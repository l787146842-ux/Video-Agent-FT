# -*- coding: utf-8 -*-
"""任务#12 批次B 防回归测试（普通测试，不新增门禁）；
指令性制作手册口径刷新（决策史见 git tag adr-archive-20260901）：选中 Skill 正文改经渐进披露预算化注入——
1) 真实超 2 万字 Skill：正文头部按预算注入（头部探针在场），
   预算外尾部探针零注入，附 read_skill 续读指引；
2) 组合激活（1 pipeline + N style 层）：主流程正文头部预算注入，
   风格层正文仍零注入（只在目录段以名称可见）。
"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.core.planner import PlannerContext
from src.video_agent.skill_runtime import frontmatter, registry

# 探针：真实超长 Skill（约 4 万字）正文中的独有短语；
# 同时钉该短语确实存在于 data/skills 源文件（防探针失效静默通过）
LONG_SKILL_NAME = "3D国漫古装精品短剧"
# 头部探针（正文前部，预算头部内）+ 尾部探针（全文唯一且远离头部，
# 预算外）：一正一反钉预算切分边界（指令性制作手册口径）
BODY_PROBE = "影像风格固定为3D古风，无需用户确认。"
TAIL_PROBE = "**导出基准**"

PRIMARY_SKILL = "AI-短剧一站式生成"  # 存量 pipeline 型
STYLE_SKILLS = ["李安美学风格短片", "水墨风格武侠短片"]  # 存量 style 型


@pytest.fixture(autouse=True)
def fresh_registry():
    registry.reset_registry()  # 按真实 data/skills 目录重新注册
    yield
    registry.reset_registry()


def _ctx(skill_name: str) -> PlannerContext:
    ctx = PlannerContext()
    ctx.use_studio_context = True
    ctx.skill_name = skill_name
    return ctx


def _pb(raw_state) -> PromptBuilder:
    return PromptBuilder(lambda: sd, lambda: "proj", lambda: raw_state)


def _base_state(**extra):
    raw = {"keyElements": [], "shots": [], "audioItems": []}
    raw.update(extra)
    return raw


def test_probe_phrase_exists_in_source_skill():
    """前置钉死：头/尾探针确在超 2 万字源文件中，且尾部探针不在头部区间（防探针失效假绿）。"""
    _, content = sd.resolve_skill_content(LONG_SKILL_NAME)
    assert len(content) > 20000
    assert BODY_PROBE in content
    assert TAIL_PROBE in content
    # 尾部探针远离头部预算区间且全文唯一（反向探针有效性）
    assert content.find(TAIL_PROBE) > 9000 and content.count(TAIL_PROBE) == 1


def test_system_prompt_long_skill_planner_only_injection():
    """选中真实超长 Skill（B1 裁决 2026-08-31）：默认只注入 <planner> 段全文
    + 章节目录，其余章节正文经 read_skill 按需取读。"""
    text = _pb(_base_state()).build_system_prompt(_ctx(LONG_SKILL_NAME))
    # planner 段探针在场；非 planner 章节探针零注入（只进目录）
    assert BODY_PROBE in text
    assert TAIL_PROBE not in text
    # 目录行在场（L1 元数据：名称 + 摘要）
    assert "Skill 目录" in text and LONG_SKILL_NAME in text
    # 选中提示 + 取读指引在场（按需加载口径）
    assert f"当前选中 Skill「{LONG_SKILL_NAME}」" in text
    assert "read_skill" in text and "正文头部到此为止" not in text
    # 历史注入形态措辞全部退役（压制性包壳同批退役）
    assert "【执行基准声明】" not in text
    assert "== 平台边界声明" not in text
    assert "以后者为准" not in text
    assert "章节目录" in text  # B1：章节目录在场（按需取读入口）


def _style_body_probe(style_content: str) -> str:
    """风格层正文独有探针：取 <planner> 标签内首个非空行（标签本身不在章节拆分
    结果里，取首行会撞标签漏报）；无标签时回落首个非标题非空行。"""
    lines = style_content.splitlines()
    try:
        idx = next(i for i, ln in enumerate(lines) if ln.strip() == "<planner>")
    except StopIteration:
        idx = -1
    pool = lines[idx + 1:] if idx >= 0 else lines
    return next(
        (ln.strip() for ln in pool
         if ln.strip() and not ln.strip().startswith("#")
         and not ln.strip().startswith("<")),
        "")


@pytest.fixture
def tmp_skills(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    yield d
    registry.reset_registry()


def _pb_raw(raw):
    return PromptBuilder(lambda: sd, lambda: "proj", lambda: raw)


def test_selected_block_empty_when_content_blank(tmp_skills, monkeypatch):
    """正文为空白：返空串（降级为仅目录，不产出残壳）"""
    sd.save_skill_doc("空白桩", "# 空白桩\n正文")
    monkeypatch.setattr(sd, "resolve_skill_content", lambda n: ("空白桩", "  \n"))
    assert _pb_raw({}).build_selected_skill_block("空白桩") == ""


def test_selected_block_falls_back_to_raw_name_when_display_blank(
        tmp_skills, monkeypatch):
    """resolve 返回空 display：回落传入名（轻量提示仍产出）"""
    sd.save_skill_doc("回落桩", "# 回落桩\n正文")
    monkeypatch.setattr(sd, "resolve_skill_content", lambda n: ("", "正文"))
    block = _pb_raw({}).build_selected_skill_block("回落桩")
    assert "当前选中 Skill「回落桩」" in block


def test_metadata_header_missing_input_without_hint(tmp_skills):
    """C1b 裁决 2026-08-31：requires_inputs 原料声明轴退役——
    元数据头不再注入原料未就绪段（声明忽略，零警告）。"""
    sd.save_skill_doc("需乐桩", "# 需乐桩\n正文")
    frontmatter.write_manifest(
        "需乐桩", {"name": "需乐桩", "description": "测试桩",
                   "requires_inputs": [{"type": "music", "required": True}]})
    registry.register_skill("需乐桩")
    block = _pb_raw({}).build_skill_metadata_header("需乐桩")
    assert "原料未就绪" not in block


def test_metadata_header_no_raw_state_skips_input_probe(tmp_skills):
    """无 raw state 提供者：原料探测段整体省略，其余字段照常"""
    sd.save_skill_doc("需乐桩2", "# 需乐桩2\n正文")
    frontmatter.write_manifest(
        "需乐桩2", {"name": "需乐桩2", "description": "测试桩",
                    "requires_inputs": [{"type": "music", "required": True}],
                    "version": "1.0"})
    registry.register_skill("需乐桩2")
    pb = PromptBuilder(lambda: sd, lambda: "proj", None)
    block = pb.build_skill_metadata_header("需乐桩2")
    assert "版本：1.0" in block
    assert "原料未就绪" not in block


@pytest.mark.allow_degradation
def test_catalog_list_failure_degrades_to_empty(tmp_skills, monkeypatch):
    """目录读取失败：返空串 + 降级遥测可见（不阻断对话）。
    M3 批2：目录段数据源 = 注册表门户，降级分支改由 loadable_entries 抛错触发"""
    def boom():
        raise RuntimeError("registry unavailable")
    monkeypatch.setattr(registry, "loadable_entries", boom)
    ctx = PlannerContext()
    ctx.use_studio_context = True
    assert _pb_raw({}).build_skill_catalog(ctx) == ""


def test_catalog_entry_fallbacks_slug_and_default_desc(tmp_skills, monkeypatch):
    """目录行防御性兜底：空摘要回落占位文案（M3 批2 后注册派生 name 恒有值、
    description 注册期必填，本分支只剩防御面——直接钉门户返回形状）"""
    from types import SimpleNamespace

    stub = [SimpleNamespace(slug="slug-only", name="slug-only", manifest={})]
    monkeypatch.setattr(registry, "loadable_entries", lambda: stub)
    ctx = PlannerContext()
    ctx.use_studio_context = True
    block = PromptBuilder(lambda: sd, lambda: "proj", lambda: {}).build_skill_catalog(ctx)
    assert "slug-only：未提供摘要" in block
