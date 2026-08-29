# -*- coding: utf-8 -*-
"""任务#12 批次B 防回归测试（普通测试，不新增门禁）；
批4/ADR-0007 口径刷新：选中 Skill 正文改经渐进披露预算化注入——
1) 真实超 2 万字 Skill：正文头部按预算注入（头部探针在场），
   预算外尾部探针零注入，附 read_skill 续读指引；
2) 组合激活（1 pipeline + N style 层）：主流程正文头部预算注入，
   风格层正文仍零注入（只在目录段以名称可见）。
"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core import gates_inputs
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.core.planner import PlannerContext
from src.video_agent.skill_runtime import frontmatter, registry

# 探针：真实超长 Skill（约 4 万字）正文中的独有短语；
# 同时钉该短语确实存在于 data/skills 源文件（防探针失效静默通过）
LONG_SKILL_NAME = "3D国漫古装精品短剧"
# 头部探针（正文前部，预算头部内）+ 尾部探针（全文唯一且远离头部，
# 预算外）：一正一反钉预算切分边界（批4/ADR-0007）
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


def test_system_prompt_long_skill_head_budget_injection():
    """选中真实超长 Skill（批4/ADR-0007）：正文头部按预算注入，
    预算外尾部零注入，附 read_skill 续读指引。"""
    text = _pb(_base_state()).build_system_prompt(_ctx(LONG_SKILL_NAME))
    # 头部探针经预算注入在场；尾部探针零注入（全文按需，不击穿预算）
    assert BODY_PROBE in text
    assert TAIL_PROBE not in text
    # 目录行在场（L1 元数据：名称 + 摘要）
    assert "Skill 目录" in text and LONG_SKILL_NAME in text
    # 选中提示 + 续读指引在场（渐进披露口径）
    assert f"当前选中 Skill「{LONG_SKILL_NAME}」" in text
    assert "read_skill" in text and "正文头部到此为止" in text
    # 历史注入形态措辞全部退役（压制性包壳同批退役）
    assert "【执行基准声明】" not in text
    assert "== 平台边界声明" not in text
    assert "以后者为准" not in text
    assert "章节目录" not in text


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


def test_combo_activation_keeps_style_body_out_of_system_prompt():
    """组合激活（1 pipeline + N style 层，批4/ADR-0007）：主流程正文头部
    预算注入；风格层正文零注入，只在目录段以名称可见。"""
    primary_probe = "启动协议"  # 主流程正文锚点（短桩，预算内全文注入）
    # 存在性前置钉死（与 BODY_PROBE 口径对齐：防探针失效假绿）
    _, primary_content = sd.resolve_skill_content(PRIMARY_SKILL)
    assert primary_probe in primary_content
    raw = _base_state(
        activeSkill={"slug": PRIMARY_SKILL, "source": "user"},
        styleSkills=list(STYLE_SKILLS),
    )
    text = _pb(raw).build_system_prompt(_ctx(PRIMARY_SKILL))
    # 主流程正文头部经预算注入（短正文预算内全文在场）
    assert primary_probe in text
    # 风格层正文仍零注入（取标签内正文片段做探针，并钉其确在源文件）
    for style_name in STYLE_SKILLS:
        _, style_content = sd.resolve_skill_content(style_name)
        probe = _style_body_probe(style_content)
        assert probe and probe in style_content, f"探针失效: {style_name}"
        assert probe not in text, f"风格层正文泄漏: {style_name}"
    # 风格层只在目录段可见（名称提示 + read_skill 按需指引）
    assert "另有风格层叠加生效" in text
    for style_name in STYLE_SKILLS:
        assert style_name in text
    assert "read_skill" in text


# ---------- 轻量路径分支覆盖（新注入路径的异常/降级分支回填） ----------

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


def test_metadata_header_exception_branches_degrade_to_empty(tmp_skills):
    """manifest/kind/语言/暂停点查询异常分支：各自降级不抛，无其余字段时头返空"""
    from src.video_agent.skill_runtime import guard as skill_guard

    # M2 门户：选中项注入放行须可加载（已注册）→ 带 frontmatter 必填键可注册
    sd.save_skill_doc(
        "炸桩", "---\nname: 炸桩\ndescription: 测试桩\n---\n# 炸桩\n正文")
    pb = _pb_raw({})

    orig_m, orig_k = registry.skill_manifest_of, registry.skill_kind
    orig_l, orig_p = registry.skill_language, skill_guard.skill_pause_points
    try:
        registry.skill_manifest_of = lambda n: (_ for _ in ()).throw(RuntimeError())
        registry.skill_kind = lambda n: (_ for _ in ()).throw(RuntimeError())
        registry.skill_language = lambda n: (_ for _ in ()).throw(RuntimeError())
        skill_guard.skill_pause_points = lambda n: (_ for _ in ()).throw(RuntimeError())
        assert pb.build_skill_metadata_header("炸桩") == ""
        # 异常分支不阻断轻量块（仅标题行在场）
        block = pb.build_selected_skill_block("炸桩")
        assert "当前选中 Skill「炸桩」" in block
    finally:
        registry.skill_manifest_of = orig_m
        registry.skill_kind = orig_k
        registry.skill_language = orig_l
        skill_guard.skill_pause_points = orig_p


def test_metadata_header_missing_input_without_hint(tmp_skills):
    """原料未就绪且声明无 hint：回落类型标签兜底文案"""
    sd.save_skill_doc("需乐桩", "# 需乐桩\n正文")
    frontmatter.write_manifest(
        "需乐桩", {"name": "需乐桩", "description": "测试桩",
                   "requires_inputs": [{"type": "music", "required": True}]})
    registry.register_skill("需乐桩")
    block = _pb_raw({}).build_skill_metadata_header("需乐桩")
    assert "原料未就绪：本 Skill 需要音乐素材" in block
    # 原料到达后缺失行消失（分支另一侧）
    block2 = _pb_raw(
        {"assets": [{"type": "music", "url": "a.mp3"}]}
    ).build_skill_metadata_header("需乐桩")
    assert "原料未就绪" not in block2


def test_metadata_header_unknown_input_type_label_fallback(
        tmp_skills, monkeypatch):
    """白名单外原料类型：标签回落原始类型字符串（不误拦不崩）"""
    sd.save_skill_doc("异型桩", "# 异型桩\n正文")
    monkeypatch.setattr(
        registry, "skill_requires_inputs",
        lambda n: [{"type": "hologram", "required": True}])
    # 闸口保守放行（白名单外视为已满足）；此处强制判缺以覆盖标签回落分支
    monkeypatch.setattr(gates_inputs, "input_present", lambda s, t: False)
    block = _pb_raw({}).build_skill_metadata_header("异型桩")
    assert "本 Skill 需要hologram素材" in block


def test_metadata_header_language_zh_line(tmp_skills):
    """language.prompt=zh：语言闸生效告知行（运营状态面）"""
    sd.save_skill_doc("中文桩", "# 中文桩\n正文")
    frontmatter.write_manifest(
        "中文桩", {"name": "中文桩", "description": "测试桩",
                   "language": {"prompt": "zh"}})
    registry.register_skill("中文桩")
    block = _pb_raw({}).build_skill_metadata_header("中文桩")
    assert "用中文书写（平台语言闸生效）" in block


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
