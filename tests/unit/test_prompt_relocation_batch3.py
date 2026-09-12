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
    # STEP_ASSISTANT_PLACEHOLDER 已随上下文与缓存优化计划批 C2 退役删除
    # （assistant 消息改带标准 tool_calls，content 为空合法，占位无消费点）
    for section in ("STEP_FEEDBACK", "EMPTY_RESPONSE_FALLBACK"):
        assert load_prompt_section("planner/feedback.md", section), \
            f"feedback.md 分节缺失: {section}"
    assert not load_prompt_section("planner/feedback.md", "STEP_ASSISTANT_PLACEHOLDER"), \
        "STEP_ASSISTANT_PLACEHOLDER 已随批 C2 退役，不应回潜"


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
    """暂停纪律唯一家 = workflow_pause 工具描述（P1 规则单家；
    2026-09-12 指令体量治理批：原 skill_runtime 纪律2/4 停机判定与收尾批
    合并条款迁入工具描述，protocol 暂停段同步删除。
    （同日 3333 事故批：description 改 dsh 式正面契约——回应三态条款
    随说明层减负退役，三态消费语义归平台 reducer 行为，不再模型可见。）"""
    from src.video_agent.tools.document_tools import WorkflowPauseTool

    wd = WorkflowPauseTool().description or ""
    assert "真正的停 = 调用本工具" in wd, "假停无效条款（工具描述）丢失"
    assert "先收尾后暂停" in wd, "收尾批合并条款（工具描述）丢失"
    assert "本轮立即结束" in wd, "问即停结束本轮条款（工具描述）丢失"
    sd = load_prompt_section("planner/skill_runtime.md", "DISCIPLINE")
    assert "何时停（唯一判定）" not in sd, "停机判定式已在纪律2 退役，不得回潮"
    ir = load_prompt("planner/protocol.md")
    assert "暂停请求用户确认" not in ir, "protocol 暂停段已迁出，不得回潮"


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
    ① 防虚报表述源唯一 = skill_runtime《Skill 流程纪律》第 4 条（含状态对账细节；
       2026-09-12 治理批纪律重编号：原第 7 条 → 第 4 条），
       protocol 只留一句引用式短述；
    ② 回复精简模型可见表述归 protocol 回复输出纪律（治理批压缩为三行契约，
       全文归属锚点 = 草稿卡/事件卡），铁律模板只留头部指针；
    ③ 优先级链三处措辞以 iron_rules_header 为唯一源对齐（治理批补充裁决：
       优先级链只在铁律文档出现，模型可见层不携带）。"""
    from src.video_agent.core.spec_rules import _IRON_RULES_DOC_BODY, _NEW_PRIORITY

    ir = load_prompt("planner/protocol.md")
    assert "《Skill 流程纪律》第 4 条" in ir, "防虚报引用式短述丢失"
    assert "动作通道唯一 = 工具调用，只在正文写不产生任何效果" not in ir, "防虚报双源回潮"
    sd = load_prompt_section("planner/skill_runtime.md", "DISCIPLINE")
    assert "状态对账" in sd, "防虚报表述源（第 4 条）丢失"

    od = load_prompt("planner/protocol.md")
    assert "归属草稿卡" in od and "事件卡" in od, "回复纪律表述源丢失"
    assert "见平台注入的《执行铁律》头部声明" in _IRON_RULES_DOC_BODY
    assert "回复纪律见平台协议" not in _IRON_RULES_DOC_BODY
    assert "逐卡罗列" not in _IRON_RULES_DOC_BODY, "铁律模板复述回复纪律回潮"

    header = load_prompt("shared/iron_rules_header.md")
    assert _NEW_PRIORITY in header, "优先级链措辞与唯一源（iron_rules_header）不一致"
    assert "用户最新指令 > 本文档 + 制片规格 > Skill/系统默认" in header, \
        "裁决链措辞未对齐唯一源"


def test_b3_agent_loop_templates_wired():
    """agent_loop 运行时文案走 feedback.md 分节（分节在场即接线有效；
    代码内置兜底允许保留但不得作为唯一来源）。
    （C2：STEP_ASSISTANT_PLACEHOLDER 随占位退役删除——assistant 消息改带
    标准 tool_calls；本测试同步改为退役防回潜断言）"""
    src = (ROOT / "src/video_agent/core/agent_loop.py").read_text(encoding="utf-8")
    for anchor in ("STEP_FEEDBACK", "EMPTY_RESPONSE_FALLBACK"):
        assert anchor in src, f"agent_loop 未接线分节: {anchor}"
    assert "STEP_ASSISTANT_PLACEHOLDER" not in src, \
        "STEP_ASSISTANT_PLACEHOLDER 已随批 C2 退役，agent_loop 不应有残留消费点"
