# -*- coding: utf-8 -*-
"""P3-15 Skill 表达力破单一模板：custom_sections 自定义章节通道。

钉死四件事：
① manifest_schema 校验——未声明合法、非法声明 fail-closed；
② registry 注册——声明+章节可解析 → skill_section_run 进 available_tools；
③ 回落——未声明/解析不到/非法声明者维持现行为（不产生半死通道）；
④ 接线——执行器退役后含自定义章节的短 Skill 走通用主路径全文直注，
   章节原文随全文进 prompt（不再有执行器清单/章节标识单独下发形态）。
"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.skill_runtime import frontmatter
from src.video_agent.skill_runtime import manifest_schema
from src.video_agent.skill_runtime import registry


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """每个测试独立 Skill 目录 + 清空运行时注册表（frontmatter 随文档同根）。"""
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    registry.reset_registry()
    yield
    registry.reset_registry()


def _write(slug: str, content: str):
    sd.save_skill_doc(slug, content)


# 仅含自定义 tag 章节的文档（固定 7 章节词汇表全部落空）
_DOC_CUSTOM = (
    "# 访谈音色\n> 调用规则：测试\n"
    "<tone_design>\n为每位发言者设计音色档案。\n</tone_design>\n"
)


# ---------- ① schema 校验：未声明合法 / 非法 fail-closed ----------


def test_schema_custom_sections_valid_and_undeclared():
    assert manifest_schema.validate_manifest_data(
        {"custom_sections": {"音色设计": "skill_section_run"}}) == []
    assert manifest_schema.validate_manifest_data({}) == []
    assert manifest_schema.validate_manifest_data(None) == []


def test_schema_custom_sections_fail_closed():
    def _issues(manifest):
        return [i for i in manifest_schema.validate_manifest_data(manifest)
                if "custom_sections" in i]

    # 非对象
    assert _issues({"custom_sections": ["音色设计"]})
    # 空键
    assert _issues({"custom_sections": {"": "skill_section_run"}})
    # 白名单外执行器（含复用工具名/专属执行器名：通道单一）
    assert _issues({"custom_sections": {"音色设计": "script_analyze"}})
    assert _issues({"custom_sections": {"音色设计": 123}})


# ---------- ② 注册：声明 + 章节可解析 → 通用执行器可用 ----------


def test_custom_sections_registers_generic_executor():
    _write("interview", _DOC_CUSTOM)
    frontmatter.write_manifest(
        "interview", {"custom_sections": {"tone_design": "skill_section_run"}})
    entry = registry.get_entry("interview")
    assert entry is not None
    # 固定 7 章节全落空，仅自定义通道成立
    assert entry.available_tools == ["skill_section_run"]
    assert "音色档案" in registry.tool_sections("interview", "skill_section_run")
    assert registry.tool_available("interview", "skill_section_run")
    # trace 大阶段标签登记（前端卡片不退化）
    assert registry.stage_label_for_tool("skill_section_run") == "自定义章节执行"


def test_custom_sections_coexist_with_fixed_tools():
    content = (
        "# 混合\n> 调用规则：测试\n"
        "<planner>\n流程章节\n</planner>\n"
        "<my_tag>\n自定义章节\n</my_tag>\n"
    )
    _write("mix", content)
    frontmatter.write_manifest(
        "mix", {"custom_sections": {"my_tag": "skill_section_run",
                                    "planning": "skill_section_run"}})
    entry = registry.get_entry("mix")
    # stage 键解析链同源：planning 走 sections，my_tag 走任意 <tag>
    assert entry.available_tools == ["script_analyze", "skill_section_run"]
    sec = registry.tool_sections("mix", "skill_section_run")
    assert "自定义章节" in sec and "流程章节" in sec


# ---------- ③ 回落：未声明/解析不到/非法声明者维持现行为 ----------


def test_custom_sections_undeclared_falls_back():
    _write("plain", _DOC_CUSTOM)
    entry = registry.get_entry("plain")
    assert entry.available_tools == []  # 与改造前完全一致
    assert registry.tool_sections("plain", "skill_section_run") == ""


def test_custom_sections_unresolvable_not_registered():
    """声明了但文档无对应章节：fail-closed，不注册半死通道。"""
    _write("hollow", "# 空\n> 调用规则：测试\n正文\n")
    frontmatter.write_manifest(
        "hollow", {"custom_sections": {"不存在章节": "skill_section_run"}})
    entry = registry.get_entry("hollow")
    assert "skill_section_run" not in entry.available_tools
    assert registry.tool_sections("hollow", "skill_section_run") == ""


def test_custom_sections_illegal_declaration_fail_hard():
    """C4 fail-hard（任务#22）：白名单外执行器声明 schema 违规，
    注册期直接拒注册（替代旧「告警照注册、消费端忽略」）；
    注册后改坏再 refresh 同样摘除条目（与 save_skill_doc 刷新链路同源）。"""
    _write("bad", _DOC_CUSTOM)
    frontmatter.write_manifest(
        "bad", {"custom_sections": {"tone_design": "script_analyze"}})
    # save_skill_doc 时（frontmatter 未写）已注册；改坏后 refresh 触发 fail-hard
    assert registry.refresh_skill("bad") is None
    assert registry.get_entry("bad") is None
    # 合法声明照常注册
    _write("livebad", _DOC_CUSTOM)
    frontmatter.write_manifest(
        "livebad", {"custom_sections": {"tone_design": "skill_section_run"}})
    entry = registry.get_entry("livebad")
    assert entry is not None and entry.custom_sections


# ---------- ④ 接线：轻量选中段与自定义章节（任务#12 批次B） ----------


def test_selected_block_lightweight_with_custom_sections():
    """任务#12 批次B：含自定义章节的 Skill 选中后同样只有轻量状态提示；
    章节原文（含自定义章节）不进 system prompt，由 read_skill 按需读取。"""
    _write("interview2", _DOC_CUSTOM)
    frontmatter.write_manifest(
        "interview2", {"custom_sections": {"tone_design": "skill_section_run"}})
    pb = PromptBuilder(
        lambda: sd,
        lambda: "proj",
        lambda: {"keyElements": [], "shots": [], "audioItems": []},
    )
    block = pb.build_selected_skill_block("访谈音色")
    # 轻量状态提示：名称 + read_skill 指引 + 正文零注入
    assert "== 当前选中 Skill「访谈音色」" in block
    assert "read_skill" in block
    assert "tone_design" not in block
    assert "音色档案" not in block
    # 执行器清单措辞已随退役删除
    assert "已注册独立执行器" not in block


def test_selected_block_lightweight_without_declaration():
    """未声明 custom_sections 的 Skill：轻量块同样零正文增量。"""
    _write("fixed", "# 固定\n> 调用规则：测试\n"
           "<script_analyze>\n分析\n</script_analyze>\n")
    pb = PromptBuilder(
        lambda: sd,
        lambda: "proj",
        lambda: {"keyElements": [], "shots": [], "audioItems": []},
    )
    block = pb.build_selected_skill_block("固定")
    assert "== 自定义章节" not in block
    assert "分析" not in block
