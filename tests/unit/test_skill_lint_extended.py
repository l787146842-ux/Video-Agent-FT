"""Skill lint 扩展（整改计划批 5，对标 Flova 固定组成）。

三类新检查（只告警不阻断，F4 语义）：
① 体量预算（全文注入截断阈值 80% 预警）；
② 章节完整性对照 Flova 组成（流程型 Skill 缺核心段才告警）；
③ frontmatter 声明体检（解析/schema 编辑期预警，任务#5 后口径）。
另含保存路由接线断言（814R 型断线防复发：lint 必须有消费方）。
（原「有流程章节但未声明 steps」提示已随任务#5 流程抄本通道废除退役：
正文 planner 是唯一流程源，无 steps 声明可补。）
"""
from pathlib import Path

from src.video_agent.web import skill_docs as sd

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "data" / "skills"


def test_bulk_budget_warns_over_80_percent():
    content = "<planner>\n流程\n</planner>\n" + ("填充" * 13000)  # > 30000*0.8
    result = sd.lint_skill_content(content)
    assert any("建议预算" in w for w in result["warnings"])


def test_bulk_budget_silent_under_budget():
    content = "<planner>\n流程\n</planner>\n短文档"
    result = sd.lint_skill_content(content)
    assert not any("建议预算" in w for w in result["warnings"])


def test_flova_composition_warns_missing_core_parts():
    """流程型 Skill（有 planner）缺故事板/生成/提示词段 → 单条组成告警"""
    content = "<planner>\n步骤 1：分析剧本\n步骤 2：写规格\n</planner>"
    result = sd.lint_skill_content(content)
    comp = [w for w in result["warnings"] if "标准组成" in w]
    assert len(comp) == 1
    assert "故事板设计" in comp[0] and "媒体生成" in comp[0]


def test_flova_composition_silent_when_complete():
    content = (
        "<planner>\n流程：故事板拆解→生成→提示词写法\n</planner>\n"
        "<storyboard_designer>\n分镜与关键元素设计\n</storyboard_designer>\n"
        "<media_generator>\n生成设定图\n</media_generator>\n"
        "<write_the_prompt>\n提示词写法规范\n</write_the_prompt>\n"
    )
    result = sd.lint_skill_content(content)
    assert not any("标准组成" in w for w in result["warnings"])


def test_flova_composition_skips_freeform_skills():
    """无执行器章节且无 planning 段的自由型 Skill 不误伤"""
    result = sd.lint_skill_content("# 音色参考\n一些音色偏好描述，无流程章节。")
    assert not any("标准组成" in w for w in result["warnings"])


def test_frontmatter_lint_warns_on_schema_issue():
    """任务#5：frontmatter 声明问题编辑期预警（只告警不阻断）。"""
    content = "---\ngates:\n  unknown_gate: true\n---\n<planner>\n1. 分析剧本\n</planner>"
    result = sd.lint_skill_content(content, slug="test-skill")
    assert any("frontmatter 声明问题" in w for w in result["warnings"])


def test_frontmatter_lint_silent_when_valid():
    content = "---\npause:\n  stage_pause: true\n---\n<planner>\n1. 分析剧本\n</planner>"
    result = sd.lint_skill_content(content, slug="test-skill")
    assert not any("frontmatter 声明" in w for w in result["warnings"])


def test_put_route_returns_lint():
    """接线防复发：PUT /skills/docs/{slug} 响应必须携带 lint（只告警不阻断）"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.video_agent.web.routes import plugins as plugins_routes

    probe_app = FastAPI()
    probe_app.include_router(plugins_routes.router, prefix="/api")
    client = TestClient(probe_app)
    resp = client.put(
        "/api/skills/docs/__lint_probe__",
        json={"content": "# 探针\n<planner>\n流程\n</planner>\n"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert "lint" in payload and "warnings" in payload["lint"]
    # 清理探针文档（测试零残留）
    client.delete("/api/skills/docs/__lint_probe__")


def test_inventory_skills_lint_health_report():
    """16 存量 Skill 体检（只读不改，G1）：lint 全量可执行、结构合法；
    告警计数作为健康快照打印（供人工审阅，不作为失败条件）"""
    assert SKILLS_DIR.exists(), "data/skills 目录缺失"
    # 批3 单一包形态：每个存量 Skill = <slug>/SKILL.md 目录包
    packages = sorted(
        (p, p / "SKILL.md") for p in SKILLS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(".")
        and (p / "SKILL.md").exists())
    assert len(packages) >= 16, f"存量 Skill 数量异常：{len(packages)}"
    total_warnings = 0
    for pkg, f in packages:
        content = f.read_text(encoding="utf-8")
        result = sd.lint_skill_content(content, slug=pkg.name)
        assert isinstance(result.get("available_tools"), list)
        assert isinstance(result.get("warnings"), list)
        total_warnings += len(result["warnings"])
        if result["warnings"]:
            print(f"  [{pkg.name}] " + " | ".join(result["warnings"]))
    print(f"[体检] {len(packages)} 个存量 Skill，共 {total_warnings} 条 lint 告警")
