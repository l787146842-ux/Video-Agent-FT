"""PromptBuilder 选中 Skill 段（批4/ADR-0007：渐进披露预算化注入口径）。

钉死：选中 Skill 段产出选中提示 + 元数据头 + 《Skill 流程纪律》全文（评审修复批
挂回，用户裁决）+ 正文头部（按 settings.skill_inject_max_tokens 预算、按章节边界切齐，
超出附 read_skill 续读指引）；短 Skill 预算内全文一次注入；
全文硬直注/分级注入/回落截断三形态保持整体退役。"""
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


def test_selected_skill_block_full_injection_for_short_skill(skills_dir):
    """短 Skill（批4/ADR-0007）：预算内全文一次注入 + 流程纪律"""
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
    # 预算内全文注入（章节标签随正文在场）+ 完整注入提示，无续读指引
    assert "全文已按渐进披露预算完整注入" in block
    assert "script_analyze" in block and "write_media_prompt" in block
    assert "正文头部到此为止" not in block  # 未截断不附续读指引
    # 《Skill 流程纪律》全文随选中 Skill 挂回在场（评审修复批）
    assert "Skill 流程纪律" in block
    # 历史注入形态措辞全部退役（压制性包壳同批退役）
    assert "已注册独立执行器" not in block
    assert "== 当前选中 Skill「演示4」全文" not in block


def test_selected_skill_block_budget_head_for_oversized_skill(skills_dir):
    """超长 Skill（批4/ADR-0007）：正文头部预算注入 + 续读指引（分级注入形态保持退役）"""
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
    assert "正文头部已按渐进披露预算注入" in block
    assert "read_skill" in block and "正文头部到此为止" in block  # 续读指引在场
    # 头部探针（正文前部）经预算注入；预算外章节探针零注入，按章节边界切齐不击穿预算
    assert "UNIQUE_PLANNER_MARK" in block
    assert "UNIQUE_KE_MARK" not in block and "UNIQUE_WP_MARK" not in block
    # 分级注入三件套（章节全文/章节目录/首段回落）保持退役
    assert "章节目录" not in block
    assert "正文首段" not in block
    # 《Skill 流程纪律》全文挂回在场（评审修复批，用户裁决：预算充裕保持原样注入）
    assert "Skill 流程纪律" in block
    # 预算头部+纪律体量受预算约束（仍远低于历史全文/分级注入形态）
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

