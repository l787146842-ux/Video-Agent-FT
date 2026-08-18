# -*- coding: utf-8 -*-
"""0818-2222 DAG 修复回归 — 依赖尾对丢失 / 编号冲突 / manifest 声明通道 / 注册期 lint。

本文件覆盖：
F1 依赖行末对不因「行尾无分号」而丢失
F2 同号编号列表后来居上（启动协议类清单不再顶掉流程步骤）
F3 manifest flow.steps/dependencies 声明通道（确定性调度；未声明回落正文解析）
F4 lint：依赖引用必须命中步骤、同号冲突可见
F5 AI-短剧 manifest 回填黄金用例
"""
import inspect

import pytest

from src.video_agent.skill_runtime import dag


# ---------- 自包含样例：<planner> 双编号列表（协议 3 条 + 流程 8 步） ----------

_PLANNER_DUAL_LIST = """
**启动协议**

1. 当前所处阶段（从零开始，还是已有部分产出？）
2. 已有素材（请用户上传或粘贴现有剧本）
3. 输出语言偏好

**全流程阶段与依赖关系**

1. 读取并分析用户上传的剧本文件 → **resource_prepare_and_analyze**
2. 将全局制作参数写入 Final_Video_Spec.md → **text_editor**
3. 设计 Storyboard：登记 key_element、拆解 shot、规划 audio_layer → **storyboard_designer**
4. 生成所有 key_element 设定图 → **media_generator**
5. 生成运镜轨迹示意图 → **media_generator**
6. 逐 shot 生成视频 → **media_generator**
7. 生成所有 audio_layer 音频资产 → **media_generator**
8. 按 Storyboard 顺序组装时间线 → **video_assembler**

**依赖关系：** 3→1,2；4→3；5→3；6→4,5；7→3；8→4,5,6,7

**关键暂停点：** 每个阶段完成后必须暂停。
"""


# ---------- F1：依赖行末对不丢 ----------

def test_dep_last_pair_at_line_end_not_dropped():
    """依赖行最后一对后面跟的是换行而非分号：照样解析出来。"""
    deps = dag.parse_dependencies("前置说明\n3→1,2；4→3；8→4,5,6,7\n\n**关键暂停点：** 每阶段暂停。")
    assert deps.get(8) == [4, 5, 6, 7], f"末对依赖丢失：{deps}"
    assert deps.get(3) == [1, 2]
    assert deps.get(4) == [3]


def test_dep_last_pair_with_trailing_period():
    """依赖行以句号收尾（存量 Skill 常见写法）：末对不丢。"""
    deps = dag.parse_dependencies("**依赖关系：** 2→1；3→1,2；8→3,4,5,6。")
    assert deps.get(8) == [3, 4, 5, 6], f"句号收尾末对丢失：{deps}"
    deps2 = dag.parse_dependencies("**依赖关系：** 2→1; 5→2,3; 7→2,3,4,5.")
    assert deps2.get(7) == [2, 3, 4, 5], f"英文句号收尾末对丢失：{deps2}"


# ---------- F2：同号编号列表后来居上 ----------

def test_later_numbered_list_wins():
    """同号冲突时保留后出现的列表（生产流程通常在协议/清单之后）。"""
    steps = dag.parse_steps(_PLANNER_DUAL_LIST)
    assert "剧本" in steps[1], f"step1 被启动协议顶掉：{steps.get(1)}"
    assert "Final_Video_Spec" in steps[2]
    assert "Storyboard" in steps[3]
    assert steps[8].startswith("按 Storyboard 顺序组装时间线")


# ---------- F1+F2 合力：调度输出不再放行越级末步 ----------

def test_pipeline_step8_blocked_before_prereqs():
    """前置 4~7 未完成时，step8（组装）不得 ready（空状态 = 一切未做）。"""
    status = dag.pipeline_status(_PLANNER_DUAL_LIST, {})
    by_no = {s["step"]: s for s in status}
    assert by_no[8]["ready"] is False, "依赖未满足不得放行末步"
    ready = [s["step"] for s in status if s["ready"]]
    assert 8 not in ready
    assert 1 in ready  # 无前置的首步照常可执行


# ---------- F3：manifest 声明通道 ----------

_MANIFEST_DECL = {
    "flow": {
        "steps": {"1": "分析剧本", "2": "写入规格", "3": "故事板设计"},
        "dependencies": {"2": [1], "3": [1, 2]},
    },
}


def test_manifest_steps_take_priority_over_text():
    """声明存在时只认声明：正文故意写成歧义结构也不影响调度。"""
    steps, deps = dag.resolve_steps_and_deps(_MANIFEST_DECL, _PLANNER_DUAL_LIST)
    assert steps == {1: "分析剧本", 2: "写入规格", 3: "故事板设计"}
    assert deps == {2: [1], 3: [1, 2]}


def test_manifest_absent_falls_back_to_text():
    """未声明 steps：回落正文解析（存量 Skill 行为不变）。"""
    steps, deps = dag.resolve_steps_and_deps(None, _PLANNER_DUAL_LIST)
    assert "剧本" in steps[1]
    assert deps.get(8) == [4, 5, 6, 7]
    steps2, deps2 = dag.resolve_steps_and_deps({"flow": {}}, _PLANNER_DUAL_LIST)
    assert steps2 == steps and deps2 == deps


def test_pipeline_status_from_manifest():
    """声明驱动的完成度/就绪计算：依赖未满足不放行。"""
    steps, deps = dag.resolve_steps_and_deps(_MANIFEST_DECL, "")
    status = dag.pipeline_status_from(steps, deps, {})
    by_no = {s["step"]: s for s in status}
    assert by_no[1]["ready"] is True
    assert by_no[2]["ready"] is False
    assert by_no[3]["ready"] is False


# ---------- F4：lint 门禁 ----------

def test_lint_detects_dangling_dependency():
    """依赖引用了不存在的步骤号 → lint 必须报出。"""
    issues = dag.lint_planner_dag(
        "1. 步骤一\n2. 步骤二\n\n**依赖关系：** 2→1；3→9", None)
    assert any("9" in s for s in issues), issues


def test_lint_detects_number_collision():
    """无声明时正文同号冲突 → lint 报冲突（可见，不静默）。"""
    issues = dag.lint_planner_dag(_PLANNER_DUAL_LIST, None)
    assert any("冲突" in s for s in issues), issues


def test_lint_clean_when_manifest_declared():
    """声明通道自洽时（引用全命中）→ 零告警，正文歧义不再追究。"""
    assert dag.lint_planner_dag(_PLANNER_DUAL_LIST, _MANIFEST_DECL) == []


def test_register_skill_wires_lint():
    """钉死：注册链路接入 lint（结构问题注册期可见）。"""
    from src.video_agent.skill_runtime import registry

    src = inspect.getsource(registry.register_skill)
    assert "lint_planner_dag(" in src


# ---------- F5：AI-短剧 manifest 回填黄金 ----------

def test_ai_short_drama_planner_golden():
    """回填声明后：零 lint 告警，步骤/依赖与文档流程一致。"""
    from src.video_agent.skill_runtime import registry

    entry = registry.register_skill("AI-短剧一站式生成")
    assert entry is not None
    planner_text = entry.sections.get("planning") or ""
    issues = dag.lint_planner_dag(planner_text, entry.manifest)
    assert issues == [], issues
    steps, deps = dag.resolve_steps_and_deps(entry.manifest, planner_text)
    assert "剧本" in steps[1]
    assert "Final_Video_Spec" in steps[2]
    assert "Storyboard" in steps[3]
    assert steps[8].startswith("按 Storyboard 顺序组装时间线")
    assert deps.get(8) == [4, 5, 6, 7]
    assert deps.get(3) == [1, 2]


# ---------- F5 扩展：存量 6 Skill 声明回填 + 全量盘点钉死 ----------

# 回填声明的 Skill → 关键步骤语义钉（首末步骤标题特征，防声明漂移）
_DECLARED_GOLDEN = {
    "AI-短剧一站式生成": ((1, "剧本"), (8, "组装")),
    "3D国漫古装精品短剧": ((1, "分析"), (8, "组装")),
    "人文纪录短片": ((1, "Final_Video_Spec"), (7, "组装")),
    "古风甜宠短剧": ((0, "剧本来源"), (7, "剪辑导出")),
    "未来科幻真人电影": ((1, "全局规格"), (7, "组装")),
    "李安美学风格短片": ((1, "构思"), (9, "超分")),
    "水墨风格武侠短片": ((1, "全局规格"), (7, "合成")),
    "剧情短片音色参考": ((1, "剧本"), (7, "剪辑")),
    "叙事驱动的美学视频": ((1, "Final_Video_Spec"), (6, "剪辑")),
}


@pytest.mark.parametrize("skill,checks", sorted(_DECLARED_GOLDEN.items()))
def test_declared_skills_semantic_golden(skill, checks):
    """声明回填黄金：关键步骤语义与文档流程一致，依赖声明非空。"""
    from src.video_agent.skill_runtime import registry

    entry = registry.register_skill(skill)
    assert entry is not None
    planner_text = entry.sections.get("planning") or ""
    steps, deps = dag.resolve_steps_and_deps(entry.manifest, planner_text)
    assert len(steps) >= 6, f"{skill} 声明步骤数异常：{steps}"
    assert deps, f"{skill} 缺依赖声明（无依赖约束的调度会一口气放行末步）"
    for no, kw in checks:
        assert no in steps and kw in steps[no], \
            f"{skill} step{no} 语义漂移：{steps.get(no)}"


def test_all_product_skills_planner_lint_clean():
    """全量盘点钉死：data/skills 下所有产品 Skill 的 <planner> 体检零告警
    （声明从注册表读——B0 起 sidecar 优先）。"""
    from pathlib import Path
    from src.video_agent.skill_runtime import registry

    d = Path(__file__).resolve().parents[2] / "data" / "skills"
    skills = sorted(d.glob("*.md"))
    assert skills, "产品 Skill 目录为空"
    problems = []
    for f in skills:
        entry = registry.register_skill(f.stem)
        assert entry is not None, f.stem
        planner = entry.sections.get("planning") or ""
        issues = dag.lint_planner_dag(planner, entry.manifest)
        if issues:
            problems.append(f"{f.stem}：{'；'.join(issues)}")
        # 末步无依赖 = 调度无条件放行末步（同型事故防线）：
        # 流程类 Skill（步骤数≥5）的最大步骤号必须带依赖声明
        steps, deps = dag.resolve_steps_and_deps(entry.manifest, planner)
        if len(steps) >= 5:
            last = max(steps)
            if last not in deps:
                problems.append(f"{f.stem}：末步 {last} 无依赖声明（会被无条件放行）")
    assert problems == [], "\n".join(problems)
