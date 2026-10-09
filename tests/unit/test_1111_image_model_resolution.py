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


# ---------- ① 注入层：model 与 provider 各自独立解析（死分支根因） ----------


def test_1111_injection_fills_model_from_global_settings(monkeypatch):
    """草稿选择命中（ctx.image_provider 非空）时，model 也必须被注入。

    旧实现该情形只写 provider_id，`args['model']` 永远缺席 ⇒ 现场日志
    「[image_generate] batch provider 注入（草稿选择）: custom-api-2」之后
    没有任何 model 注入行。
    """
    import src.video_agent.core.provider_config as pc
    from src.video_agent.tools.document_tools import ImageGenerateTool

    class _Port:
        @staticmethod
        def spec_media_preference(state, kind="image"):
            return ("custom-api-2", _FLASH)

    monkeypatch.setattr(pc, "spec_media_preference", _Port.spec_media_preference)
    import src.video_agent.core.ports as ports_mod
    monkeypatch.setattr(ports_mod, "provider_config_port", lambda: _Port)

    tool = ImageGenerateTool()
    ctx = _ctx(image_provider="custom-api-2", state={})
    args = {"mode": "batch", "target": "all_keyElements"}
    tool.apply_provider_defaults(args, ctx)

    assert args["provider_id"] == "custom-api-2"
    assert args["model"] == _FLASH, (
        "全局设置的模型必须随同源供应商注入（事故 1111 根因①：该分支只写 provider）")


def test_1111_injection_model_not_borrowed_across_providers(monkeypatch):
    """provider 与全局设置**不同源**时不得套用其模型（防张冠李戴）。

    草稿自带其它供应商时，全局设置的模型不适用，应留给下游按草稿/供应商解析。
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
        args, _ctx(image_provider="other-provider", state={}))
    assert args["provider_id"] == "other-provider"
    assert not args.get("model"), "跨供应商不得借用全局设置的模型"


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
    assert result.data.get("model") == _FLASH
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


# ---------- 小工具 ----------


def _ctx(image_provider="", state=None):
    from src.video_agent.tools.base import ProviderInjectionContext
    return ProviderInjectionContext(
        state=state if state is not None else {},
        image_provider=image_provider,
        image_aspect_ratio="",
        selected_draft_id="",
        selected_type="",
    )


async def _async_echo(v):
    return v


async def _async_endpoint(pid, model):
    return ("", "", model)
