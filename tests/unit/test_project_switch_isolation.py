# -*- coding: utf-8 -*-
"""8888 二轮回归：切换项目旧状态覆盖 + 流程体验带修复。

8888 项目现场：任务级隔离后全局单例在任务期间不刷新，switch_project 的
「保存当前」用单例过期空壳回写文件，抹掉后台任务写好的数据（12:19:21 实证）。
"""
from src.video_agent.state.manager import StateManager


def _fresh(ws: str, project_id: str) -> StateManager:
    """全新实例加载指定项目（模拟重连/核对落盘内容）。"""
    svc = StateManager(ws)
    if svc.active_project_id != project_id:
        svc.switch_project(project_id)
    return svc


# ---------- A3：切换/保存不得回退后台任务的新写入 ----------

def test_switch_does_not_regress_task_writes(tmp_path):
    """钉死 8888 现场：任务实例写新后，单例来回切换不得抹掉文件；
    单例持过期内存直接 save() 也必须被版本闸放弃。"""
    ws = str(tmp_path / "ws")
    singleton = StateManager(ws)
    p8888 = singleton.create_project("8888")
    p1111 = singleton.create_project("1111")  # 单例停在 1111（空壳），与现场一致

    # 后台任务实例（contextvar 隔离的同构模拟）：写关键元素并落盘
    task = StateManager(ws)
    task.switch_project(p8888)
    task.state_dict["keyElements"] = [{"id": "ke-1", "title": "程心", "drafts": []}]
    task.save()

    # 用户来回切换：不得再出现「空壳回写抹数据」
    singleton.switch_project(p8888)
    assert singleton.state_dict["keyElements"], "切换应加载任务写好的完整数据"
    singleton.switch_project(p1111)
    singleton.switch_project(p8888)
    assert singleton.state_dict["keyElements"]

    # 任务又写新（分镜），单例内存过期（无分镜）直接 save() → 版本闸放弃
    task.state_dict["shots"] = [{"id": "s-1", "title": "镜头1", "drafts": []}]
    task.save()
    singleton.state_dict["shots"] = []  # 模拟单例的过期视图
    singleton.save()  # 必须被放弃，不得回退文件

    fresh = _fresh(ws, p8888)
    assert fresh.state_dict["keyElements"]
    assert fresh.state_dict["shots"], "过期实例的保存必须被版本闸放弃"


def test_parallel_projects_no_cross_write(tmp_path):
    """双项目并行：各自实例各自落盘，互不串写。"""
    ws = str(tmp_path / "ws")
    a = StateManager(ws)
    pa = a.create_project("A")
    b = StateManager(ws)
    pb = b.create_project("B")
    if a.active_project_id != pa:
        a.switch_project(pa)

    a.state_dict["keyElements"] = [{"id": "ke-a", "title": "元素A", "drafts": []}]
    a.save()
    b.state_dict["keyElements"] = [{"id": "ke-b", "title": "元素B", "drafts": []}]
    b.save()

    fa = _fresh(ws, pa)
    fb = _fresh(ws, pb)
    assert [g["title"] for g in fa.state_dict["keyElements"]] == ["元素A"]
    assert [g["title"] for g in fb.state_dict["keyElements"]] == ["元素B"]


def test_normal_single_instance_save_still_works(tmp_path):
    """版本闸不得误伤正常单实例读写链：连续 update/save 均落盘。"""
    ws = str(tmp_path / "ws")
    svc = StateManager(ws)
    pid = svc.create_project("常规")
    svc.state_dict["keyElements"] = [{"id": "ke-1", "title": "程心", "drafts": []}]
    svc.save()
    svc.state_dict["keyElements"][0]["title"] = "AA"
    svc.save()
    fresh = _fresh(ws, pid)
    assert fresh.state_dict["keyElements"][0]["title"] == "AA"


# ---------- B：流程体验带 ----------

_SPEC_FULL = (
    "- **画幅比例**：16:9\n- **目标时长**：约 2 分钟\n"
    "- **影像风格基调**：冷峻写实\n- **输出语言**：中文普通话\n"
)


def test_takeover_skipped_when_spec_finalized(monkeypatch):
    """B1 钉死现场：规格已定稿时模型冗余手写规格 → 只拒收警告，
    不接管暂停卡（拆解阶段不再被换回「确认规格」卡）。"""
    import asyncio
    import json

    from src.video_agent.core import prompt_gates
    from src.video_agent.core.fc_tool_runner import FCToolRunner
    from src.video_agent.adapters.base_chat import ChatResponse
    from src.video_agent.tools.base import ToolResult

    raw_state = {
        "usedSkills": ["AI-短剧一站式生成"],
        "documents": [{"name": "Final_Video_Spec.md", "content": _SPEC_FULL}],
        "interaction": {},
    }

    class _TM:
        async def invoke_tool(self, name, args):
            if name == "document_write":
                return ToolResult(success=False, error="规格已按您的选择生成，无需重复写入")
            return ToolResult(success=True, data={})

    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: raw_state))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "storyboard_key_elements", "arguments": "{}"}},
        {"id": "c2", "type": "function", "function": {
            "name": "document_write",
            "arguments": json.dumps({"name": "Final_Video_Spec.md", "content": "x"})}},
        {"id": "c3", "type": "function", "function": {
            "name": "workflow_pause",
            "arguments": json.dumps({"message": "关键元素拆解完成，请审阅"})}},
    ])
    _res = asyncio.run(
        runner.execute(response, injected_skill="AI-短剧一站式生成",
                       # 桩无注册信息 → 确认闸默认拦；本用例聚焦暂停卡接管
                       # 语义，经「本次放行」等价通道显式同意放行（闸不放松）
                       gate_override="all"))
    confirmation, overflow = _res[1], _res[9]
    # v2 批4：卡问句系统组装、模型原文进正文通道；且不被规格卡接管
    assert "请过目以上成果" in confirmation
    assert overflow == "关键元素拆解完成，请审阅"
    assert raw_state["interaction"].get("pending_pause_kind") != "spec"


# test_review_options_concrete_next_step / test_collect_card_neutral_no_summary_injection /
# test_output_language_dim_description 已随用户裁决 2026-08-31 退役删除（D-08 清偿）：
# 规格审阅/收集向导卡链整体退役。

# test_duration_candidates_dedup_by_value（executors._dedupe_duration_candidates）
# 已随任务#36 B5 执行器一步退役删除：时长候选去重是执行器规格收集
# 内部逻辑，规格收集改由模型按 skill_runtime 用 workflow_pause 分组向导完成。


# test_badge_normalize_from_desc_anchors 已随用户裁决 2026-09-17 退役删除：
# badgeLabel 类别标识全链删除（建组推导/patch 写口/前端显示编辑均退役），
# 存量数据只读透传（extra="allow" 往返断言见 test_project_state_roundtrip）。
