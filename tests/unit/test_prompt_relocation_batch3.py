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
    """暂停纪律唯一家 = skill_discipline.md（P1）；frontmatter 流程清单附注的
    复述防复活由 check_legacy_orchestration 门禁承接（P2d）。"""
    sd = load_prompt("planner/skill_discipline.md")
    assert "workflow_pause 工具调用真正停下" in sd, "暂停纪律单家条款丢失"


def test_f1_guide_card_boundary_reference():
    """F-1 快照锁：引导卡/暂停卡边界定义单家在宪法 Rule2，
    skill_discipline 第 2 条只引用不复述机制细节（防家规打架）。"""
    sd = load_prompt("planner/skill_discipline.md")
    assert "引导卡与暂停卡的边界定义见宪法 Rule2" in sd, "边界定义引用丢失"
    assert "由代码执行，不依赖模型自觉" not in sd, "机制细节复述回潮"
    rules = (ROOT / "ARCHITECTURE_RULES.md").read_text(encoding="utf-8")
    assert "引导卡仅承载客观状态选项" in rules, "宪法 Rule2 边界定义丢失"


def test_finalization_to_document_clause():
    """任务#6 C-1 快照锁：剧本定稿入文档的编排约定在 skill_discipline.md 单家在场：
    用户表达定稿意图 → 先 workflow_pause 弹确认卡（存入文档/继续打磨）→
    用户确认后调 document_write 写入（措辞为中性陈述，无禁令词）。"""
    sd = load_prompt("planner/skill_discipline.md")
    assert "存入文档" in sd, "定稿确认卡选项条款丢失"
    assert "继续打磨" in sd, "定稿确认卡选项条款丢失"
    assert "document_write" in sd, "定稿写入工具条款丢失"
    assert "定稿" in sd


def test_f2_prompt_dual_source_merge():
    """F-2 双源合并快照锁：
    ① 防虚报表述源唯一 = skill_discipline 第 9 条（含状态对账细节），
       important_rules 只留一句引用式短述；
    ② 回复精简模型可见表述归 output_discipline 条目 1，铁律模板只留指针；
    ③ 优先级链三处措辞以 iron_rules_header 为唯一源对齐。"""
    from src.video_agent.core.spec_rules import _IRON_RULES_DOC_BODY, _NEW_PRIORITY

    ir = load_prompt("shared/important_rules.md")
    assert "《Skill 流程纪律》第 9 条" in ir, "防虚报引用式短述丢失"
    assert "动作通道唯一 = 工具调用，只在正文写不产生任何效果" not in ir, "防虚报双源回潮"
    sd = load_prompt("planner/skill_discipline.md")
    assert "状态对账" in sd, "防虚报表述源（第 9 条）丢失"

    od = load_prompt("shared/output_discipline.md")
    assert "已写入" in od and "一句话摘要" in od, "回复纪律表述源丢失"
    assert "回复纪律见平台协议" in _IRON_RULES_DOC_BODY
    assert "逐卡罗列" not in _IRON_RULES_DOC_BODY, "铁律模板复述回复纪律回潮"

    header = load_prompt("shared/iron_rules_header.md")
    assert _NEW_PRIORITY in header, "优先级链措辞与唯一源（iron_rules_header）不一致"
    governance = (ROOT / "docs" / "GOVERNANCE.md").read_text(encoding="utf-8")
    assert "用户最新指令 > 铁律文档 + 制片规格 > Skill/系统默认" in governance, \
        "GOVERNANCE 裁决链措辞未对齐唯一源"


def test_b3_agent_loop_templates_wired():
    """agent_loop 运行时文案走 feedback.md 分节（分节在场即接线有效；
    代码内置兜底允许保留但不得作为唯一来源）。"""
    src = (ROOT / "src/video_agent/core/agent_loop.py").read_text(encoding="utf-8")
    for anchor in ("BAD_OUTPUT_NUDGE", "STEP_FEEDBACK", "EMPTY_RESPONSE_FALLBACK"):
        assert anchor in src, f"agent_loop 未接线分节: {anchor}"
