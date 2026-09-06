"""批3（审核整改）：指令收敛入宪执行——prose 外置 + 暂停纪律单家（Rule6 快照锁语义）。

迁移内容：
1. prompt_builder 内硬编码模型指令块 → prompts/（global_settings /
   storyboard_progress / iron_rules_header；executor_runtime 已随任务#36 B5
   执行器一步退役删除，其语义由通用主路径 Skill 全文直注承接）；
2. agent_loop 运行时文案（空输出引导/步间回喂/空响应兜底）→ feedback.md 分节；
3. 暂停纪律四处表述收敛为 skill_runtime.md 单家（P1 规则单家）。

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
# skill_section_run 等语义改由通用主路径 Skill 全文直注 + skill_runtime.md 承接。


def test_b3_feedback_sections_exist():
    # BAD_OUTPUT_NUDGE 已随批 2 退役删除（判空 = 正常收轮，nudge 重试退役）
    for section in ("STEP_FEEDBACK", "EMPTY_RESPONSE_FALLBACK",
                    "STEP_ASSISTANT_PLACEHOLDER"):
        assert load_prompt_section("planner/feedback.md", section), \
            f"feedback.md 分节缺失: {section}"
    # 工具轮 assistant 占位必须是客观陈述，不得是「本步无输出」式假陈述：
    # 该分支入口是「fc_applied>0 且无可见正文」（工具轮常态，本步实际执行了
    # 工具），假陈述会与紧随其后注入的 STEP_FEEDBACK（「第 N 轮的 X 个 Tool 已
    # 执行完毕」）自相矛盾。
    placeholder = load_prompt_section("planner/feedback.md", "STEP_ASSISTANT_PLACEHOLDER")
    assert "工具调用轮" in placeholder, "占位应客观陈述本轮为工具调用轮"
    assert "无输出" not in placeholder, "工具轮占位不得是假陈述（本步执行了工具）"


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
    """暂停纪律唯一家 = skill_runtime.md（P1）；frontmatter 流程清单附注的
    复述防复活由 check_legacy_orchestration 门禁承接（P2d）。"""
    sd = load_prompt_section("planner/skill_runtime.md", "DISCIPLINE")
    assert "workflow_pause 工具调用真正停下" in sd, "暂停纪律单家条款丢失"


def test_f1_guide_card_boundary_reference():
    """F-1 快照锁（整改批 2.2 修订）：引导卡/暂停卡边界定义单家在
    ARCHITECTURE_RULES.md；skill_runtime 不复述机制细节，也不再向
    模型可见层携带内部治理编号引用（「见宪法 Rule2」「层 9」属考古噪声，
    模型无从查阅）——引用删除后反向钉死防复活。"""
    sd = load_prompt_section("planner/skill_runtime.md", "DISCIPLINE")
    assert "宪法 Rule" not in sd and "层 9" not in sd, (
        "模型可见层内部编号引用回潮（批 2.2 已清偿）")
    assert "由代码执行，不依赖模型自觉" not in sd, "机制细节复述回潮"
    rules = (ROOT / "ARCHITECTURE_RULES.md").read_text(encoding="utf-8")
    assert "引导卡仅承载客观状态选项" in rules, "宪法 Rule2 边界定义丢失"


def test_finalization_to_document_clause():
    """任务#6 C-1 快照锁：剧本定稿入文档的编排约定在 skill_runtime.md 单家在场：
    用户表达定稿意图 → 先 workflow_pause 弹确认卡（存入文档/继续打磨）→
    用户确认后调 document_write 写入（措辞为中性陈述，无禁令词）。"""
    sd = load_prompt_section("planner/skill_runtime.md", "DISCIPLINE")
    assert "存入文档" in sd, "定稿确认卡选项条款丢失"
    assert "继续打磨" in sd, "定稿确认卡选项条款丢失"
    assert "document_write" in sd, "定稿写入工具条款丢失"
    assert "定稿" in sd


def test_f2_prompt_dual_source_merge():
    """F-2 双源合并快照锁（重组后单家 = protocol.md / skill_runtime.md）：
    ① 防虚报表述源唯一 = skill_runtime《Skill 流程纪律》第 9 条（含状态对账细节），
       protocol 只留一句引用式短述；
    ② 回复精简模型可见表述归 protocol 回复输出纪律条目 1，铁律模板只留指针；
    ③ 优先级链三处措辞以 iron_rules_header 为唯一源对齐。"""
    from src.video_agent.core.spec_rules import _IRON_RULES_DOC_BODY, _NEW_PRIORITY

    ir = load_prompt("planner/protocol.md")
    assert "《Skill 流程纪律》第 9 条" in ir, "防虚报引用式短述丢失"
    assert "动作通道唯一 = 工具调用，只在正文写不产生任何效果" not in ir, "防虚报双源回潮"
    sd = load_prompt_section("planner/skill_runtime.md", "DISCIPLINE")
    assert "状态对账" in sd, "防虚报表述源（第 9 条）丢失"

    od = load_prompt("planner/protocol.md")
    assert "已写入" in od and "一句话摘要" in od, "回复纪律表述源丢失"
    assert "回复纪律见平台协议" in _IRON_RULES_DOC_BODY
    assert "逐卡罗列" not in _IRON_RULES_DOC_BODY, "铁律模板复述回复纪律回潮"

    header = load_prompt("shared/iron_rules_header.md")
    assert _NEW_PRIORITY in header, "优先级链措辞与唯一源（iron_rules_header）不一致"
    assert "用户最新指令 > 本文档 + 制片规格 > Skill/系统默认" in header, \
        "裁决链措辞未对齐唯一源"


def test_b3_agent_loop_templates_wired():
    """agent_loop 运行时文案走 feedback.md 分节（分节在场即接线有效；
    代码内置兜底允许保留但不得作为唯一来源）。"""
    src = (ROOT / "src/video_agent/core/agent_loop.py").read_text(encoding="utf-8")
    for anchor in ("STEP_FEEDBACK", "EMPTY_RESPONSE_FALLBACK",
                   "STEP_ASSISTANT_PLACEHOLDER"):
        assert anchor in src, f"agent_loop 未接线分节: {anchor}"
    # 工具轮 assistant 占位经外置分节读取（load_prompt_section），
    # 不再内联写死假陈述文案（消除双源，M-2 同口径）
    assert 'content or _asst_placeholder' in src, \
        "工具轮 assistant 占位应经外置分节变量拼接，而非内联写死"
