"""批3（审核整改）：指令收敛入宪执行——prose 外置 + 暂停纪律单家（Rule6 快照锁语义）。

迁移内容：
1. prompt_builder 内硬编码模型指令块 → prompts/（global_settings /
   storyboard_progress / iron_rules_header；executor_runtime 已随任务#36 B5
   执行器一步退役删除，其语义由通用主路径 Skill 全文直注承接）；
2. agent_loop 运行时文案（空输出引导/步间回喂/空响应兜底）→ feedback.md 分节；
3. 暂停纪律四处表述收敛为 skill_discipline.md 单家（P1 规则单家）。

快照锁语义：迁入端关键语义在场 + 迁出端不得复述（防回潮）。
"""
from pathlib import Path

from src.video_agent.utils.prompts import (
    load_prompt, load_prompt_section, render_prompt,
)

ROOT = Path(__file__).resolve().parents[2]


# ---------- 迁入端：外置文件承载关键语义 ----------

# test_b3_executor_runtime_template_carries_clauses 已随任务#36 B5 执行器一步退役删除：
# 承载文件 prompts/planner/executor_runtime.md 已物理删除；执行方式/阶段边界/
# skill_section_run 等语义改由通用主路径 Skill 全文直注 + skill_discipline.md 承接。


def test_b3_feedback_sections_exist():
    for section in ("BAD_OUTPUT_NUDGE", "STEP_FEEDBACK", "EMPTY_RESPONSE_FALLBACK"):
        assert load_prompt_section("planner/feedback.md", section), \
            f"feedback.md 分节缺失: {section}"
    # 模板变量可替换
    nudge = load_prompt_section("planner/feedback.md", "BAD_OUTPUT_NUDGE")
    assert "{{attempt}}" in nudge
    assert "第 2 次" in nudge.replace("{{attempt}}", "2")


def test_b3_settings_templates_exist():
    for path in ("shared/global_settings.md", "shared/storyboard_progress.md",
                 "shared/iron_rules_header.md"):
        assert load_prompt(path), f"模板缺失: {path}"
    rendered = render_prompt("shared/global_settings.md", max_shot_duration=10,
                             image_line="", video_line="", chat_image_off=False)
    assert "全局生成设置" in rendered and "10 秒" in rendered
    # 条件行：未配置渠道时不出现空行残桩
    assert "- \n" not in rendered


# ---------- 迁出端：代码不得复述（防回潮） ----------

def test_b3_prompt_builder_no_inline_instructions():
    src = (ROOT / "src/video_agent/core/prompt_builder.py").read_text(encoding="utf-8")
    # 执行方式/虚报/通用能力 prose 已外置（兜底回落也不得保留实质条款）
    for gone in ("与状态对账不符", "虚报结果会被状态对账识破",
                 "无专属执行器的章节用 skill_section_run"):
        assert gone not in src, f"prompt_builder 仍内联指令: {gone}"


def test_b3_pause_discipline_single_home():
    """暂停纪律唯一家 = skill_discipline.md（P1）；sidecar 流程清单附注的
    复述防复活由 check_legacy_orchestration 门禁承接（P2d）。"""
    sd = load_prompt("planner/skill_discipline.md")
    assert "workflow_pause 工具调用真正停下" in sd, "暂停纪律单家条款丢失"


def test_b3_agent_loop_templates_wired():
    """agent_loop 运行时文案走 feedback.md 分节（分节在场即接线有效；
    代码内置兜底允许保留但不得作为唯一来源）。"""
    src = (ROOT / "src/video_agent/core/agent_loop.py").read_text(encoding="utf-8")
    for anchor in ("BAD_OUTPUT_NUDGE", "STEP_FEEDBACK", "EMPTY_RESPONSE_FALLBACK"):
        assert anchor in src, f"agent_loop 未接线分节: {anchor}"
