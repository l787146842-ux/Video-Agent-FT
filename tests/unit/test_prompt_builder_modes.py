"""PromptBuilder 选中 Skill 段（B1 裁决 2026-08-31：按需加载注入口径）。

钉死：选中 Skill 段产出选中提示 + 元数据头 + 《Skill 流程纪律》全文（评审修复批
挂回，用户裁决）+ <planner> 段全文 + 章节目录（其余章节经 read_skill 按需取读）；
预算式正文头部注入已退役（零判断方案不回退）。"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.skill_runtime import registry


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    # M2 门户：选中项注入放行须可加载（已注册）→ 隔离注册表，
    # 用例内懒同步只扫本临时目录；用例后重置防污染。
    registry.reset_registry()
    yield d
    registry.reset_registry()


def _pb():
    return PromptBuilder(
        lambda: sd,
        lambda: "proj",
        lambda: {"keyElements": [], "shots": [], "audioItems": []},
    )


def test_selected_skill_block_is_pointer_only(skills_dir):
    """dsh 口径：短 Skill 也只给加载指针，不把正文塞进 system prompt。"""
    sd.save_skill_doc(
        "演示4",
        "---\nname: 演示4\ndescription: 测试桩\n---\n"
        "# 演示4\n\n"
        "## 制作流程\n流程正文\n\n"
        "## 剧本分析\n分析\n\n"
        "## 关键元素\n关键元素\n\n"
        "## 提示词写法\n提示词\n",
    )
    block = _pb().build_selected_skill_block("演示4")
    assert "当前主 Skill「演示4」" in block
    assert "read_skill" in block
    assert "流程正文" not in block
    assert "Skill 流程纪律" in block
    assert "<planner>" not in block


def test_selected_skill_block_oversized_doc_also_pointer_only(skills_dir):
    """超长 Skill 同样不注入正文；模型按需 read_skill。"""
    filler = "正文填充内容。" * 100
    sd.save_skill_doc(
        "超长流程",
        "---\nname: 超长流程\ndescription: 测试桩\n---\n"
        "# 超长流程\n\n"
        f"## 制作流程\n流程总纲 UNIQUE_PLANNER_MARK\n{filler}\n\n"
        f"## 关键元素\n关键元素规范 UNIQUE_KE_MARK\n{filler * 20}\n\n"
        f"## 提示词写法\n提示词规范 UNIQUE_WP_MARK\n{filler * 20}\n",
    )
    block = _pb().build_selected_skill_block("超长流程")
    assert "read_skill" in block
    assert "UNIQUE_PLANNER_MARK" not in block
    assert "UNIQUE_WP_MARK" not in block
    assert "标题目录" not in block
    assert "Skill 流程纪律" in block
    assert len(block) < 5000


def test_selected_skill_block_empty_for_unknown_skill(skills_dir):
    """不存在的 Skill：返空串（降级为仅目录）"""
    # 预置一个带章节 tag 的可注册桩：避免空目录触发 ensure_default 补默认文档，
    # 懒同步注册默认文档会打 heading_fallback 降级遥测（降级看门狗拦截）
    sd.save_skill_doc(
        "探针桩",
        "---\nname: 探针桩\ndescription: 测试桩\n---\n"
        "# 探针桩\n<script_analyze>\n占位\n</script_analyze>\n",
    )
    assert _pb().build_selected_skill_block("不存在") == ""


def test_selected_skill_block_empty_when_resolve_raises(skills_dir, monkeypatch):
    """解析异常不阻断对话：返空串（降级遥测可见）"""
    sd.save_skill_doc("炸桩", "# 炸桩\n正文")

    def boom(_name):
        raise RuntimeError("docs unavailable")

    monkeypatch.setattr(sd, "resolve_skill_content", boom)
    assert _pb().build_selected_skill_block("炸桩") == ""


def test_system_prompt_over_threshold_warns(skills_dir, monkeypatch):
    """遥测：组装总长超阈值预警分支可达（纪律挂回后体量钉观测面仍工作）。"""
    import src.video_agent.core.prompt_builder as pb_mod
    from src.video_agent.core.planner import PlannerContext

    # 预置带章节 tag 的可注册桩：避免空目录触发 ensure_default 补默认文档，
    # 懒同步注册默认文档会打 heading_fallback 降级遥测（降级看门狗拦截）
    sd.save_skill_doc(
        "探针桩",
        "---\nname: 探针桩\ndescription: 测试桩\n---\n"
        "# 探针桩\n<script_analyze>\n占位\n</script_analyze>\n",
    )
    monkeypatch.setattr(pb_mod, "_SYSTEM_PROMPT_WARN_CHARS", 0)
    text = _pb().build_system_prompt(PlannerContext(use_studio_context=False, skill_name=""))
    assert text


def test_system_prompt_telemetry_exception_not_blocking(skills_dir, monkeypatch):
    """遥测分项入账异常不阻断组装：record_sections 抛错静默忽略、正文照常返回"""
    import src.video_agent.core.prompt_builder as pb_mod
    from src.video_agent.core.planner import PlannerContext

    sd.save_skill_doc(
        "探针桩",
        "---\nname: 探针桩\ndescription: 测试桩\n---\n"
        "# 探针桩\n<script_analyze>\n占位\n</script_analyze>\n",
    )

    def boom(*_a, **_k):
        raise RuntimeError("metrics unavailable")

    monkeypatch.setattr(pb_mod.live_metrics, "record_sections", boom)
    text = _pb().build_system_prompt(PlannerContext(use_studio_context=False, skill_name=""))
    assert text

