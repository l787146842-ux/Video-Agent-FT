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
    # 2026-10-01 媒体生成支（步骤3）：原 audio_generate 在此位；能力词收敛为
    # media_generate（其章节 = generation + prompt_draft），旧名降为兼容别名。
    # 顺序 = PIPELINE_CAPABILITY_TOOLS 声明序（media_generate 在 audio_generate 前）。
    # 两者都能由 `<generation>` 章支撑：media_generate 取二章（本桩只有其一），
    # audio_generate 仍作能力词映射 generation（喂 lint/音频闸/stage_probes）。
    assert entry.available_tools == [
        "storyboard_key_elements", "media_generate", "audio_generate"]
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
    Skill 正文只注入 <planner> 段，纪律单家仍是 skill_runtime.md。"""
    from src.video_agent.utils.prompts import load_prompt_section

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
    discipline = load_prompt_section("planner/skill_runtime.md", "DISCIPLINE")
    assert "必须真的调用" in discipline and "才可声称完成" in discipline


# test_executor_runtime_block_lists_tools（执行器清单注入断言）已随任务#36 B5
# 执行器一步退役删除：执行器清单形态不再存在，通用主路径全文直注/分级注入
# 语义由 tests/unit/test_prompt_builder_modes.py 钉死。


# test_add_group_title_field_fallback / test_add_group_title_alias_element_name /
# test_add_draft_label_smart_matching 已随 Q2 裁决 2026-09-01 退役删除：
# 文本轨 add_group/add_draft 的字段别名兜底与 label 智能匹配随执行器家族退役；
# FC 轨工具输入经 pydantic 严格校验，错误结构化回喂模型纠正（弱模型容错不再靠猜）。


def test_selected_block_flow_body_budget_injection():
    """指令性制作手册口径（决策史见 git tag adr-archive-20260901）：<planner> 流程正文经渐进披露预算注入（短桩预算内全文）；
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


# test_add_group_badge_label_persisted_and_patchable 已随 Q2 裁决 2026-09-01 退役删除：
# 文本轨 add_group/update_group 的 badgeLabel 口径随执行器家族退役；
# badgeLabel 全链（含 FC 轨建组推导与前端显示编辑）随用户裁决 2026-09-17 退役。


# test_add_draft_accepts_patch_field_fallback 已随 Q2 裁决 2026-09-01 退役删除：
# 文本轨 add_draft 的 patch/fields 宽容兜底随执行器家族退役；
# FC 轨 storyboard_add_draft 输入经 pydantic 严格校验，错误回喂纠正。


def test_feedback_carries_tool_detail():
    """3333 事故回归：script_analyze 的一句话总结随回喂传给模型，不再只报「执行成功」。"""
    from src.video_agent.core.fc_feedback import format_tool_results

    feedback = format_tool_results([{
        "name": "script_analyze", "ok": True,
        "data": {"summary": "太阳系被二维化的一曲悲歌",
                 "detail": "已分析《剧本.md》。一句话总结：太阳系被二维化的一曲悲歌 （必须展示）"},
    }])
    assert isinstance(feedback, str)
    assert "太阳系被二维化的一曲悲歌" in feedback
    assert "必须展示" in feedback
