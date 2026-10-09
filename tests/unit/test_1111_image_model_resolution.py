# -*- coding: utf-8 -*-
"""事故 1111 回归钉：Agent 批量生图的模型解析链与目标种类过滤。

事故现场（2026-10-08，工作台「1111」`proj-1791464775-7e017914`，修复于 2026-10-09）：
Agent 调 `image_generate(target='all_keyElements')` 后 **15 个任务全部失败**，
上游报 `No accounts available with quota for model: gemini-3-pro-image`；而用户
手动点同一批卡**成功**（用的是草稿卡上的 `gemini-3.1-flash-image`）。

三条根因（本文件逐条钉死）：
  ① 注入层死分支：model 注入嵌在 `elif spec_pid` 内，而 `ctx.image_provider`
     自身即回落 `default_image_provider_id` ⇒ 两分支同源互斥 ⇒ 该 elif 恒不成立，
     `args["model"]` 永不被写；
  ② 工具层短路：model 解析嵌在 `if not provider_id` 内，provider 已有值即整块跳过，
     且回退链**从不读草稿自带 `imageModel`**；
  ③ 派发层静默兜底：空 model 被换成 `image_models[0]`（列表首位，恰是无额度的那个），
     全程零告警 —— 用户配的 `gemini-3.1-flash-image` 就此落空。

附带发现：`target='all_keyElements'` 只判「有无提示词」、不判媒体种类，
把同组 5 张音色卡（mediaType=audio）也拉去生图（15 = 10 图 + 5 音色）。
"""
import asyncio
import json

import pytest

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult

# 现场真实配置：列表首位（pro）无额度，用户全局设置选的是 flash
_PRO = "gemini-3-pro-image"
_FLASH = "gemini-3.1-flash-image"


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    yield StateManager(str(tmp_path))
    StateManager.reset_instance()


@pytest.fixture(autouse=True)
def _ensure_platform_tools():
    from src.video_agent.tools.document_tools import register_document_tools
    from src.video_agent.tools.storyboard_tools import register_storyboard_tools
    register_storyboard_tools()
    register_document_tools()


def _seed(svc):
    """复现 1111 现场：同组内 1 张音色卡（audio）+ 1 张设定图卡（image）。"""
    svc.state_dict["shots"] = []
    svc.state_dict["keyElements"] = [{
        "id": "ke-1", "title": "Element_程心",
        "drafts": [
            {"id": "d-voice", "label": "程心_音色卡", "tag": "已确认", "mediaType": "audio",
             "audioType": "voice", "prompt": "年轻知性女性音，柔和清澈略带沙哑。"},
            {"id": "d-view", "label": "程心_三视图设定图", "tag": "已确认", "mediaType": "image",
             "prompt": "角色三视图设定图：东方面孔女性，齐肩发，冷白影棚光。",
             "imageProviderId": "custom-api-2", "imageModel": _FLASH, "aspectRatio": "16:9"},
        ],
    }]


# ---------- ① 注入层不再解析 batch 渠道（消除「两处各写一遍」的复述） ----------


def test_1111_injection_leaves_batch_channel_to_tool(monkeypatch):
    """batch 轨：注入层**不写** provider_id/model —— 渠道解析唯一落点 = 工具。

    事故 1111 根因①（model 注入嵌在 `elif spec_pid` 内恒不可达）**长在
    「注入层与工具各解析一份」这份重复里**。2026-10-09 用户裁决「执行时按卡内
    已填参数」后，batch 解析整体收回 `_execute_batch`（逐卡），本处只留 single。
    消除重复即消除该 bug 的温床：即便将来再改优先级，也只有一处可改。
    """
    import src.video_agent.core.provider_config as pc
    import src.video_agent.core.ports as ports_mod
    from src.video_agent.tools.document_tools import ImageGenerateTool

    class _Port:
        @staticmethod
        def spec_media_preference(state, kind="image"):
            return ("custom-api-2", _FLASH)

    monkeypatch.setattr(pc, "spec_media_preference", _Port.spec_media_preference)
    monkeypatch.setattr(ports_mod, "provider_config_port", lambda: _Port)

    args = {"mode": "batch", "target": "all_keyElements"}
    ImageGenerateTool().apply_provider_defaults(
        args, _ctx(image_provider="custom-api-2", state={}))
    assert not str(args.get("provider_id") or "").strip(), \
        "batch 渠道不得在注入层解析（唯一落点 = _execute_batch 逐卡）"
    assert not str(args.get("model") or "").strip()


def test_1111_injection_still_serves_single_mode(monkeypatch):
    """single 轨照旧注入 provider/画幅（批次回归：移除 batch 分支不得误伤 single）。"""
    import src.video_agent.core.provider_config as pc
    import src.video_agent.core.ports as ports_mod
    from src.video_agent.tools.document_tools import ImageGenerateTool

    class _Port:
        @staticmethod
        def spec_media_preference(state, kind="image"):
            return ("custom-api-2", _FLASH)

    monkeypatch.setattr(pc, "spec_media_preference", _Port.spec_media_preference)
    monkeypatch.setattr(ports_mod, "provider_config_port", lambda: _Port)

    args = {"mode": "single", "prompt": "一只猫"}
    ImageGenerateTool().apply_provider_defaults(
        args, _ctx(image_provider="", state={}, aspect="9:16"))
    assert args["adapter_provider"] == "custom-api-2", "single 轨仍按全局设置注入"
    assert args["aspect_ratio"] == "9:16", "single 轨仍注入画幅"


# ---------- ② 工具层：模型回退链独立于供应商链 ----------


def _stub_gen(monkeypatch, captured):
    from src.video_agent.web import generation_dispatch

    async def fake_gen(provider_id, model, prompt, **kwargs):
        captured.append((provider_id, model, prompt))
        return "http://fake/img.png"

    monkeypatch.setattr(generation_dispatch, "generate_image_via_provider", fake_gen)


async def test_1111_model_resolved_from_draft_when_provider_already_set(
        svc, monkeypatch):
    """provider 已由注入层给定时，model 仍要按草稿自带 `imageModel` 解析。

    事故 1111 根因②：两处解析同嵌在一个 `if not provider_id` 里，
    provider 有值 ⇒ model 整块不解析 ⇒ 空 model 落到派发层被静默换名。
    """
    from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool

    monkeypatch.setattr(StateManager, "_instance", svc)
    _seed(svc)
    captured = []
    _stub_gen(monkeypatch, captured)

    # 模拟注入层：provider 已定，但 model 仍未解析
    result = await ImageGenerateTool().aexecute(
        GenerateImageInput(target="all_keyElements", provider_id="custom-api-2"))
    assert result.success
    await asyncio.sleep(0.3)

    assert captured, "生图任务必须真的提交"
    assert captured[0][:2] == ("custom-api-2", _FLASH), (
        f"应取草稿自带的 {_FLASH}，实际 {captured[0][:2]}（事故 1111 根因②）")


async def test_1111_model_falls_back_to_global_settings_when_same_provider(
        svc, monkeypatch):
    """草稿没写模型、但 provider 与全局设置同源 → 取全局设置的模型（用户意图）。"""
    from src.video_agent.tools import document_tools
    from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool

    monkeypatch.setattr(StateManager, "_instance", svc)
    _seed(svc)
    # 草稿去掉自带模型，仅留 provider
    svc.state_dict["keyElements"][0]["drafts"][1].pop("imageModel", None)
    monkeypatch.setattr(document_tools, "spec_media_preference",
                        lambda state: ("custom-api-2", _FLASH))
    captured = []
    _stub_gen(monkeypatch, captured)

    result = await ImageGenerateTool().aexecute(
        GenerateImageInput(target="all_keyElements", provider_id="custom-api-2"))
    assert result.success
    await asyncio.sleep(0.3)
    assert captured[0][:2] == ("custom-api-2", _FLASH), (
        "同源时应回退全局设置模型；旧实现此处落到派发层首位模型")


async def test_1111_receipt_reports_actual_model(svc, monkeypatch):
    """回执必须写明实际生效的渠道与模型（§2.5 平台改写须模型可见）。

    旧回执只说「已提交 N 个生图任务」⇒ 模型无从察觉自己指定的模型被换掉。
    """
    from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool

    monkeypatch.setattr(StateManager, "_instance", svc)
    _seed(svc)
    _stub_gen(monkeypatch, [])

    result = await ImageGenerateTool().aexecute(
        GenerateImageInput(target="all_keyElements", provider_id="custom-api-2"))
    assert result.success
    assert result.data.get("channels") == [f"custom-api-2 / {_FLASH}"]
    assert _FLASH in result.data.get("detail", "")
    await asyncio.sleep(0.3)


# ---------- ③ 派发层：静默兜底改为留痕 ----------


async def test_1111_dispatch_fallback_is_logged_not_silent(monkeypatch, caplog):
    """空 model 走到派发层时，兜底取值必须 WARNING 留痕（不得静默换名）。"""
    from loguru import logger as _logger

    from src.video_agent.web import generation_dispatch as gd

    class _Cfg:
        @staticmethod
        async def get_provider_config_async(pid):
            return {"image_models": [_PRO, _FLASH]}

    monkeypatch.setattr(gd, "get_provider_config_async",
                        _Cfg.get_provider_config_async)
    monkeypatch.setattr(gd, "resolve_provider_ref_async",
                        _async_echo)

    seen = []
    sink_id = _logger.add(lambda m: seen.append(m.record["level"].name + "|" + m.record["message"]),
                          level="WARNING")
    try:
        captured_model = {}

        async def fake_adapter_gen(*a, **k):
            raise RuntimeError("stop here")

        class _Adapter:
            def __init__(self, **kwargs):
                captured_model["model"] = kwargs.get("model")

            async def generate_image(self, *a, **k):
                raise RuntimeError("stop here")

            async def close(self):
                pass

        monkeypatch.setattr(gd, "OpenAICompatImageAdapter", _Adapter)
        monkeypatch.setattr(gd, "resolve_openai_endpoint_async",
                            _async_endpoint)
        with pytest.raises(Exception):
            await gd.generate_image_via_provider(
                "custom-api-2", "", "一只猫", size="1024x1024")
    finally:
        _logger.remove(sink_id)

    assert captured_model.get("model") == _PRO, "兜底仍取列表首位（既有兜底语义不变）"
    assert any("兜底" in s and "WARNING" in s for s in seen), (
        f"静默换名必须留痕（事故 1111 根因③），实际日志: {seen}")


# ---------- ④ 目标种类过滤：音色卡不进生图批 ----------


async def test_1111_audio_cards_excluded_from_image_batch(svc, monkeypatch):
    """`all_keyElements` 只收图像卡：音色卡（mediaType=audio）不得进生图批。

    事故 1111 附带发现：15 个任务 = 10 图 + 5 音色，音色描述词被当画面提示词送出。
    """
    from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool

    monkeypatch.setattr(StateManager, "_instance", svc)
    _seed(svc)
    captured = []
    _stub_gen(monkeypatch, captured)

    result = await ImageGenerateTool().aexecute(
        GenerateImageInput(target="all_keyElements", provider_id="custom-api-2"))
    assert result.success
    assert result.data["submitted"] == 1, (
        f"只应有 1 张图像卡参与，实际 {result.data['submitted']}（音色卡被卷入=事故 1111）")
    await asyncio.sleep(0.3)

    # 送审提示词必须是图像卡的，音色描述词一个字都不该出现
    prompts = [c[2] for c in captured]
    assert prompts == ["角色三视图设定图：东方面孔女性，齐肩发，冷白影棚光。"], (
        f"音色卡不得参与生图，实际送审提示词: {prompts}")


def test_1111_batch_media_targets_single_source():
    """种类判据单一事实源：写口与闸机同引 ops.batch_media_targets。"""
    state = {
        "keyElements": [{
            "id": "ke-1", "title": "Element_A",
            "drafts": [
                {"id": "d-img", "mediaType": "image", "prompt": "画面"},
                {"id": "d-aud", "mediaType": "audio", "prompt": "音色"},
                {"id": "d-none", "mediaType": "image", "prompt": "  "},
            ],
        }],
        "shots": [], "audioItems": [],
    }
    img = ops.batch_media_targets(state, "all_keyElements", media_type="image")
    assert [d["id"] for _g, d, _t in img] == ["d-img"], "只收有提示词的图像卡"
    aud = ops.batch_media_targets(state, "all_keyElements", media_type="audio")
    assert [d["id"] for _g, d, _t in aud] == ["d-aud"]
    # 非批量关键字交回调用方走定点路径
    assert ops.batch_media_targets(state, "d-img", media_type="image") == []


def test_1111_batch_target_keyword_is_case_insensitive():
    """批量关键字判定必须大小写不敏感（键是小写，模型常传驼峰 all_keyElements）。

    这是本批修复过程中真实踩到的坑：`target in BATCH_MEDIA_TARGETS` 对
    `all_keyElements` 假阴性 ⇒ 走进定点 draft_id 分支报「格式非法」。
    """
    assert ops.is_batch_media_target("all_keyElements")
    assert ops.is_batch_media_target("all_keyelements")
    assert ops.is_batch_media_target("ALL_SHOTS")
    assert ops.is_batch_media_target("all_shot")
    assert not ops.is_batch_media_target("d-ke1")
    assert not ops.is_batch_media_target("")


def test_1111_gate_and_tool_share_target_set():
    """闸机判的目标集必须**就是**工具会提交的目标集（G4 同类路径全覆盖）。"""
    import inspect

    from src.video_agent.core import fc_gates
    src = inspect.getsource(fc_gates.gen_confirm_gate)
    assert "batch_media_targets" in src, (
        "闸机须走写口同一实现，否则闸机校验的目标集 ≠ 工具实际提交的目标集")


# ---------- ⑤ 卡优先（用户裁决 2026-10-09：「执行时按卡内已填参数」） ----------


async def test_1111_card_channel_wins_over_global_settings(svc, monkeypatch):
    """卡上渠道 ≠ 全局设置时，**用卡**（= 用户手动点卡那条路）。

    事故 1111 的分歧点：用户手动点卡成功（读卡上的 flash），Agent 失败
    （渠道被全局设置/兜底改写）。用户裁决「执行时按卡内已填参数」后，
    两条路同源，不再存在分歧。
    """
    from src.video_agent.tools import document_tools
    from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool

    monkeypatch.setattr(StateManager, "_instance", svc)
    _seed(svc)
    # 全局设置指向另一个渠道；卡上写明 custom-api-2 / flash
    monkeypatch.setattr(document_tools, "spec_media_preference",
                        lambda state: ("agnes-ai", "agnes-image-2.1-flash"))
    captured = []
    _stub_gen(monkeypatch, captured)

    result = await ImageGenerateTool().aexecute(
        GenerateImageInput(target="all_keyElements"))
    assert result.success
    await asyncio.sleep(0.3)
    assert captured[0][:2] == ("custom-api-2", _FLASH), (
        f"卡上渠道必须生效，实际 {captured[0][:2]}（用户裁决：按卡内已填参数）")


async def test_1111_mixed_channels_resolved_per_card(svc, monkeypatch):
    """同批不同卡可以是不同渠道 —— 逐卡解析，不得整批套用同一对值。

    旧实现整批只解析一对 (provider, model)，跨供应商的卡会被其中一对覆盖
    （9999 实测有 4 张卡与全局设置不同）。"""
    from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool

    monkeypatch.setattr(StateManager, "_instance", svc)
    svc.state_dict["shots"] = []
    svc.state_dict["keyElements"] = [
        {"id": "ke-1", "title": "Element_A", "drafts": [
            {"id": "d-a", "tag": "已确认", "mediaType": "image", "prompt": "卡A",
             "imageProviderId": "custom-api-2", "imageModel": _FLASH, "aspectRatio": "16:9"}]},
        {"id": "ke-2", "title": "Element_B", "drafts": [
            {"id": "d-b", "tag": "已确认", "mediaType": "image", "prompt": "卡B",
             "imageProviderId": "modelscope", "imageModel": "Qwen/Qwen-Image-2512",
             "aspectRatio": "16:9"}]},
    ]
    captured = []
    _stub_gen(monkeypatch, captured)

    result = await ImageGenerateTool().aexecute(
        GenerateImageInput(target="all_keyElements"))
    assert result.success and result.data["submitted"] == 2
    await asyncio.sleep(0.3)

    got = {(c[0], c[1]) for c in captured}
    assert got == {("custom-api-2", _FLASH), ("modelscope", "Qwen/Qwen-Image-2512")}, \
        f"两张卡应各走自己的渠道，实际 {got}"
    # 回执把两个渠道都列出来（§2.5 可见）
    assert len(result.data["channels"]) == 2


async def test_1111_unstamped_card_falls_back_to_global_then_logs(svc, monkeypatch):
    """卡上无渠道（存量/漏补印）→ 回退全局设置；全局也没有才用供应商首个模型。"""
    from src.video_agent.tools import document_tools
    from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool

    monkeypatch.setattr(StateManager, "_instance", svc)
    _seed(svc)
    svc.state_dict["keyElements"][0]["drafts"][1].pop("imageProviderId", None)
    svc.state_dict["keyElements"][0]["drafts"][1].pop("imageModel", None)
    monkeypatch.setattr(document_tools, "spec_media_preference",
                        lambda state: ("custom-api-2", _FLASH))
    captured = []
    _stub_gen(monkeypatch, captured)

    result = await ImageGenerateTool().aexecute(
        GenerateImageInput(target="all_keyElements"))
    assert result.success
    await asyncio.sleep(0.3)
    assert captured[0][:2] == ("custom-api-2", _FLASH), "卡无值时回退全局设置"


def test_1111_stamp_only_fills_empty_never_overwrites(set_global_setting):
    """建卡补印**只补空、不覆盖**已有值（用户逐卡改选必须存活）。"""
    from src.video_agent.core.provider_config import stamp_draft_spec_preference

    set_global_setting("default_image_provider_id", "custom-api-2")
    set_global_setting("default_image_model", _FLASH)

    # 已有值 → 不被覆盖
    d1 = {"mediaType": "image", "imageProviderId": "user-chosen", "imageModel": "user-model"}
    stamp_draft_spec_preference({}, d1, "keyElements")
    assert d1["imageProviderId"] == "user-chosen" and d1["imageModel"] == "user-model"

    # 空值 → 补印成全局设置（结构保证：卡上必有值，执行期无须靠回退链猜）
    d2 = {"mediaType": "image"}
    stamp_draft_spec_preference({}, d2, "keyElements")
    assert d2.get("imageProviderId") == "custom-api-2"
    assert d2.get("imageModel") == _FLASH


def test_1111_stamp_covers_create_group_path():
    """建卡补印必须覆盖**两条**建卡路径（G4）：add_draft 与 create_group 附带草稿。

    事故 1111 复查发现 `create_group` 的附带草稿路径**漏了补印** ⇒ 由此建出的
    卡渠道为空。用户裁决「执行时按卡内已填参数」要求卡上必有值（结构保证），
    故该漏口必须补上并钉死。
    """
    import inspect

    from src.video_agent.tools import storyboard_tools
    src = inspect.getsource(storyboard_tools.StoryboardCreateGroupTool.aexecute)
    assert "stamp_draft_spec_preference" in src, \
        "create_group 附带草稿路径必须补印（否则卡上无渠道，回退链兜底）"
    src_add = inspect.getsource(storyboard_tools.StoryboardAddDraftTool.aexecute)
    assert "stamp_draft_spec_preference" in src_add, "add_draft 路径必须补印"


# ---------- 小工具 ----------


def _ctx(image_provider="", state=None, aspect=""):
    from src.video_agent.tools.base import ProviderInjectionContext
    return ProviderInjectionContext(
        state=state if state is not None else {},
        image_provider=image_provider,
        image_aspect_ratio=aspect,
        selected_draft_id="",
        selected_type="",
    )


async def _async_echo(v):
    return v


async def _async_endpoint(pid, model):
    return ("", "", model)
