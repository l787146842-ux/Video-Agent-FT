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


def test_selected_skill_block_planner_and_toc_for_short_skill(skills_dir):
    """短 Skill（B1）：无 planner 段时只注入章节目录，预算式全文注入退役"""
    sd.save_skill_doc(
        "演示4",
        "---\nname: 演示4\ndescription: 测试桩\n---\n"
        "# 演示4\n> 调用规则：测试\n"
        "<script_analyze>\n分析\n</script_analyze>\n"
        "<storyboard_key_elements>\n关键元素\n</storyboard_key_elements>\n"
        "<write_media_prompt>\n提示词\n</write_media_prompt>\n",
    )
    block = _pb().build_selected_skill_block("演示4")
    assert "当前选中 Skill「演示4」" in block
    # B1 新口径：章节正文零注入，只注入章节目录（章节名在场）
    assert "下方已注入流程（planner）段全文与章节目录" in block
    assert "script_analyze" in block and "write_media_prompt" in block
    assert "正文头部到此为止" not in block  # 预算续读指引退役
    # 《Skill 流程纪律》全文随选中 Skill 挂回在场（评审修复批）
    assert "Skill 流程纪律" in block
    # 历史注入形态措辞全部退役（压制性包壳同批退役）
    assert "已注册独立执行器" not in block
    assert "== 当前选中 Skill「演示4」全文" not in block
    # 章节正文探针零注入（只有目录行）
    assert "分析\n" not in block


def test_selected_skill_block_planner_only_for_oversized_skill(skills_dir):
    """超长 Skill（B1）：只注入 <planner> 段全文 + 章节目录，其余章节零注入"""
    filler = "正文填充内容。" * 100
    sd.save_skill_doc(
        "超长流程",
        "---\nname: 超长流程\ndescription: 测试桩\n---\n"
        "# 超长流程\n> 调用规则：测试\n"
        f"<planner>\n流程总纲 UNIQUE_PLANNER_MARK\n{filler}</planner>\n"
        f"<storyboard_key_elements>\n关键元素规范 UNIQUE_KE_MARK\n{filler * 20}</storyboard_key_elements>\n"
        f"<write_media_prompt>\n提示词规范 UNIQUE_WP_MARK\n{filler * 20}</write_media_prompt>\n",
    )
    block = _pb().build_selected_skill_block("超长流程")
    assert "下方已注入流程（planner）段全文与章节目录" in block
    assert "read_skill" in block  # 按需取读指引在场（预算续读指引退役）
    # planner 段全文注入；其余章节正文零注入（只有目录行）
    assert "UNIQUE_PLANNER_MARK" in block
    assert "UNIQUE_KE_MARK" not in block and "UNIQUE_WP_MARK" not in block
    # 章节目录在场（含各章节名与字数）
    assert "章节目录" in block
    assert "storyboard_key_elements" in block and "write_media_prompt" in block
    assert "正文首段" not in block
    # 《Skill 流程纪律》全文挂回在场（评审修复批，用户裁决：预算充裕保持原样注入）
    assert "Skill 流程纪律" in block
    # 按需注入体量远低于历史全文/预算头部注入形态（planner 段 + 目录 + 纪律）
    assert len(block) < 20000


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

