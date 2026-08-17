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

def test_8888_switch_does_not_regress_task_writes(tmp_path):
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


def test_8888_parallel_projects_no_cross_write(tmp_path):
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


def test_8888_normal_single_instance_save_still_works(tmp_path):
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


def test_8888_takeover_skipped_when_spec_finalized(monkeypatch):
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
    _applied, confirmation, *_rest = asyncio.run(
        runner.execute(response, injected_skill="AI-短剧一站式生成"))
    # 模型暂停文案保留，不被规格卡接管
    assert confirmation == "关键元素拆解完成，请审阅"
    assert raw_state["interaction"].get("pending_pause_kind") != "spec"


def test_8888_review_options_concrete_next_step():
    """0817 B22：审阅卡选项中性化——平台不点名下一步，一律按 Skill 流程推进。"""
    from src.video_agent.core import prompt_gates

    opts = prompt_gates.spec_review_options({})
    assert "开始拆解" not in opts[0]["label"]
    assert "按流程继续" in opts[0]["label"] or "Skill 流程" in opts[0]["label"]
    opts = prompt_gates.spec_review_options({"keyElements": [{"id": "k"}]})
    assert "开始拆解" not in opts[0]["label"]
    opts = prompt_gates.spec_review_options({"keyElements": [{"id": "k"}], "shots": [{"id": "s"}]})
    assert opts[0]["label"] == "确认成片规格，按流程继续"


def test_8888_collect_card_embeds_summary_and_no_dev_talk(monkeypatch):
    """B4：声明总结展示的 Skill 收集卡内嵌总结、无「见上」/「按 Skill 声明」/全局设置解释句。
    0817 B20：内嵌总结归 Skill 声明驱动，此处模拟已声明。"""
    from src.video_agent.core import prompt_gates
    monkeypatch.setattr(prompt_gates, "skill_declares_summary", lambda name: True)

    state = {"analysis": {"summary": "人类在太阳系边缘拦截到神秘薄片"}}
    msg, _opts = prompt_gates.spec_collect_card(state)
    assert "一句话故事总结：人类在太阳系边缘拦截到神秘薄片" in msg
    assert "见上" not in msg
    assert "Skill 声明" not in msg
    assert "全局设置" not in msg


def test_8888_duration_candidates_dedup_by_value():
    """B5：「约 2 分钟」与「约 120 秒」同档去重，表述归一。"""
    from src.video_agent.skill_runtime import executors as ex_mod

    out = ex_mod._dedupe_duration_candidates(["约 2 分钟", "约 120 秒", "约 90 秒"])
    assert out == ["约 2 分钟", "约 1.5 分钟"]
    out = ex_mod._dedupe_duration_candidates(["约 45 秒", "约 45 秒"])
    assert out == ["约 45 秒"]


def test_8888_output_language_dim_description(monkeypatch):
    """B6/814G4：维度选项卡片文字不重复维度名（display），说明逐项差异化白话。"""
    from src.video_agent.core import prompt_gates

    monkeypatch.setattr(
        prompt_gates, "skill_spec_dimensions", lambda skill: ["输出语言"],
    )
    state = {"interaction": {"spec_soft_candidates": {"输出语言": ["中文普通话", "中英双语"]}}}
    _msg, opts = prompt_gates.build_spec_param_options("", state)
    assert opts
    assert all(o["display"] in ("中文普通话", "中英双语") for o in opts)
    assert all("若选此项，成片将按「" in o["description"] for o in opts)
    # label 保留「键：值」回传格式（chat_service 机械解析）
    assert all(o["label"].startswith("输出语言：") for o in opts)


def test_8888_badge_normalize_from_desc_anchors():
    """B7：泛化「关键元素」/缺省角标按 desc 锚点确定映射。"""
    from src.video_agent.state import storyboard_ops as ops

    assert ops.normalize_badge_label("关键元素", "关键道具（prop element）。一艘小型无人太空探测器") == "道具"
    assert ops.normalize_badge_label("", "关键场景（element scene）。空间结构：无垠开放深空") == "场景"
    assert ops.normalize_badge_label("关键元素", "青年女性，约20-30岁。外貌：清秀") == "人物"
    assert ops.normalize_badge_label("", "音色：温柔但坚定", group_type="audio") == "声音特征"
    # 已有具体角标不覆盖
    assert ops.normalize_badge_label("人物", "任意描述") == "人物"
