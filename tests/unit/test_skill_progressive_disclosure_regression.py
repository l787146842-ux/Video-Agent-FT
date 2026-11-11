# -*- coding: utf-8 -*-
"""渐进披露预算注入防回归（任务#12 批次B 口径演进版）。

2026-11-11 Flova 六节骨架裁决后，存量 Skill 主文档全部落在 12000 注入预算内
（约 2700–5900 字），不再有「真实超预算包」可作探针——用真实包验证截断会
立刻失效。故本文件改用**临时构造的超预算文档**验证同一条机制：

1) 选中 Skill 正文超 `skill_selected_inject_max_chars` 时：
   头部探针在场、预算外尾部探针零注入、附标题目录与 read_skill 续读指引；
2) 组合激活（1 pipeline + N style 层）：主流程正文预算注入，
   风格层正文仍零注入（只在目录段以名称可见）。
"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.core.planner import PlannerContext
from src.video_agent.skill_runtime import frontmatter, registry

# 临时超预算文档的探针（头部 / 尾部各一，尾部远离头部）
LONG_SKILL_NAME = "超预算探针包"
BODY_PROBE = "头部探针 PHRASE_HEAD_XYZ"
TAIL_PROBE = "尾部探针 PHRASE_TAIL_XYZ"
REF_PATH = "references/媒体生成.md"

PRIMARY_SKILL = "AI-短剧一站式生成"  # 存量 pipeline 型
STYLE_SKILLS = ["李安美学风格短片", "水墨风格武侠短片"]  # 存量 style 型


def _long_doc() -> str:
    """构造超预算主文档：头部探针在前 6000 字内，尾部探针在 12000 字之外。"""
    filler = "流程正文填充。" * 900  # 约 6300 字
    return (
        "---\nname: " + LONG_SKILL_NAME + "\ndescription: 预算切分探针\n---\n"
        "# " + LONG_SKILL_NAME + "\n\n"
        "## 一、目标\n\n" + BODY_PROBE + "\n\n" + filler + "\n\n"
        "## 二、制作流程\n\n" + filler + "\n\n"
        "## 三、参考资料\n\n"
        "需要时读 `" + REF_PATH + "`（read_skill(resource=\"" + REF_PATH + "\")）。\n\n"
        + TAIL_PROBE + "\n"
    )


@pytest.fixture(autouse=True)
def fresh_registry(tmp_path, monkeypatch):
    """把 Skill 目录指向临时目录，写入超预算探针包后按新目录注册。"""
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    sd.save_skill_doc(LONG_SKILL_NAME, _long_doc())
    try:
        yield
    finally:
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


def test_probe_phrase_positions():
    """前置钉死：头/尾探针确在超预算源文件中，且尾部探针远离头部（防探针失效假绿）。"""
    _, content = sd.resolve_skill_content(LONG_SKILL_NAME)
    assert len(content) > 12000
    assert BODY_PROBE in content
    assert TAIL_PROBE in content
    assert content.find(TAIL_PROBE) > 6000


def test_system_prompt_long_skill_truncates_with_outline():
    """通用口径：超预算主文档注入开头 + 标题目录，尾部正文靠 read_skill 续读。"""
    text = _pb(_base_state()).build_system_prompt(_ctx(LONG_SKILL_NAME))
    assert BODY_PROBE in text
    assert TAIL_PROBE not in text
    assert "Skill 目录" in text and LONG_SKILL_NAME in text
    assert f"当前选中 Skill「{LONG_SKILL_NAME}」" in text
    assert "read_skill" in text
    assert "标题目录" in text
    assert "<planner>" not in text
    # 历史注入形态措辞全部退役（压制性包壳同批退役）
    assert "【执行基准声明】" not in text
    assert "== 平台边界声明" not in text
    assert "以后者为准" not in text


def test_truncated_inject_still_surfaces_references():
    """截断注入必须补分册清单：指针在正文后段也不能失联（2026-11-11 事故）。"""
    text = _pb(_base_state()).build_system_prompt(_ctx(LONG_SKILL_NAME))
    assert REF_PATH in text, "分册指针必须出现在注入块中（从全文提取的清单）"


def test_style_layers_stay_out_of_context():
    """组合激活：风格层正文零注入，只在目录段以名称可见。

    注意本用例走**真实** skill 目录（风格层来自 data/skills），
    与预算切分用例的临时目录互不影响。
    """
    import src.video_agent.web.skill_docs as real_sd
    from src.video_agent.utils.paths import SKILL_DOCS_DIR as REAL_DIR

    orig = real_sd.SKILL_DOCS_DIR
    real_sd.SKILL_DOCS_DIR = REAL_DIR
    registry.reset_registry()
    try:
        ctx = _ctx(PRIMARY_SKILL)
        ctx.style_names = list(STYLE_SKILLS)
        text = _pb(_base_state()).build_system_prompt(ctx)
        for name in STYLE_SKILLS:
            assert name in text, f"目录段应可见风格层「{name}」"
    finally:
        real_sd.SKILL_DOCS_DIR = orig
        registry.reset_registry()


def test_stock_skills_all_within_budget():
    """存量 16 包主文档必须全部落在注入预算内（Flova 六节形态的核心理由）。

    直接读真实 data/skills，不受本文件临时目录夹具影响。
    """
    from src.video_agent.config import settings
    from src.video_agent.utils.paths import SKILL_DOCS_DIR as REAL_DIR

    limit = int(settings.skill_selected_inject_max_chars)
    over = []
    for doc in sorted(REAL_DIR.glob("*/SKILL.md")):
        raw = doc.read_text(encoding="utf-8-sig")
        _, body, _ = frontmatter.split_frontmatter(raw)
        if len(body) > limit:
            over.append((doc.parent.name, len(body)))
    assert not over, f"以下主文档超注入预算 {limit}: {over}"
