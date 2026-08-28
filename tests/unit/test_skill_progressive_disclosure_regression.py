# -*- coding: utf-8 -*-
"""任务#12 批次B 防回归测试（普通测试，不新增门禁）：

系统只做两件事——L1 元数据目录（name+description）常驻注入 + 提供
read_skill 工具；任何 Skill 正文（全文直注/分级注入/组合注入）都
不进 system prompt。
1) 真实超 2 万字 Skill 的独有短语作探针：选中后 system prompt
   只含目录行 + 轻量状态提示，正文零注入；
2) 组合激活（1 pipeline + N style 层）后风格层正文同样不进
   system prompt，风格层只在目录段以名称可见。
"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core import gates_inputs
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.core.planner import PlannerContext
from src.video_agent.skill_runtime import frontmatter, registry

# 探针：真实超长 Skill（约 4.1 万字，>2 万字口径）正文中的独有短语；
# 同时钉该短语确实存在于 data/skills 源文件（防探针失效静默通过）
LONG_SKILL_NAME = "3D国漫古装精品短剧"
BODY_PROBE = "影像风格固定为3D古风，无需用户确认。"

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
    """前置钉死：探针短语确在超 2 万字源文件中（防探针失效假绿）。"""
    _, content = sd.resolve_skill_content(LONG_SKILL_NAME)
    assert len(content) > 20000
    assert BODY_PROBE in content


def test_system_prompt_has_no_skill_body_for_long_skill():
    """选中真实超长 Skill：system prompt 只含目录行 + 轻量状态提示，
    正文片段（探针短语）零注入。"""
    text = _pb(_base_state()).build_system_prompt(_ctx(LONG_SKILL_NAME))
    # 正文零注入（探针）
    assert BODY_PROBE not in text
    # 目录行在场（L1 元数据：名称 + 摘要）
    assert "Skill 目录" in text and LONG_SKILL_NAME in text
    # 轻量状态提示在场（选中名称 + read_skill 按需加载指引）
    assert f"当前选中 Skill「{LONG_SKILL_NAME}」" in text
    assert "read_skill" in text and "全文未注入" in text
    # 历史注入形态措辞全部退役
    assert "【执行基准声明】" not in text
    assert "== 平台边界声明" not in text
    assert "章节目录" not in text


def test_combo_activation_keeps_style_body_out_of_system_prompt():
    """组合激活（1 pipeline + N style 层）：主流程与各风格层正文
    都不进 system prompt；风格层只在目录段以名称可见。"""
    primary_probe = "启动协议"  # 主流程 planner 章节原文锚点
    raw = _base_state(
        activeSkill={"slug": PRIMARY_SKILL, "source": "user"},
        styleSkills=list(STYLE_SKILLS),
    )
    text = _pb(raw).build_system_prompt(_ctx(PRIMARY_SKILL))
    # 主流程正文零注入
    assert primary_probe not in text
    # 风格层正文同样零注入（取风格层源文件的独有短语做探针）
    for style_name in STYLE_SKILLS:
        _, style_content = sd.resolve_skill_content(style_name)
        # 取正文首行非空片段作该风格层的独有探针
        probe = next(
            (ln.strip() for ln in style_content.splitlines()
             if ln.strip() and not ln.strip().startswith("#")),
            "")
        assert probe and probe not in text, f"风格层正文泄漏: {style_name}"
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

    sd.save_skill_doc("炸桩", "# 炸桩\n正文")
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
        "需乐桩", {"requires_inputs": [{"type": "music", "required": True}]})
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
    frontmatter.write_manifest("中文桩", {"language": {"prompt": "zh"}})
    registry.register_skill("中文桩")
    block = _pb_raw({}).build_skill_metadata_header("中文桩")
    assert "用中文书写（平台语言闸生效）" in block


def test_metadata_header_no_raw_state_skips_input_probe(tmp_skills):
    """无 raw state 提供者：原料探测段整体省略，其余字段照常"""
    sd.save_skill_doc("需乐桩2", "# 需乐桩2\n正文")
    frontmatter.write_manifest(
        "需乐桩2", {"requires_inputs": [{"type": "music", "required": True}],
                     "version": "1.0"})
    registry.register_skill("需乐桩2")
    pb = PromptBuilder(lambda: sd, lambda: "proj", None)
    block = pb.build_skill_metadata_header("需乐桩2")
    assert "版本：1.0" in block
    assert "原料未就绪" not in block


@pytest.mark.allow_degradation
def test_catalog_list_failure_degrades_to_empty(tmp_skills, monkeypatch):
    """目录读取失败：返空串 + 降级遥测可见（不阻断对话）"""
    def boom():
        raise RuntimeError("docs unavailable")
    monkeypatch.setattr(sd, "list_skill_docs", boom)
    ctx = PlannerContext()
    ctx.use_studio_context = True
    assert _pb_raw({}).build_skill_catalog(ctx) == ""


def test_catalog_entry_fallbacks_slug_and_default_desc(tmp_skills):
    """目录行兜底：无 name 回落 slug；空摘要回落占位文案"""
    sd.save_skill_doc("兜底桩", "# 兜底桩\n正文")
    ctx = PlannerContext()
    ctx.use_studio_context = True

    class _StubDocs:
        def list_skill_docs(self):
            return [{"slug": "slug-only", "description": "  "}]

    pb = PromptBuilder(lambda: _StubDocs(), lambda: "proj", lambda: {})
    block = pb.build_skill_catalog(ctx)
    assert "slug-only：未提供摘要" in block
