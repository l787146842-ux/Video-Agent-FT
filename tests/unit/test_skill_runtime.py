"""Skill 注册表 + 通用主路径运行时测试。

任务#36 B5：独立执行器族一步退役后，本文件只保留通用路径用例：
- registry 注册/注销/章节解析（阶段能力探针口径）；
- PromptBuilder 通用主路径全文直注语义（防虚报条款/流程可见）；
- action_executor 通用动作语义（标题兜底/徽标/草稿归组）。
执行器专属用例（execute_async 派发、LLM 拆解批次、提示词分批写入、
_apply_actions 护栏）已随退役删除；建组护栏由
tests/unit/test_structure_integrity_gate.py 在通用闸机链钉死。
"""
import re

import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.skill_runtime import registry
from src.video_agent.core.action_executor import StateOperationExecutor


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """每个测试独立 Skill 目录 + 清空运行时注册表。"""
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    registry.reset_registry()
    yield
    registry.reset_registry()


def _write(slug: str, content: str):
    # 批3：name/description 注册期必填；name 取正文 H1（与原显示名口径一致，
    # 避免声明头覆盖展示名导致按名解析失联），正文一字不动。
    m = re.search(r"(?m)^# (.+)$", content)
    name = m.group(1).strip() if m else slug
    sd.save_skill_doc(
        slug, f"---\nname: {name}\ndescription: 测试桩\n---\n" + content)


def test_save_registers_and_delete_unregisters():
    _write(
        "demo",
        "# 演示\n> 调用规则：测试\n"
        "<storyboard_key_elements>\n关键元素规范\n</storyboard_key_elements>\n"
        "<generation>\n生成规范\n</generation>\n",
    )
    entry = registry.get_entry("demo")
    assert entry is not None
    # 只有对应章节存在的管线能力才会登记（探针口径）
    assert entry.available_tools == ["storyboard_key_elements", "audio_generate"]
    assert "关键元素规范" in registry.tool_sections("demo", "storyboard_key_elements")
    assert registry.tool_sections("demo", "script_analyze") == ""

    sd.delete_skill_doc("demo")
    assert registry.get_entry("demo") is None
    assert not registry.tool_available("demo", "storyboard_key_elements")


def test_edit_re_registers():
    _write("demo2", "# 演示2\n> 调用规则：测试\n<script_analyze>\n分析\n</script_analyze>\n")
    assert "分析" in registry.tool_sections("demo2", "script_analyze")
    # 编辑后章节变化 → 重新注册
    _write("demo2", "# 演示2\n> 调用规则：测试\n<storyboard_shots>\n分镜\n</storyboard_shots>\n")
    assert registry.tool_sections("demo2", "script_analyze") == ""
    assert "分镜" in registry.tool_sections("demo2", "storyboard_shots")


def test_prompt_draft_section_merges_write_media_prompt_and_write_the_prompt():
    _write(
        "demo3",
        "# 演示3\n> 调用规则：测试\n"
        "<write_media_prompt>\n草案说明\n</write_media_prompt>\n"
        "<write_the_prompt>\n写法规范\n</write_the_prompt>\n",
    )
    sec = registry.tool_sections("demo3", "write_media_prompt")
    assert "草案说明" in sec
    assert "写法规范" in sec


def test_selected_block_lightweight_keeps_discipline_pointer():
    """回归（7777 事故）：防虚报语义随《Skill 流程纪律》全文到达模型——
    纪律全文经评审修复批（用户裁决）挂回选中 Skill 块；B1：
    Skill 正文只注入 <planner> 段，纪律单家仍是 skill_discipline.md。"""
    from src.video_agent.utils.prompts import load_prompt

    _write(
        "demo-fc",
        "# 演示防虚报\n> 调用规则：测试\n"
        "<planner>\nUNIQUE_BODY_MARK_FX\n</planner>\n",
    )
    pb = PromptBuilder(
        lambda: sd,
        lambda: "proj",
        lambda: {"keyElements": [], "shots": [], "audioItems": []},
    )
    block = pb.build_selected_skill_block("演示防虚报")
    # 防虚报条款（纪律第 9 条）随选中块挂回在场；planner 段探针经按需注入在场（B1）
    assert "必须真的调用" in block and "才可声称完成" in block
    assert "UNIQUE_BODY_MARK_FX" in block
    # 防虚报条款外置单家仍在场（宪法 Rule 6 单一事实源）
    discipline = load_prompt("planner/skill_discipline.md")
    assert "必须真的调用" in discipline and "才可声称完成" in discipline


# test_executor_runtime_block_lists_tools（执行器清单注入断言）已随任务#36 B5
# 执行器一步退役删除：执行器清单形态不再存在，通用主路径全文直注/分级注入
# 语义由 tests/unit/test_prompt_builder_modes.py 钉死。


def test_add_group_title_field_fallback(tmp_path):
    """回归（6666 事故）：模型用 name/element_id 等非 title 字段时不得静默落默认标题。"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    ex = StateOperationExecutor(svc, gate_enabled=False)
    applied = ex.execute([
        {"action": "add_group", "group_type": "keyElement", "name": "罗辑", "desc": "角色描述"},
        {"action": "add_group", "group_type": "keyElement", "element_id": "[Element_ChengXin]"},
        {"action": "add_group", "group_type": "shot", "title": "镜头一",
         "roughDesc": "场景：太空。旁白：二向箔漂浮。"},
    ])
    assert applied == 3
    kes = svc.state_dict["keyElements"]
    assert kes[-2]["title"] == "罗辑"
    assert kes[-1]["title"] == "[Element_ChengXin]"
    # 分镜只写 roughDesc 不写 desc 时自动同步，前端卡片不显示空白
    shot = svc.state_dict["shots"][-1]
    assert shot["desc"] == "场景：太空。旁白：二向箔漂浮。"


def test_add_group_title_alias_element_name(tmp_path):
    """8888 事故：标题兜底链扩展 element_name/group_title 等别名。"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    ex = StateOperationExecutor(svc, gate_enabled=False)
    applied = ex.execute([
        {"action": "add_group", "group_type": "keyElement", "element_name": "AA"},
        {"action": "add_group", "group_type": "keyElement", "group_title": "预警中心"},
    ])
    assert applied == 2
    titles = [g["title"] for g in svc.state_dict["keyElements"][-2:]]
    assert titles == ["AA", "预警中心"]


def test_add_draft_label_smart_matching(tmp_path):
    """回归（proj-1786169643 事故）：add_draft 未携带有效 group_id 时，
    按 label 名称匹配对应分组，不再盲捡第一个分组（曾导致 24 条提示词全进程心组）。"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "ke-1", "title": "[Element_Cheng_Xin] 程心", "desc": "", "drafts": []},
        {"id": "ke-2", "title": "[Element_Ai_AA] 艾AA", "desc": "", "drafts": []},
        {"id": "ke-3", "title": "[Element_Dual_Vector_Foil] 二向箔", "desc": "", "drafts": []},
    ]
    ex = StateOperationExecutor(svc, gate_enabled=False)
    applied = ex.execute([
        {"action": "add_draft", "group_id": "current",
         "draft": {"label": "艾AA - 角色概念图", "prompt": "艾AA的提示词", "mediaType": "image"}},
        {"action": "add_draft", "group_id": "current",
         "draft": {"label": "二向箔 - 道具概念图", "prompt": "二向箔的提示词", "mediaType": "image"}},
    ])
    assert applied == 2
    kes = {g["title"]: g for g in svc.state_dict["keyElements"]}
    # 各归其位：不再全堆进第一个分组（程心）
    assert len(kes["[Element_Cheng_Xin] 程心"]["drafts"]) == 0
    assert len(kes["[Element_Ai_AA] 艾AA"]["drafts"]) == 1
    assert len(kes["[Element_Dual_Vector_Foil] 二向箔"]["drafts"]) == 1


def test_selected_block_flow_body_budget_injection():
    """批4/ADR-0007：<planner> 流程正文经渐进披露预算注入（短桩预算内全文）；
    执行器「流程基线」专属段与全文硬注入形态仍保持退役。"""
    _write(
        "flow-skill",
        "# 流程\n> 调用规则：测试\n"
        "<planner>\n阶段逻辑：先 script_analyze → document_write → storyboard_key_elements\n</planner>\n"
        "<script_analyze>\n分析\n</script_analyze>\n"
        "<storyboard_key_elements>\n关键元素\n</storyboard_key_elements>\n",
    )
    pb = PromptBuilder(
        lambda: sd,
        lambda: "proj",
        lambda: {"keyElements": [], "shots": [], "audioItems": []},
    )
    block = pb.build_selected_skill_block("流程")
    # 正文头部预算注入：阶段逻辑在场；执行器形态专属段保持退役
    assert "阶段逻辑" in block
    assert "script_analyze" in block
    assert "== 当前 Skill 的流程基线" not in block  # 执行器形态专属段已退役


def test_add_group_badge_label_persisted_and_patchable(tmp_path):
    """898 需求：关键元素类别徽标（人物/场景/道具）可随 add_group 写入，
    且双击编辑（update_group patch badgeLabel）能持久化（曾在白名单外被静默丢弃）。"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    ex = StateOperationExecutor(svc, gate_enabled=False)
    applied = ex.execute([
        {"action": "add_group", "group_type": "keyElement",
         "title": "程心", "desc": "前执剑人", "badgeLabel": "人物"},
        {"action": "add_group", "group_type": "keyElement", "title": "二向箔"},
    ])
    assert applied == 2
    kes = {g["title"]: g for g in svc.state_dict["keyElements"]}
    assert kes["程心"].get("badgeLabel") == "人物"
    assert "badgeLabel" not in kes["二向箔"]
    # 双击徽标编辑（update_group）必须能改写并持久化
    applied = ex.execute([
        {"action": "update_group", "group_id": kes["二向箔"]["id"],
         "group_type": "keyElement", "patch": {"badgeLabel": "道具"}},
    ])
    assert applied == 1
    assert kes["二向箔"]["badgeLabel"] == "道具"


def test_add_draft_accepts_patch_field_fallback(tmp_path):
    """898 事故回归：模型把建卡字段放进 patch/fields 而非 draft 时，
    不得静默落成空默认草稿，提示词必须写入。"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "ke-1", "title": "罗辑", "desc": "", "drafts": []},
    ]
    ex = StateOperationExecutor(svc, gate_enabled=False)
    applied = ex.execute([
        {"action": "add_draft", "group_id": "ke-1",
         "patch": {"label": "概念图", "prompt": "罗辑的概念图提示词", "mediaType": "image"}},
    ])
    assert applied == 1
    draft = svc.state_dict["keyElements"][0]["drafts"][0]
    assert draft["prompt"] == "罗辑的概念图提示词"
    assert draft["label"] == "概念图"


def test_feedback_carries_tool_detail():
    """3333 事故回归：script_analyze 的一句话总结随回喂传给模型，不再只报「执行成功」。"""
    from src.video_agent.core.fc_tool_runner import format_tool_results

    feedback = format_tool_results([{
        "name": "script_analyze", "ok": True,
        "data": {"summary": "太阳系被二维化的一曲悲歌",
                 "detail": "已分析《剧本.md》。一句话总结：太阳系被二维化的一曲悲歌 （必须展示）"},
    }])
    assert isinstance(feedback, str)
    assert "太阳系被二维化的一曲悲歌" in feedback
    assert "必须展示" in feedback
