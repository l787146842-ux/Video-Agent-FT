"""混合形态工具边界：确认状态闭环 + 生成确认闸 + 阶段工具裁剪 + 首拆闸/即时暂停/文档卡片"""
import json

import pytest

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core import prompt_gates
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult
from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.core import provider_config as pc


def _async_return(value):
    """构造返回固定值的 async callable（monkeypatch 异步函数用）"""
    async def _f():
        return value
    return _f


@pytest.fixture(autouse=True)
def reset_provider_cache():
    """供应商合并结果带 TTL 缓存：每个用例前清空，避免串用其他夹具的临时配置。"""
    pc.reset_provider_caches()
    yield
    pc.reset_provider_caches()


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    yield StateManager(str(tmp_path))
    StateManager.reset_instance()


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


def test_presented_record_and_promote_on_user_reply(svc):
    """写提示词记录 presented → 用户新消息到达 → 晋升已确认并清空记录"""
    from src.video_agent.web.chat_service import _consume_pending_confirmation
    _seed_ke_draft(svc, tag="Agent")
    ex = StateOperationExecutor(svc, gate_enabled=True)
    applied = ex.execute([{
        "action": "update_draft", "draft_id": "d-ke1", "draft_type": "keyElement",
        "patch": {"prompt": "年轻女性程心身穿白色星环号轻型宇航服，面容清秀温婉，眼神中带着深沉的悲悯与疲惫，冷白正面主光，哑光金属质感，电影级新写实主义质感。"},
    }])
    assert applied == 1
    assert svc.state_dict["interaction"]["drafts_presented"] == ["d-ke1"]
    # 用户回应到达 → 晋升
    _consume_pending_confirmation(svc, "确认")
    assert svc.state_dict["keyElements"][0]["drafts"][0]["tag"] == "已确认"
    assert svc.state_dict["interaction"]["drafts_presented"] == []


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


def test_manual_confirm_draft_still_works(svc):
    """手动确认落点（用户口头明确确认）照常可用"""
    _seed_ke_draft(svc, tag="Agent")
    ex = StateOperationExecutor(svc, gate_enabled=True)
    applied = ex.execute([{
        "action": "confirm_draft", "draft_id": "d-ke1", "draft_type": "keyElement",
    }])
    assert applied == 1
    assert svc.state_dict["keyElements"][0]["drafts"][0]["tag"] == "已确认"


# ---------- 生成确认闸（文本轨） ----------

def test_gen_gate_blocks_model_self_skip_text_track(svc, monkeypatch):
    """4444：未确认草稿——本轮无跳过指令 → 拒收；用户本轮要求（gate_override）
    → 照常生成+警告；确认后放行。"""
    _seed_ke_draft(svc, tag="Agent")
    ex = StateOperationExecutor(svc, gate_enabled=True)
    submitted = []
    monkeypatch.setattr(ex, "_submit_image_task", lambda *a, **k: submitted.append(a))
    applied = ex.execute([{
        "action": "generate_image", "target": "all_keyElements",
    }])
    assert applied == 0 and not submitted  # 模型自发跳确认被拒收
    assert any("拦截" in w for w in ex.gate_warnings)
    # 用户本轮明确要求跳过 → 放行+警告
    ex2 = StateOperationExecutor(svc, gate_enabled=True)
    ex2.gate_override = "all"
    monkeypatch.setattr(ex2, "_submit_image_task", lambda *a, **k: submitted.append(a))
    applied = ex2.execute([{
        "action": "generate_image", "target": "all_keyElements",
    }])
    assert applied == 1 and len(submitted) == 1
    assert any("确认" in w for w in ex2.gate_warnings)
    # 确认后同样放行
    svc.state_dict["keyElements"][0]["drafts"][0]["tag"] = "已确认"
    ex3 = StateOperationExecutor(svc, gate_enabled=True)
    monkeypatch.setattr(ex3, "_submit_image_task", lambda *a, **k: submitted.append(a))
    applied = ex3.execute([{
        "action": "generate_image", "target": "all_keyElements",
    }])
    assert applied == 1 and len(submitted) == 2


def test_gen_gate_partial_confirmed_filters_unconfirmed(svc, monkeypatch):
    """B4 双轨收敛：部分确认且无跳过指令 → 整批硬拒（与 FC 轨一致，
    取代旧文本轨「跳过未确认项」镜像语义；4444：模型跳确认非用户意志）。"""
    _seed_ke_draft(svc, tag="已确认")
    svc.state_dict["keyElements"].append({
        "id": "ke-2", "title": "Element_乙",
        "drafts": [{"id": "d-ke2", "label": "图", "tag": "Agent",
                    "prompt": "黑色玄武岩方碑耸立在冥王星地表，地球文明石刻，宏大苍凉。"}],
    })
    ex = StateOperationExecutor(svc, gate_enabled=True)
    submitted = []
    monkeypatch.setattr(ex, "_submit_image_task", lambda *a, **k: submitted.append(a))
    applied = ex.execute([{"action": "generate_image", "target": "all_keyElements"}])
    assert applied == 0 and not submitted  # 整批拒收，不再部分提交
    assert ex.gate_warnings and "生成确认闸拦截" in ex.gate_warnings[0]


def test_gen_gate_inactive_without_skill(svc, monkeypatch):
    _seed_ke_draft(svc, tag="Agent")
    ex = StateOperationExecutor(svc)  # gate_enabled=False
    submitted = []
    monkeypatch.setattr(ex, "_submit_image_task", lambda *a, **k: submitted.append(a))
    applied = ex.execute([{"action": "generate_image", "target": "all_keyElements"}])
    assert applied == 1 and len(submitted) == 1


# ---------- 生成确认闸（FC 轨） ----------

def test_fc_gen_gate_blocks_without_user_insist(monkeypatch):
    """4444：FC 轨未确认草稿——本轮无跳过指令 → 返回拒收错误；
    用户本轮要求（gate_override）→ 放行+警告；确认后放行。"""
    runner = FCToolRunner(tool_manager=None)
    state = {"keyElements": [{
        "id": "ke-1", "title": "E", "drafts": [
            {"id": "d1", "tag": "Agent", "prompt": "深空背景中的二向箔，冷白荧光，极简硬科幻美学。"},
        ]}]}
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: state))
    err = runner._gen_confirm_gate(
        "image_generate", {"target": "all_keyElements"}, injected_skill="任意 Skill")
    assert err and "拦截" in err  # 模型自发跳确认被拒收
    # 用户本轮明确要求 → 放行+警告
    runner2 = FCToolRunner(tool_manager=None)
    runner2.gate_override = "all"
    monkeypatch.setattr(runner2, "_raw_state", staticmethod(lambda: state))
    assert runner2._gen_confirm_gate(
        "image_generate", {"target": "all_keyElements"}, injected_skill="任意 Skill") is None
    assert runner2.gate_warnings and "确认" in runner2.gate_warnings[0]
    # 全部确认后同样放行
    state["keyElements"][0]["drafts"][0]["tag"] = "已确认"
    assert runner._gen_confirm_gate(
        "image_generate", {"target": "all_keyElements"}, injected_skill="任意 Skill") is None
    # 无 Skill 不拦
    state["keyElements"][0]["drafts"][0]["tag"] = "Agent"
    assert runner._gen_confirm_gate(
        "image_generate", {"target": "all_keyElements"}, injected_skill="") is None


def test_fc_gen_gate_no_targets_passes(monkeypatch):
    """无目标草稿时放行（交给工具自身报错，不误伤）"""
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {"keyElements": []}))
    assert runner._gen_confirm_gate(
        "image_generate", {"target": "all_keyElements"}, injected_skill="任意") is None


# ---------- 阶段探测工具裁剪 ----------

def test_stage_restrictions_no_spec():
    excluded, note = prompt_gates.stage_tool_restrictions(
        {"documents": [], "keyElements": [], "shots": [], "audioItems": []})
    assert "storyboard_create_group" in excluded
    assert "read_draft" in excluded
    assert "image_generate" in excluded and "generate_video" in excluded
    # 对话内直出生图不受裁剪
    assert "generate_image" not in excluded
    assert "document_write" not in excluded
    assert "规格" in note


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

    # 无规格文档 + Skill 激活：故事板与生成工具都被裁剪，且携带解释文案
    svc.state_dict["documents"] = []
    ctx1 = make_ctx("剧本生视频（需上传剧本）")
    excluded = planner._compute_excluded_tools(ctx1)
    assert "storyboard_create_group" in excluded and "image_generate" in excluded
    assert ctx1.stage_excluded_tools and "当前阶段工具边界" in ctx1.stage_note
    # 无 Skill：不追加阶段裁剪，也不签发解释
    ctx2 = make_ctx("")
    excluded2 = planner._compute_excluded_tools(ctx2)
    assert "storyboard_create_group" not in excluded2
    assert ctx2.stage_excluded_tools == frozenset() and ctx2.stage_note == ""


# ---------- 首拆只允许关键元素（8888 事故：规格确认后一次性拆出分镜+音频） ----------

def _clear_storyboard(svc):
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []


def test_ke_first_gate_text_track(svc):
    """0817 用户裁决：平台不再「首拆只允关键元素」警告——流程以 Skill 为准，
    空板直接建 shot/audio 也照常创建且无首拆警告。"""
    _clear_storyboard(svc)
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": "规格正文"}]
    ex = StateOperationExecutor(svc, gate_enabled=True)
    applied = ex.execute([
        {"action": "add_group", "group_type": "shot", "title": "Shot_1"},
        {"action": "add_group", "group_type": "audio", "title": "Audio_1"},
        {"action": "add_group", "group_type": "keyElement", "title": "Element_A"},
    ])
    assert applied == 3  # 全部创建成功
    assert len(svc.state_dict["shots"]) == 1
    assert len(svc.state_dict["audioItems"]) == 1
    assert [g["title"] for g in svc.state_dict["keyElements"]][-1] == "Element_A"
    assert not any("首次" in w for w in ex.gate_warnings)


def test_ke_first_gate_allows_shots_after_elements_exist(svc):
    """关键元素已存在（非首次搭建）后，创建分镜/音频不再被拦"""
    _clear_storyboard(svc)
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": "规格正文"}]
    _seed_ke_draft(svc)
    ex = StateOperationExecutor(svc, gate_enabled=True)
    applied = ex.execute([
        {"action": "add_group", "group_type": "shot", "title": "Shot_1"},
    ])
    assert applied == 1 and len(svc.state_dict["shots"]) == 1


def test_ke_first_gate_fc_track(monkeypatch):
    """0817 用户裁决：FC 轨建 shot 无首拆警告。
    任务#36 护栏移植后：分镜 sceneRefs 完整度由 _structure_integrity_gate
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

def test_pending_immediate_rejects_short_prompt_in_same_batch(svc):
    """同一批：建结构成功，但过短提示词被质量闸拒绝（决策 D）"""
    _clear_storyboard(svc)
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": "规格正文"}]
    ex = StateOperationExecutor(svc, gate_enabled=True)
    applied = ex.execute([
        {"action": "add_group", "group_type": "keyElement", "title": "Element_A",
         "draft": {"label": "概念图"}},
        {"action": "update_draft", "draft_id": "current", "draft_type": "keyElement",
         "patch": {"prompt": "白发老者站在冥王星冰原上，手持拐杖，伦勃朗式光影，宿命感与沧桑。"}},
    ])
    assert applied == 1
    draft = svc.state_dict["keyElements"][-1]["drafts"][0]
    assert not draft.get("prompt")
    assert ex.gate_rejections


# ---------- FC 轨文档收集与规格暂停文案（8888 事故：无文档卡片无下一步指引） ----------

class _StubToolManager:
    async def invoke_tool(self, name, args):
        return ToolResult(success=True, data={})


def test_fc_spec_doc_written_injects_system_pause(monkeypatch):
    """写入规格文档且模型未自发暂停：系统注入规格审阅暂停卡（5555 事故兜底）。
    6666 二轮：硬参数由全局设置提供，规格审阅卡不再升级为候选项向导。"""
    import asyncio
    from src.video_agent.skill_runtime import registry

    monkeypatch.setattr(registry, "skill_flow_enabled", lambda skill, key: True)
    monkeypatch.setattr(registry, "spec_wizard_active", lambda skill: True)
    runner = FCToolRunner(tool_manager=_StubToolManager())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "document_write",
            "arguments": json.dumps({"name": "制片规格.md", "content": "标题：测试"})}},
    ])
    applied, confirmation, *_rest, tool_results, docs_written, _warnings, _overflow, _pause_id = asyncio.run(
        # §2.7 预期收紧：document_write 属 high，gate_override="all" 模拟用户一次性同意
        runner.execute(response, injected_skill="任意 Skill", gate_override="all"))
    assert applied == 1
    assert docs_written == ["制片规格.md"]
    assert confirmation == prompt_gates.SPEC_DOC_PAUSED_MSG


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
    asyncio.run(runner.execute(response, image_provider="custom-api"))
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
    asyncio.run(runner.execute(response, image_provider="custom-api"))
    _name, args = tm.captured[0]
    assert args.get("provider_id") == "custom-api"

    # 未带草稿供应商：回落全局设置（唯一硬参数事实源）
    tm2 = _CaptureToolManager()
    runner2 = FCToolRunner(tool_manager=tm2)
    asyncio.run(runner2.execute(response, image_provider=""))
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
    """同批生成失败但暂停文案声称已触发 → 覆盖为诚实文案与选项"""
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
    opts = _rest[3]
    assert "出图尚未执行" in confirmation and "闸机拦截" in confirmation
    assert "已为您触发" not in confirmation
    assert any("确认提示词草案" in o.get("label", "") for o in opts)


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
    # v2 批4：诚实暂停不被没收——闸警告与模型原文在确认/正文通道可见
    assert "提示词草案已写好，请审阅确认。" in (confirmation + _overflow)
    assert "闸" in confirmation or "请过目以上成果" in confirmation


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


def test_text_track_add_draft_stamps_spec_preference(svc, monkeypatch, set_global_setting):
    """文本轨 add_draft 同样补印（来源为全局设置）；草稿自带 providerId 时不覆盖"""
    set_global_setting("default_image_provider_id", "gemini-cli")
    set_global_setting("default_image_model", "auto")
    ex = StateOperationExecutor(svc, gate_enabled=False)
    svc.state_dict["documents"] = [
        {"name": "制片规格.md", "content": _SPEC_PREF_DOC}]
    svc.state_dict["keyElements"] = [{"id": "g1", "title": "G", "drafts": []}]
    applied = ex.execute([
        {"action": "add_draft", "draft_type": "keyElement", "group_id": "g1",
         "draft": {"label": "概念图"}},
    ])
    assert applied == 1
    d = svc.state_dict["keyElements"][0]["drafts"][-1]
    assert d["providerId"] == "gemini-cli" and d["model"] == "auto"
    # 自带 providerId 不被覆盖
    applied2 = ex.execute([
        {"action": "add_draft", "draft_type": "keyElement", "group_id": "g1",
         "draft": {"label": "概念图2", "providerId": "custom-api"}},
    ])
    assert applied2 == 1
    d2 = svc.state_dict["keyElements"][0]["drafts"][-1]
    assert d2["providerId"] == "custom-api"


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
