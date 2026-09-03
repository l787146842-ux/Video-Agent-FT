"""混合形态工具边界：确认状态闭环 + 生成确认闸 + 阶段工具裁剪 + 首拆闸/即时暂停/文档卡片"""
import json

import pytest

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core import fc_gates, prompt_gates
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult


def _async_return(value):
    """构造返回固定值的 async callable（monkeypatch 异步函数用）"""
    async def _f():
        return value
    return _f


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    yield StateManager(str(tmp_path))
    StateManager.reset_instance()


@pytest.fixture(autouse=True)
def _ensure_platform_tools():
    # 显式重注册：同序其它用例的 ToolManager.reset() 可能清空全局
    # 注册表，确认闸读 approval_tier 后未注册即拦，本文件不依赖导入副作用
    #（与 test_pause_structure 同口径）
    from src.video_agent.tools.document_tools import register_document_tools
    from src.video_agent.tools.storyboard_tools import register_storyboard_tools
    register_storyboard_tools()
    register_document_tools()


def _seed_ke_draft(svc, tag="Agent", prompt="白发老者站在冥王星冰原上，手持拐杖，伦勃朗式光影，宿命感。"):
    svc.state_dict["keyElements"] = [{
        "id": "ke-t", "title": "Element_测试",
        "drafts": [{"id": "d-ke1", "label": "概念图", "tag": tag, "prompt": prompt}],
    }]
    return "d-ke1"


# ---------- 确认状态闭环 ----------

def test_patch_prompt_invalidates_confirmation():
    """重写即作废：已确认草稿的提示词被重写后 tag 重置为 Agent"""
    draft = {"id": "d1", "tag": "已确认", "prompt": "旧提示词"}
    changed, dropped = ops.patch_draft(draft, {"prompt": "新提示词内容"})
    assert changed is True and dropped == []
    assert draft["tag"] == "Agent"


def test_patch_other_fields_keeps_confirmation():
    """非提示词字段修改不作废确认；同值重写也不作废"""
    draft = {"id": "d1", "tag": "已确认", "prompt": "提示词"}
    ops.patch_draft(draft, {"label": "新标签"})
    assert draft["tag"] == "已确认"
    ops.patch_draft(draft, {"prompt": "提示词"})  # 同值
    assert draft["tag"] == "已确认"


def test_confirm_draft_patch_keeps_tag():
    """patch 同时带 tag 时以 patch 为准（confirm_draft 路径不被误重置）"""
    draft = {"id": "d1", "tag": "Agent", "prompt": "提示词"}
    ops.patch_draft(draft, {"tag": "已确认"})
    assert draft["tag"] == "已确认"


# test_presented_record_and_promote_on_user_reply 已随 Q2 裁决 2026-09-01 退役删除：
# 文本轨写提示词记 presented（executor.execute update_draft）随执行器家族退役；
# presented 记录改由 FC 轨 fc_tool_runner 写入（消费/晋升语义由下方
# test_unrelated_message_consumes_pending_and_promotes 等用例钉死）。


def test_rewritten_draft_not_promoted(svc):
    """展示后被重写的草稿不会被误晋升（写入时已重置 tag，晋升只认 presented 列表中未重写的）"""
    from src.video_agent.web.chat_service import _consume_pending_confirmation
    draft_id = _seed_ke_draft(svc, tag="Agent")
    svc.state_dict.setdefault("interaction", {})["drafts_presented"] = [draft_id]
    # 模拟：展示后又被重写（tag 重置为 Agent，仍在 presented 中）
    # 用户回应前没有再展示 → 依然晋升（因为重写后的版本也属于本轮交付物）；
    # 真正的保护是：重写发生在"用户回应之后"时 tag 重置，生成闸重新拦截
    _consume_pending_confirmation(svc, "继续")
    assert svc.state_dict["keyElements"][0]["drafts"][0]["tag"] == "已确认"
    # 确认后再次重写 → 作废，需重新确认
    ops.patch_draft(svc.state_dict["keyElements"][0]["drafts"][0],
                    {"prompt": "艾 AA 短发干练，深蓝色轻型宇航服，顶侧冷白主光，坚毅神情。"})
    assert svc.state_dict["keyElements"][0]["drafts"][0]["tag"] == "Agent"


def test_unrelated_message_consumes_pending_and_promotes(svc):
    """执行优先：任何用户消息都消费暂停态并晋升已展示草稿（不再拦截）"""
    from src.video_agent.web.chat_service import _consume_pending_confirmation
    draft_id = _seed_ke_draft(svc, tag="Agent")
    inter = svc.state_dict.setdefault("interaction", {})
    inter["storyboard_pending"] = True
    inter["drafts_presented"] = [draft_id]
    inter["awaiting_confirmation"] = True
    inter["confirmation_message"] = "请审阅"

    note = _consume_pending_confirmation(svc, "今天天气如何？")
    assert "暂停" in note
    assert svc.state_dict["keyElements"][0]["drafts"][0]["tag"] == "已确认"
    assert inter["storyboard_pending"] is False
    assert inter["awaiting_confirmation"] is False
    assert inter["drafts_presented"] == []


def test_review_signal_unlocks_pending_and_promotes(svc):
    """调整意见同样解除 pending 并晋升草稿（用户新指令即继续）"""
    from src.video_agent.web.chat_service import _consume_pending_confirmation
    draft_id = _seed_ke_draft(svc, tag="Agent")
    inter = svc.state_dict.setdefault("interaction", {})
    inter["storyboard_pending"] = True
    inter["drafts_presented"] = [draft_id]
    inter["awaiting_confirmation"] = True
    inter["confirmation_message"] = "请审阅"

    note = _consume_pending_confirmation(svc, "把主角改成红色")
    # 新基线（客观账本式文案）：注入上一轮暂停事实 + 本条消息即对该暂停的回应
    assert "暂停等待确认" in note and "请审阅" in note
    assert inter["storyboard_pending"] is False
    assert inter["awaiting_confirmation"] is False
    assert svc.state_dict["keyElements"][0]["drafts"][0]["tag"] == "已确认"
    assert inter["drafts_presented"] == []


def test_select_signal_promotes(svc):
    """选择候选项属于确认信号：晋升草稿并清空 presented"""
    from src.video_agent.web.chat_service import _consume_pending_confirmation
    draft_id = _seed_ke_draft(svc, tag="Agent")
    inter = svc.state_dict.setdefault("interaction", {})
    inter["drafts_presented"] = [draft_id]

    _consume_pending_confirmation(svc, "选择第 2 个方案")
    assert svc.state_dict["keyElements"][0]["drafts"][0]["tag"] == "已确认"
    assert inter["drafts_presented"] == []


# test_manual_confirm_draft_still_works 已随 Q2 裁决 2026-09-01 退役删除：
# 文本轨 confirm_draft 动作随执行器家族退役；手动确认落点归 FC 轨
# storyboard_confirm_draft 工具（工具注册与风险分级闸已钉死）。


# ---------- 生成确认闸（文本轨）用例已随 Q2 裁决 2026-09-01 退役删除 ----------
# test_gen_gate_blocks_model_self_skip_text_track /
# test_gen_gate_partial_confirmed_filters_unconfirmed /
# test_gen_gate_inactive_without_skill：文本轨生成动作（executor.execute
# generate_image）随执行器家族退役；拦截/坚持/放行/部分确认整批硬拒语义由
# 下方 FC 轨用例与 guard_pipeline.evaluate_gen_confirm 唯一实现直测钉死。


# ---------- 生成确认闸（FC 轨） ----------

def _gen_ctx(state, injected_skill="任意 Skill", override=False):
    return fc_gates.GateContext(
        state=lambda: state, injected_skill=injected_skill,
        gate_override=override)


def test_fc_gen_gate_blocks_without_user_insist(monkeypatch):
    """4444：FC 轨未确认草稿——本轮无跳过指令 → 返回拒收错误；
    用户本轮要求（gate_override）→ 放行+警告；确认后放行。"""
    state = {"keyElements": [{
        "id": "ke-1", "title": "E", "drafts": [
            {"id": "d1", "tag": "Agent", "prompt": "深空背景中的二向箔，冷白荧光，极简硬科幻美学。"},
        ]}]}
    ctx = _gen_ctx(state)
    err = fc_gates.gen_confirm_gate(
        ctx, "image_generate", {"target": "all_keyElements"})
    assert err and "拦截" in err  # 模型自发跳确认被拒收
    # 用户本轮明确要求 → 放行+警告
    ctx2 = _gen_ctx(state, override="all")
    assert fc_gates.gen_confirm_gate(
        ctx2, "image_generate", {"target": "all_keyElements"}) is None
    assert ctx2.warnings and "确认" in ctx2.warnings[0]
    # 全部确认后同样放行
    state["keyElements"][0]["drafts"][0]["tag"] = "已确认"
    assert fc_gates.gen_confirm_gate(
        ctx, "image_generate", {"target": "all_keyElements"}) is None
    # 无 Skill 不拦
    state["keyElements"][0]["drafts"][0]["tag"] = "Agent"
    ctx3 = _gen_ctx(state, injected_skill="")
    assert fc_gates.gen_confirm_gate(
        ctx3, "image_generate", {"target": "all_keyElements"}) is None


def test_fc_gen_gate_no_targets_passes(monkeypatch):
    """无目标草稿时放行（交给工具自身报错，不误伤）"""
    ctx = _gen_ctx({"keyElements": []})
    assert fc_gates.gen_confirm_gate(
        ctx, "image_generate", {"target": "all_keyElements"}) is None


def test_fc_gen_gate_exec_preference_auto_decide(monkeypatch, set_global_setting):
    """批 B：auto_decide + 活跃 Skill 在场 → 系统代发同意放行（留痕警告）；
    无活跃 Skill → 闸不激活按现状放行（与今日逐字节一致）。"""
    state = {"keyElements": [{
        "id": "ke-1", "title": "E", "drafts": [
            {"id": "d1", "tag": "Agent", "prompt": "深空背景中的二向箔，冷白荧光。"},
        ]}]}
    set_global_setting("execution_preference", "auto_decide")
    ctx = _gen_ctx(state)
    assert fc_gates.gen_confirm_gate(
        ctx, "image_generate", {"target": "all_keyElements"}) is None
    assert ctx.warnings and "自动决定" in ctx.warnings[0]
    # 无活跃 Skill → 闸不激活，不拒无警告（现状语义）
    ctx2 = _gen_ctx(state, injected_skill="")
    assert fc_gates.gen_confirm_gate(
        ctx2, "image_generate", {"target": "all_keyElements"}) is None
    assert ctx2.warnings == []


def test_fc_gen_gate_exec_preference_generate_directly(monkeypatch, set_global_setting):
    """批 B：generate_directly 恒免确认（未确认草稿也放行，留痕警告）；
    回默认档后同场景恢复拦截（红线语义随时可回退）。"""
    state = {"keyElements": [{
        "id": "ke-1", "title": "E", "drafts": [
            {"id": "d1", "tag": "Agent", "prompt": "深空背景中的二向箔，冷白荧光。"},
        ]}]}
    set_global_setting("execution_preference", "generate_directly")
    ctx = _gen_ctx(state)
    assert fc_gates.gen_confirm_gate(
        ctx, "image_generate", {"target": "all_keyElements"}) is None
    assert ctx.warnings and "直接生成" in ctx.warnings[0]
    # 回落默认档 → 同场景恢复拦截（免确认仅由偏好控制，不侵入兜底逻辑）
    set_global_setting("execution_preference", "confirm_before_gen")
    ctx3 = _gen_ctx(state)
    err = fc_gates.gen_confirm_gate(
        ctx3, "image_generate", {"target": "all_keyElements"})
    assert err and "拦截" in err


# ---------- 阶段探测工具裁剪 ----------

def test_stage_restrictions_spec_but_no_storyboard():
    excluded, note = prompt_gates.stage_tool_restrictions({
        "documents": [{"name": "制片规格.md", "content": "正文"}],
        "keyElements": [], "shots": [], "audioItems": [],
    })
    assert excluded == prompt_gates.GENERATION_STAGE_TOOLS
    assert "storyboard_create_group" not in excluded
    assert "结构" in note


def test_stage_restrictions_storyboard_ready():
    excluded, note = prompt_gates.stage_tool_restrictions({
        "documents": [{"name": "制片规格.md", "content": "正文"}],
        "keyElements": [{"id": "ke-1", "drafts": []}], "shots": [], "audioItems": [],
    })
    assert excluded == frozenset() and note == ""


def test_planner_stage_pruning(svc, monkeypatch):
    """planner._compute_excluded_tools：Skill 激活 + strict 时按阶段裁剪，
    且裁剪⇔解释同源签发（任务#15 P2：阶段裁剪的声明门控已废，
    条件单一事实源归 planner；成对断言详见 test_prompt_assembly_snapshot）"""
    from src.video_agent.core.planner import Planner, PlannerContext

    planner = Planner.__new__(Planner)  # 绕过重量级构造，只测裁剪逻辑
    planner.state_manager = svc

    def make_ctx(skill):
        ctx = PlannerContext()
        ctx.use_studio_context = True
        ctx.skill_name = skill
        return ctx

    # 无规格文档 + Skill 激活（2026-08-31 用户裁决：规格锁工具退役）：
    # 故事板工具不再裁剪；故事板为空时仅生成工具裁剪，且携带解释文案
    svc.state_dict["documents"] = []
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    ctx1 = make_ctx("剧本生视频（需上传剧本）")
    excluded = planner._compute_excluded_tools(ctx1)
    assert "storyboard_create_group" not in excluded
    assert "generate_video" in excluded
    assert "image_generate" not in excluded  # 单张应急轨任意阶段可见
    assert ctx1.stage_excluded_tools and "当前阶段工具边界" in ctx1.stage_note
    # 无 Skill：不追加阶段裁剪，也不签发解释
    ctx2 = make_ctx("")
    excluded2 = planner._compute_excluded_tools(ctx2)
    assert "storyboard_create_group" not in excluded2
    assert ctx2.stage_excluded_tools == frozenset() and ctx2.stage_note == ""


# ---------- 首拆只允许关键元素（8888 事故：规格确认后一次性拆出分镜+音频） ----------

# test_ke_first_gate_text_track / test_ke_first_gate_allows_shots_after_elements_exist
# 已随 Q2 裁决 2026-09-01 退役删除：文本轨 add_group 随执行器家族退役；
# 首拆语义由下方 FC 轨同覆盖用例钉死（G4 同类路径）。


def test_ke_first_gate_fc_track(monkeypatch):
    """0817 用户裁决：FC 轨建 shot 无首拆警告。
    任务#36 护栏移植后：分镜 sceneRefs 完整度由 fc_gates.structure_integrity_gate
    机械校验（承接原 exec_common），故建分镜须带客观引用。"""
    import asyncio
    runner = FCToolRunner(tool_manager=_StubToolManager())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {
        "analysis": {"summary": "一句话总结"},  # audit-0819e：前置就位
        "documents": [{"name": "制片规格.md", "content": "规格内容"}],
        "keyElements": [{"id": "ke-1", "title": "程心", "drafts": []}],
        "shots": [], "audioItems": [],
    }))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "storyboard_create_group",
            "arguments": json.dumps({"group_type": "shot", "title": "Shot_1",
                                     "scene_refs": ["ke-1"]})}},
    ])
    applied, *_rest = asyncio.run(runner.execute(response, injected_skill="任意 Skill"))
    assert applied == 1
    assert not any("首次" in w for w in runner.gate_warnings)


# ---------- pending 批内即时置位（8888 事故：同批建结构又写提示词） ----------
# test_pending_immediate_rejects_short_prompt_in_same_batch 已随 Q2 裁决 2026-09-01 退役删除：
# 文本轨同批建结构+写提示词随执行器家族退役；批内即时拒绝语义由下方
# test_fc_pending_window_rejects_bad_prompt（test_prompt_gates）等 FC 轨用例钉死。


# ---------- FC 轨文档收集与规格暂停文案（8888 事故：无文档卡片无下一步指引） ----------

class _StubToolManager:
    async def invoke_tool(self, name, args):
        return ToolResult(success=True, data={})


def test_fc_spec_doc_written_keeps_model_pause(monkeypatch):
    """同批已自发 workflow_pause：模型暂停不被系统规格卡覆盖（永不没收暂停）"""
    import asyncio
    runner = FCToolRunner(tool_manager=_StubToolManager())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "document_write",
            "arguments": json.dumps({"name": "制片规格.md", "content": "标题：测试"})}},
        {"id": "c2", "type": "function", "function": {
            "name": "workflow_pause",
            "arguments": json.dumps({"message": "请审阅规格"})}},
    ])
    applied, confirmation, *_rest, tool_results, docs_written, _warnings, _overflow, _pause_id = asyncio.run(
        # §2.7 预期收紧：document_write 属 high，gate_override="all" 模拟用户一次性同意
        runner.execute(response, injected_skill="任意 Skill", gate_override="all"))
    assert docs_written == ["制片规格.md"]
    # v2 批4：卡问句系统组装（不没收暂停），模型原文进正文通道
    assert "请过目以上成果" in confirmation
    assert _overflow == "请审阅规格"


def test_fc_non_spec_doc_written_no_pause(monkeypatch):
    """写入普通文档（非规格）：不注入暂停，照常继续"""
    import asyncio
    runner = FCToolRunner(tool_manager=_StubToolManager())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "document_write",
            "arguments": json.dumps({"name": "大纲.md", "content": "正文"})}},
    ])
    applied, confirmation, *_rest, tool_results, docs_written, _warnings, _overflow, _pause_id = asyncio.run(
        # §2.7 预期收紧：document_write 属 high，gate_override="all" 模拟用户一次性同意
        runner.execute(response, injected_skill="任意 Skill", gate_override="all"))
    assert applied == 1
    assert docs_written == ["大纲.md"]
    assert confirmation == ""


def test_options_group_passthrough_fc(monkeypatch):
    """workflow_pause 的 options 带 group 字段时透传到 confirmation_options"""
    import asyncio
    runner = FCToolRunner(tool_manager=_StubToolManager())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "workflow_pause",
            "arguments": json.dumps({
                "message": "请选择成片规格",
                "options": [
                    {"label": "60秒", "description": "精炼版", "group": "时长"},
                    {"label": "16:9", "description": "横版", "group": "画幅"},
                ],
            })}},
    ])
    applied, confirmation, *_rest = asyncio.run(runner.execute(response, injected_skill=""))
    opts = _rest[3]  # confirmation_options 位置
    assert [o.get("group") for o in opts] == ["时长", "画幅"]


# ---------- image_generate 供应商回退链（8888 事故：LLM 传空 provider 生图全失败） ----------

class _CaptureToolManager:
    def __init__(self):
        self.captured = []

    async def invoke_tool(self, name, args):
        self.captured.append((name, dict(args)))
        return ToolResult(success=True, data={})


def test_fc_injects_provider_into_image_generate(monkeypatch):
    """LLM 未传 provider_id 时，image_generate 注入中间面板选中供应商"""
    import asyncio
    tm = _CaptureToolManager()
    runner = FCToolRunner(tool_manager=tm)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "image_generate",
            "arguments": json.dumps({"target": "all_keyElements"})}},
    ])
    asyncio.run(runner.execute(response, image_provider="custom-api",
                               gate_override="all"))
    name, args = tm.captured[0]
    assert name == "image_generate" and args.get("provider_id") == "custom-api"


def test_image_generate_fallback_to_draft_provider(svc, monkeypatch):
    """provider 留空时回退草稿自带 providerId（8888 现场：草稿均为 custom-api）"""
    import asyncio
    from src.video_agent.web import generation_dispatch
    from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool

    monkeypatch.setattr(StateManager, "_instance", svc)  # 工具内部走 get_instance，需绑定夹具
    svc.state_dict["shots"] = []
    svc.state_dict["keyElements"] = [{
        "id": "ke-1", "title": "Element_A",
        "drafts": [{"id": "d1", "tag": "已确认", "prompt": "提示词",
                    "providerId": "custom-api", "aspectRatio": "16:9"}],
    }]
    captured = []

    async def fake_gen(provider_id, model, prompt, **kwargs):
        captured.append((provider_id, model))
        return "http://fake/img.png"

    # 工具已接入统一任务管线：patch 点在 generation 模块内的实际调用处
    # 任务#11 拆分：patch 目标迁至实现模块 generation_dispatch（承重壳仅 re-export）
    monkeypatch.setattr(generation_dispatch, "generate_image_via_provider", fake_gen)
    result = asyncio.run(ImageGenerateTool().aexecute(
        GenerateImageInput(target="all_keyElements")))
    assert result.success and captured == [("custom-api", "")]


async def test_image_generate_fallback_to_first_configured_provider(svc, monkeypatch):
    """草稿也无 providerId 时回退配置中首个可用生图供应商；完全无配置时报明确错误"""
    import asyncio
    from src.video_agent.tools import document_tools
    from src.video_agent.web import generation_dispatch
    from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool

    monkeypatch.setattr(StateManager, "_instance", svc)  # 工具内部走 get_instance，需绑定夹具
    svc.state_dict["shots"] = []
    svc.state_dict["keyElements"] = [{
        "id": "ke-1", "title": "Element_A",
        "drafts": [{"id": "d1", "tag": "已确认", "prompt": "提示词"}],
    }]
    captured = []

    async def fake_gen(provider_id, model, prompt, **kwargs):
        captured.append((provider_id, model))
        return "http://fake/img.png"

    # 任务#11 拆分：patch 目标迁至实现模块 generation_dispatch（承重壳仅 re-export）
    monkeypatch.setattr(generation_dispatch, "generate_image_via_provider", fake_gen)
    # P3 下沉：document_tools 顶层 import 实现体，patch 目标 = 调用方命名空间
    monkeypatch.setattr(
        document_tools, "first_available_image_provider_async",
        _async_return(("modelscope", "Z-Image-Turbo")),
    )
    result = await ImageGenerateTool().aexecute(GenerateImageInput(target="all_keyElements"))
    assert result.success and result.data["submitted"] == 1
    await asyncio.sleep(0.3)  # 后台任务完成 fake_gen 调用
    assert captured == [("modelscope", "Z-Image-Turbo")]

    # 完全无可用生图供应商 → 返回明确错误而非「供应商 '' 未配置」
    # （首轮成功后供应商已回写草稿，此处清空以验证纯回退链末端；
    #   2026-08-15 参数隔离后需同时清空本种类字段与旧共享字段）
    svc.state_dict["keyElements"][0]["drafts"][0]["providerId"] = ""
    svc.state_dict["keyElements"][0]["drafts"][0]["imageProviderId"] = ""
    monkeypatch.setattr(
        document_tools, "first_available_image_provider_async",
        _async_return(("", "")),
    )
    result2 = await ImageGenerateTool().aexecute(GenerateImageInput(target="all_keyElements"))
    assert not result2.success and "未配置任何可用的生图供应商" in (result2.error or "")


# ---------- 规格文档媒体偏好（8888 事故：规格设定 Antigravity CLI 却走了 Grsai） ----------

_SPEC_PREF_DOC = (
    "# 制作规格 (制片规格)\n\n"
    "- 画幅比例: 16:9\n"
    "- 制作偏好: 图像生成 Antigravity CLI aotu 模型，视频生成 Seedance 2.0\n"
)


def test_extract_media_preference_antigravity_with_typo():
    """规格「图像生成 Antigravity CLI aotu 模型」解析为 gemini-cli/auto（含笔误容忍）"""
    from src.video_agent.core.provider_config import extract_media_preference
    pid, model = extract_media_preference(_SPEC_PREF_DOC, "image")
    assert pid == "gemini-cli" and model == "auto"


def test_spec_media_preference_global_settings_sole_source(set_global_setting):
    """6666 二轮：生成渠道唯一来源为顶部全局设置，规格文档不再参与。"""
    from src.video_agent.core.provider_config import spec_media_preference

    set_global_setting("default_image_provider_id", "gemini-cli")
    set_global_setting("default_image_model", "auto")
    state = {"documents": [
        {"name": "随想笔记.md", "content": "- 制作偏好: 图像生成 Grsai gpt-image-2"},
        {"name": "制片规格.md", "content": _SPEC_PREF_DOC},
    ]}
    pid, model = spec_media_preference(state, "image")
    assert pid == "gemini-cli" and model == "auto"
    assert spec_media_preference({"documents": []}, "image") == ("gemini-cli", "auto")


def test_fc_injection_prefers_spec_over_selected_draft(monkeypatch, set_global_setting):
    """image_generate 注入优先级（B7 用户裁决基线）：草稿自身（中间面板直接选择）
    > 全局设置；未带草稿供应商时才回落全局设置渠道。"""
    import asyncio

    set_global_setting("default_image_provider_id", "gemini-cli")
    set_global_setting("default_image_model", "auto")
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(
        lambda: {"documents": [{"name": "制片规格.md", "content": _SPEC_PREF_DOC}]}))

    # 带草稿供应商：草稿自身优先（B7 优先级链首位）
    tm = _CaptureToolManager()
    runner = FCToolRunner(tool_manager=tm)
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "image_generate",
            "arguments": json.dumps({"target": "all_keyElements"})}},
    ])
    asyncio.run(runner.execute(response, image_provider="custom-api",
                               gate_override="all"))
    _name, args = tm.captured[0]
    assert args.get("provider_id") == "custom-api"

    # 未带草稿供应商：回落全局设置（唯一硬参数事实源）
    tm2 = _CaptureToolManager()
    runner2 = FCToolRunner(tool_manager=tm2)
    asyncio.run(runner2.execute(response, image_provider="",
                                gate_override="all"))
    _name2, args2 = tm2.captured[0]
    assert args2.get("provider_id") == "gemini-cli" and args2.get("model") == "auto"


async def test_image_generate_spec_prefers_over_draft_provider(svc, monkeypatch, set_global_setting):
    """草稿被前端回填 Grsai，但全局设置设定 Antigravity CLI → 实际生图走全局设置"""
    import asyncio
    from src.video_agent.web import generation_dispatch
    from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool

    monkeypatch.setattr(StateManager, "_instance", svc)
    set_global_setting("default_image_provider_id", "gemini-cli")
    set_global_setting("default_image_model", "auto")
    svc.state_dict["shots"] = []
    svc.state_dict["documents"] = [
        {"name": "制片规格.md", "content": _SPEC_PREF_DOC}]
    svc.state_dict["keyElements"] = [{
        "id": "ke-1", "title": "Element_A",
        "drafts": [{"id": "d1", "tag": "已确认", "prompt": "提示词",
                    "providerId": "custom-api", "aspectRatio": "16:9"}],
    }]
    captured = []

    async def fake_gen(provider_id, model, prompt, **kwargs):
        captured.append((provider_id, model))
        return "http://fake/img.png"

    # 任务#11 拆分：patch 目标迁至实现模块 generation_dispatch（承重壳仅 re-export）
    monkeypatch.setattr(generation_dispatch, "generate_image_via_provider", fake_gen)
    result = await ImageGenerateTool().aexecute(GenerateImageInput(target="all_keyElements"))
    assert result.success and result.data["submitted"] == 1
    await asyncio.sleep(0.3)
    assert captured == [("gemini-cli", "auto")]


# ---------- 防虚报硬拦截（8888 事故：image_generate 被拦后模型仍声称「已触发生成」） ----------

class _GenFailToolManager:
    async def invoke_tool(self, name, args):
        if name == "image_generate":
            return ToolResult(success=False, error="流程闸机拦截：目标草稿未确认")
        return ToolResult(success=True, data={})


def test_false_claim_overridden_when_generation_failed(monkeypatch):
    """C1a 裁决 2026-08-31：生成防虚报覆盖退役——暂停文案不再被客观账本
    改写；生成失败事实经 ToolResult 回喂通道可见。"""
    import asyncio
    runner = FCToolRunner(tool_manager=_GenFailToolManager())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "image_generate",
            "arguments": json.dumps({"target": "all_keyElements"})}},
        {"id": "c2", "type": "function", "function": {
            "name": "workflow_pause",
            "arguments": json.dumps({"message": "已为您触发所有关键元素的概念图生成，请查看出图进度。"})}},
    ])
    applied, confirmation, *_rest = asyncio.run(runner.execute(response))
    tool_results = _rest[4]
    assert "出图尚未执行" not in confirmation
    assert any(
        t.get("name") == "image_generate" and t.get("ok") is False
        for t in tool_results)


def test_honest_pause_kept_when_generation_failed(monkeypatch):
    """生成失败但模型文案诚实（不含生成声明）→ 不覆盖"""
    import asyncio
    runner = FCToolRunner(tool_manager=_GenFailToolManager())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "image_generate",
            "arguments": json.dumps({"target": "all_keyElements"})}},
        {"id": "c2", "type": "function", "function": {
            "name": "workflow_pause",
            "arguments": json.dumps({"message": "提示词草案已写好，请审阅确认。"})}},
    ])
    applied, confirmation, *_rest, _warns, _overflow, _pause_id = asyncio.run(runner.execute(response))
    # C1a 裁决后：诚实暂停不被没收，模型原文在确认/正文通道可见
    assert "提示词草案已写好，请审阅确认。" in (confirmation + _overflow)


# ---------- 新建草稿按规格偏好补印供应商（防前端默认回填污染） ----------

def test_fc_add_draft_stamps_spec_preference(svc, monkeypatch, set_global_setting):
    """FC 轨新增草稿：全局设置设定 Antigravity CLI → 草稿自动带上 gemini-cli/auto"""
    import asyncio
    from src.video_agent.tools.storyboard_tools import AddDraftInput, StoryboardAddDraftTool

    monkeypatch.setattr(StateManager, "_instance", svc)
    set_global_setting("default_image_provider_id", "gemini-cli")
    set_global_setting("default_image_model", "auto")
    svc.state_dict["documents"] = [
        {"name": "制片规格.md", "content": _SPEC_PREF_DOC}]
    svc.state_dict["keyElements"] = [{"id": "g1", "title": "G", "drafts": []}]
    r = asyncio.run(StoryboardAddDraftTool().aexecute(
        AddDraftInput(group_id="g1", group_type="keyElement", draft={"label": "概念图"})))
    assert r.success
    d = svc.state_dict["keyElements"][0]["drafts"][-1]
    assert d["providerId"] == "gemini-cli" and d["model"] == "auto"


# test_text_track_add_draft_stamps_spec_preference 已随 Q2 裁决 2026-09-01 退役删除：
# 文本轨 add_draft 随执行器家族退役；规格偏好补印语义由上方
# test_fc_add_draft_stamps_spec_preference（FC 轨）钉死。


# ---------- 确认晋升兜底（presented 记录缺失时按带提示词草稿晋升） ----------

def test_confirm_fallback_promotes_when_presented_missing(svc):
    """暂停态但 drafts_presented 为空：用户回应仍应晋升带提示词草稿，防生成闸死循环"""
    from src.video_agent.web.chat_service import _consume_pending_confirmation
    svc.state_dict["keyElements"] = [{
        "id": "g1", "title": "G",
        "drafts": [{"id": "d1", "tag": "Agent", "prompt": "提示词内容足够长。"}],
    }]
    inter = svc.state_dict.setdefault("interaction", {})
    inter["awaiting_confirmation"] = True
    inter["confirmation_message"] = "请审阅提示词草案"
    inter["drafts_presented"] = []
    _consume_pending_confirmation(svc, "确认")
    assert svc.state_dict["keyElements"][0]["drafts"][0]["tag"] == "已确认"


def test_confirm_fallback_not_triggered_without_pause(svc):
    """非暂停态不误晋升（日常聊天消息不视为确认）"""
    from src.video_agent.web.chat_service import _consume_pending_confirmation
    svc.state_dict["keyElements"] = [{
        "id": "g1", "title": "G",
        "drafts": [{"id": "d1", "tag": "Agent", "prompt": "提示词内容足够长。"}],
    }]
    svc.state_dict.setdefault("interaction", {})["awaiting_confirmation"] = False
    _consume_pending_confirmation(svc, "确认")
    assert svc.state_dict["keyElements"][0]["drafts"][0]["tag"] == "Agent"


# ---------- FC 轨 current 语义（审查修复：命中选中草稿 + 闸机不可绕过） ----------

def _fc_state_with_two_ke_groups():
    """两个关键元素分组，第二组 d2 为前端选中草稿
    （audit-0819e：analysis 前置就位，阶段前置闸放行结构内操作）"""
    return {
        "analysis": {"summary": "一句话总结"},
        "keyElements": [
            {"id": "ke-1", "title": "A", "drafts": [
                {"id": "d1", "label": "first", "tag": "Agent", "prompt": ""}]},
            {"id": "ke-2", "title": "B", "drafts": [
                {"id": "d2", "label": "selected", "tag": "Agent", "prompt": ""}]},
        ],
        "shots": [], "audioItems": [], "documents": [], "interaction": {},
    }


def test_fc_patch_current_rejects_bad_prompt(monkeypatch):
    """strict 下 patch \"current\" 经过提示词校验，不合格被拒绝（决策 D）"""
    import asyncio
    tm = _CaptureToolManager()
    runner = FCToolRunner(tool_manager=tm)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(_fc_state_with_two_ke_groups))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "storyboard_patch_draft",
            "arguments": json.dumps({"draft_id": "current", "patch": {"prompt": "x"}})}},
    ])
    applied, confirmation, *_rest, tool_results, _docs, _warnings, _overflow, _pause_id = asyncio.run(
        runner.execute(response, injected_skill="任意 Skill",
                       selected_draft_id="d2", selected_type="keyElement"))
    assert applied == 0
    assert not tm.captured  # 工具未执行
    assert tool_results and tool_results[0]["ok"] is False
    # 用户坚持 → 照常执行并警告
    runner2 = FCToolRunner(tool_manager=_CaptureToolManager())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(_fc_state_with_two_ke_groups))
    applied2, *_rest2 = asyncio.run(
        runner2.execute(response, injected_skill="任意 Skill",
                        selected_draft_id="d2", selected_type="keyElement",
                        gate_override=True))
    assert applied2 == 1
    assert runner2.gate_warnings and "警告" in runner2.gate_warnings[0]


def test_fc_patch_current_resolves_selected_draft(monkeypatch):
    """patch \"current\" 解析为前端选中草稿（而非第一张卡）"""
    import asyncio
    tm = _CaptureToolManager()
    runner = FCToolRunner(tool_manager=tm)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(_fc_state_with_two_ke_groups))
    valid_prompt = (
        "白发老者站在冥王星冰原上，手持拐杖，身披厚重宇航服，"
        "伦勃朗式冷白主光，坚毅沧桑的神情，背景是荒芜冰原与深邃星空，"
        "电影级新写实主义质感，人物面部细节丰富。"
    )
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "storyboard_patch_draft",
            "arguments": json.dumps({
                "draft_id": "current", "patch": {"prompt": valid_prompt}})}},
    ])
    applied, *_rest = asyncio.run(
        runner.execute(response, injected_skill="任意 Skill",
                       selected_draft_id="d2", selected_type="keyElement"))
    assert applied == 1
    assert tm.captured and tm.captured[0][0] == "storyboard_patch_draft"
    assert tm.captured[0][1]["draft_id"] == "d2"


def test_fc_add_draft_current_uses_selected_group(monkeypatch):
    """add_draft group_id=\"current\" 命中选中草稿所在分组"""
    import asyncio
    tm = _CaptureToolManager()
    runner = FCToolRunner(tool_manager=tm)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(_fc_state_with_two_ke_groups))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "storyboard_add_draft",
            "arguments": json.dumps({
                "group_id": "current", "group_type": "keyElement",
                "draft": {"label": "新草稿"}})}},
    ])
    applied, *_rest = asyncio.run(
        runner.execute(response, injected_skill="",
                       selected_draft_id="d2", selected_type="keyElement"))
    assert applied == 1
    assert tm.captured and tm.captured[0][0] == "storyboard_add_draft"
    assert tm.captured[0][1]["group_id"] == "ke-2"


def test_fc_media_to_chat_current_uses_selected_draft(monkeypatch):
    """media_to_chat target=\"current\" 解析为前端选中草稿"""
    import asyncio
    tm = _CaptureToolManager()
    runner = FCToolRunner(tool_manager=tm)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(_fc_state_with_two_ke_groups))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "storyboard_media_to_chat",
            "arguments": json.dumps({"target": "current"})}},
    ])
    applied, *_rest = asyncio.run(
        runner.execute(response, injected_skill="",
                       selected_draft_id="d2", selected_type="keyElement"))
    assert applied == 1
    assert tm.captured and tm.captured[0][0] == "storyboard_media_to_chat"
    args = tm.captured[0][1]
    assert args.get("draft_ids") == ["d2"]


# ---------- 幂等键轮内去重接线（T4） ----------

class _CountingToolManager:
    """每次调用返回带序号的结果，便于区分首次与重复调用的返回体"""

    def __init__(self):
        self.calls = 0

    async def invoke_tool(self, name, args):
        self.calls += 1
        return ToolResult(success=True, data={"seq": self.calls})


def _idem_add_draft_call(key: str, call_id: str):
    return {"id": call_id, "type": "function", "function": {
        "name": "storyboard_add_draft",
        "arguments": json.dumps({
            "group_id": "ke-2", "group_type": "keyElement",
            "draft": {"label": "新草稿"}, "idempotency_key": key})}}


def test_fc_idempotency_key_short_circuits_same_key(monkeypatch):
    """同批同键：第二次调用短路返回首次结果，真实执行只发生一次；
    异键/空键不受影响照常执行"""
    import asyncio
    tm = _CountingToolManager()
    runner = FCToolRunner(tool_manager=tm)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(_fc_state_with_two_ke_groups))
    response = ChatResponse(content="", tool_calls=[
        _idem_add_draft_call("idem-1", "c1"),
        _idem_add_draft_call("idem-1", "c2"),  # 同键重复提交
        _idem_add_draft_call("idem-2", "c3"),  # 异键照常执行
        _idem_add_draft_call("", "c4"),        # 空键直通过
    ])
    applied, *_rest, tool_results, _docs, _warnings, _overflow, _pause_id = asyncio.run(
        runner.execute(response, injected_skill=""))
    assert applied == 4
    assert tm.calls == 3  # 同键第二次被短路，未真实执行
    assert tool_results[0]["data"] == {"seq": 1}
    assert tool_results[1]["data"] == {"seq": 1}  # 命中返回首次结果
    assert tool_results[2]["data"] == {"seq": 2}
    assert tool_results[3]["data"] == {"seq": 3}


def test_fc_idempotency_key_reset_between_turns(monkeypatch):
    """跨轮：reset_turn_tracking 后同键不串，重新真实执行"""
    import asyncio
    tm = _CountingToolManager()
    runner = FCToolRunner(tool_manager=tm)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(_fc_state_with_two_ke_groups))
    response = ChatResponse(content="", tool_calls=[_idem_add_draft_call("idem-1", "c1")])
    asyncio.run(runner.execute(response, injected_skill=""))
    assert tm.calls == 1
    runner.reset_turn_tracking()  # 轮始重置（planner 每轮调用）
    out = asyncio.run(runner.execute(response, injected_skill=""))
    assert tm.calls == 2
    assert out.tool_results[0]["data"] == {"seq": 2}
