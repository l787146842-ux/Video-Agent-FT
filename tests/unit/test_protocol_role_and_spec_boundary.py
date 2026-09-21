# -*- coding: utf-8 -*-
"""主代理角色定义与规格文档边界契约单测（2026-09-21 批1，事故 2222/Q1+Q4）。

背景（2222 实跑取证）：主代理抢读剧本、把 8 角色/3 场景/道具全塞进规格文档、
给子代理写超长任务书。根因之一 = `protocol.md:1` 的自我定位停留在
「专业的编剧 + 分镜师 + 视觉总监」（2026-09-16 写入），而「主代理纯编排」裁决
是 2026-09-19——**那一批改了 subagent.py/planner.py/测试，没有改 protocol.md**。
protocol 是 system 段第 1 句（order 10，无条件注入），位置最靠前、权重最重，
`skill_runtime.md` 的「纯编排」只在选中 Skill 时才注入 → 模型同时收到两句
互相打架的自我定位，行动上服从了更靠前的那句（它做的每件事都符合「编剧」）。

本文件钉死批1 的两处改动，防回潮。
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = PROJECT_ROOT / "prompts" / "planner" / "protocol.md"


def _protocol_text() -> str:
    return PROTOCOL.read_text(encoding="utf-8")


def _spec_clause() -> str:
    """规格边界条目（唯一源 = protocol.md「Skill 与工具」段的末条）。"""
    for line in _protocol_text().splitlines():
        if line.startswith("- 规格文档"):
            return line
    raise AssertionError("protocol.md 未找到规格边界条目（规格文档…）")


# ---------- ① 角色定义（事故 2222/Q1） ----------

def test_role_line_drops_creator_identity():
    """首句不得再自称编剧/分镜师/视觉总监——这三个身份在推模型「亲自创作」。

    2222 实证：它抢读剧本（「编剧当然要读剧本」）、把实体细节当专业产出写进
    规格、给子代理写超长任务书（「分镜师在指导创作而非派活」）。
    """
    first = _protocol_text().splitlines()[0]
    for banned in ("编剧", "分镜师", "视觉总监"):
        assert banned not in first, (
            f"protocol.md 首句回潮成创作身份「{banned}」——与 2026-09-19 "
            f"主代理纯编排裁决矛盾，是 2222/Q1 的病根")


def test_role_line_declares_dispatch_position():
    """首句改为调度层定位（对齐 flova：主代理是调度层，不是创作者）。"""
    first = _protocol_text().splitlines()[0]
    assert "制片调度" in first, "protocol.md 首句缺调度层定位（制片调度）"
    assert "不亲做" in first, "首句未声明「专业创作由执行环节完成、你不亲做」"


def test_role_line_keeps_action_channel_sentence():
    """防误删：动作通道唯一 = FC 这句与角色定义同行，改角色定义不得捎带删掉。"""
    first = _protocol_text().splitlines()[0]
    assert "Tool 调用" in first and "Function Calling" in first, \
        "动作通道唯一 = Tool 调用（FC）契约丢失"


# ---------- ② 规格文档边界（事故 2222/Q4） ----------

def test_spec_clause_has_four_write_criteria():
    """四条写入判据齐备（flova 写入原则，用户 #7 明确要求本项目采纳）。"""
    clause = _spec_clause()
    assert "已由用户确认" in clause, "缺判据①：已由用户确认的全局一致性决策"
    assert "剧本分析得到" in clause and "全局且稳定" in clause, \
        "缺判据②：剧本分析得到、属于全局且稳定的制作约束"
    assert "故事板元素" in clause and "不写规格" in clause, \
        "缺判据③：清单/逐条明细归故事板元素"
    assert "未确认" in clause and "待定" in clause, \
        "缺判据④：未确认的创作选择不得写成既定规格"


def test_spec_clause_carries_narrative_direction():
    """判据②的举例含「角色方向」——对齐 flova 规格文档的实际字段名。"""
    assert "角色方向" in _spec_clause(), \
        "判据②缺「角色方向」举例（flova 规格文档字段名，实体细节落盘的直接证据）"


def test_spec_clause_criterion_two_is_policy_level():
    """判据②举例收窄到**方针级**（2026-09-21 批D，事故 5555/Q7）。

    旧举例含「叙事驱动、核心视觉母题」——5555 实证模型据此把整个分析叙事
    搬进规格（「叙事结构」整节：3 场次逐行 + 8 角色逐名 + 道具 8.5×5.2cm +
    25–31 镜，716 字 vs flova 460 字）。收窄为方针级表述后，判据②只说
    "写成方针级一两句"，不再给出会被误读成"章节清单"的词。
    """
    clause = _spec_clause()
    assert "方针级" in clause, "判据②缺「方针级」限定（防回潮成实体明细入口）"
    for leak in ("核心视觉母题", "叙事结构"):
        assert leak not in clause, (
            f"判据②回潮成会被读成实体清单的举例「{leak}」——5555/Q7 已收窄")


def test_spec_clause_criterion_three_names_lists():
    """判据③必须**点名清单类**（2026-09-21 批D，事故 5555/Q7）。

    旧措辞只有「逐条细节」——模型不认为「8 个角色**名单**」是"逐条细节"，
    它读成"范围"，于是整节写进规格。点名场次/角色/道具/镜头数后才无歧义。
    """
    clause = _spec_clause()
    for item in ("场次清单", "角色名单", "道具清单", "镜头数预估"):
        assert item in clause, f"判据③未点名清单类「{item}」（5555/Q7 直接病根）"


def test_spec_clause_has_no_fixed_dimension_ceiling():
    """规格维度不设固定条数（防「只承载」把 Skill 的地板读成天花板）。

    Skill 说「至少写这四项」，旧 protocol 用「只承载」读成「只准写这四项」，
    恰好堵死了扩展——这正是 2222 把实体细节塞进规格的推力之一。
    """
    clause = _spec_clause()
    assert "不设固定条数" in clause, "缺「维度不设固定条数」（防回潮成封闭列举）"
    assert "只承载" not in clause, \
        "回潮成「只承载」——把 Skill 的四项地板读成天花板（用户 #9）"


def test_spec_clause_does_not_restate_skill_four_items():
    """平台不复述 Skill 的四项要求（P1：Skill 的产出规范归 Skill）。

    四项（画幅比例/目标时长/影像风格基调/输出语言）唯一源 = 所选 Skill 声明；
    protocol 只写「最小集由所选 Skill 声明」。
    """
    clause = _spec_clause()
    assert "最小集由所选 Skill 声明" in clause, \
        "未声明四项最小集的归属（应指回 Skill）"
    for skill_item in ("画幅比例", "目标时长", "影像风格基调", "输出语言"):
        assert skill_item not in clause, (
            f"平台复述了 Skill 的四项要求「{skill_item}」——P1 违规（用户 #9）")


def test_spec_clause_drops_injected_global_settings_prose():
    """渠道/分辨率/分镜上限不进散文（用户 #11：系统已写死注入）。

    `prompts/shared/global_settings.md` 已无条件注入实际值，且
    `prompt_builder.py` 注释明写「渠道唯一事实源为顶部全局设置」——protocol
    再复述一遍是第二份事实源、零行为价值。
    """
    clause = _spec_clause()
    for injected in ("渠道", "分辨率", "分镜上限"):
        assert injected not in clause, (
            f"规格条目复述了系统注入项「{injected}」——第二份事实源（用户 #11）")


def test_spec_clause_requires_persisting_confirmed_entities():
    """已确认的实体细节**必须落盘**（子代理看不到父对话）。

    决定性机制事实：`planner.py` 子代理 `history=[]`，拿不到父对话历史。
    2222 实证：关键元素子代理正是靠 `read_project_doc(制片规格.md)` 拿到
    角色设定（剧本里只有名字、没有外貌）。故「留在对话中」会让下游不可见。
    """
    clause = _spec_clause()
    assert "必须落盘" in clause, "缺「已确认的角色/场景设定必须落盘」（用户 #12）"
    assert "子代理不继承本次对话" in clause, (
        "缺机制事实说明——不给原因，模型会把信息丢在只有自己能看见的地方")
    # 上一版方案曾写「无需落盘、留在对话中即可」，该表述会打断下游，直接否决
    for wrong in ("留在对话中即可", "无需落盘", "不必落盘"):
        assert wrong not in clause, f"回潮成错误表述「{wrong}」（用户 #12 已否决）"


def test_spec_clause_layers_persistence_by_granularity():
    """落盘分层：方针级进规格 / 逐条明细进故事板（对齐 flova 实际切分）。

    flova `规格文档.md` 有「角色方向」字段（一句话方针）、零逐人明细；
    05 flova 的叙事驱动点名角色但仍是方针级。2222 的错误不是"落盘"，
    而是把 8 人逐条明细写成了规格正文——粒度错，不是位置错。
    """
    clause = _spec_clause()
    assert "角色方向" in clause and "故事板元素" in clause, \
        "缺落盘分层（方针级 → 规格「角色方向」/ 逐条明细 → 故事板元素）"


# ---------- ③ 委派任务书契约（事故 2222/Q5 立，5555/Q5 由三段改两段） ----------

def _policy() -> str:
    from src.video_agent.core.subagent import subagent_policy
    return subagent_policy()


def test_task_brief_is_two_parts():
    """任务书两段式：①目标（执行所选 Skill 本章节）＋②只有子代理用得上、它读不到的东西。

    2026-09-21 批C（事故 5555/Q5）由三段改两段：**删「②下游用途」**。
    删除依据（5555 实跑取证）：子代理 `history=[]`、阶段章节已由
    `planner._launch_subagent` 全量注入——它**真的不需要**知道下游用途；
    而该段实测被用作复述章节内容的入口（任务书①把 `SKILL.md:16` 原文
    「提取角色、场景、关键道具，识别剧本类型」整句抄了一遍）。
    2026-09-21 批E（事故 4444/Q5）：段②判据口径由「尚未落入规格文档的新决定」
    改为「只有这个子代理用得上、而它自己读不到的东西」——旧口径相对
    **规格文档这一个载体**定义，导致规格尚未创建时按字面**必须**把语言偏好
    写进剧本分析任务书（剧本分析子代理用它不着）。
    """
    policy = _policy()
    assert "任务书只写两段" in policy, "缺任务书两段式契约"
    assert "一句目标" in policy, "缺第①段：一句目标"
    assert "用得上" in policy and "读不到" in policy, \
        "缺第②段新口径：只有这个子代理用得上、而它自己读不到的东西"
    # 用户 #6 已否决的「框太死」方向：不得回退成复述既有内容
    assert "子代理自己读得到" in policy, \
        "缺「子代理自己读得到」的正向读取授权认知（用户 #6）"


def test_task_brief_drops_stale_spec_relative_criterion():
    """反向钉：段②不得回潮成「尚未落入规格文档的新决定」（4444/Q5 直接病根）。

    旧口径把判据锚在**规格文档**上，与「子代理要不要」无关：4444 派
    script_analyze 时规格尚未创建，语言偏好按字面必须附上，模型只能照章办事
    （其思考原文「委派任务书里告诉子代理这个新决定」）。
    """
    policy = _policy()
    assert "尚未落入规格文档的新决定" not in policy, (
        "段②回潮成「尚未落入规格文档的新决定」——该口径相对规格文档定义，"
        "与子代理相关性无关（4444/Q5）")
    assert "没有就整段不写" in policy, (
        "缺「没有就整段不写」——该槽位若是必须存在的，模型只能写占位句填坑")


def test_task_brief_bans_placeholder_sentence():
    """段②禁止占位句（4444/Q6 实证）。

    模型自己决定过「只写①」（seq50 思考原文），最终仍写下
    「本阶段无新增未落盘决定。」——因为段② 是一个必须交代的槽位。
    """
    policy = _policy()
    assert "占位句" in policy, "缺「不要写占位句填坑」"


def test_task_brief_bans_restating_spec_params_and_downstream():
    """段①不得复述规格参数现值/源文档出处/章节自带的下游依赖（4444/Q6）。

    实跑取证（key_elements 任务书原文）：「制片规格已写入「制片规格.md」
    （16:9、约 4 分钟、电影级写实科幻冷调、中文台词+中文提示词、角色按原著
    气质写实设计），剧本为已上传的《三体简短版.md》」——括号内是规格内容
    第二份复述；同句还有「供后续镜头设计与设定图生成使用」= 批C 已删的
    「下游用途」换了位置回来（Skill 自己的依赖图仍在供料，批E 只能从
    判据侧收窄）。
    """
    policy = _policy()
    assert "规格参数的现值与源文档出处都不必转告" in policy, \
        "缺「不复述规格参数现值/源文档出处」"
    assert "下游依赖关系" in policy, "缺「不必交代章节自带的下游依赖关系」"


def test_task_brief_drops_downstream_use():
    """反向钉：任务书不再要求写「下游用途」（5555/Q5 用户确认删除）。

    旧三段式的第②段是**邀请复述的坑**：既然要写"谁会用、用来干什么"，
    模型自然会把章节里的产出清单再抄一遍。
    """
    policy = _policy()
    assert "下游用途" not in policy, (
        "回潮成三段式「下游用途」——5555/Q5 已删除（子代理不需要知道，"
        "且该段被用作复述章节内容的入口）")
    assert "任务书三段" not in policy, "回潮成三段式表述"


def test_task_brief_examples_do_not_leak_internal_terms():
    """反向钉：反例清单不得含系统内部机制词（4444/Q2① 直接病根）。

    批2/批C 为表达「不要复述什么」，在括注里列了四个内部机制词
    （范围几个角色/几个场景、字段怎么写、**要不要建卡**、交不交提示词）。
    4444 实证模型抓的正是其中之一：「章节里会说明**是否建卡**等」
    （conv-main seq25）——而 `建卡` 在 `data/skills/*/SKILL.md` **零命中**，
    说明该词是平台自己喂进去的，不是它从章节里读到的。
    改法：删举例、只留因果——不靠穷举反例表达「别复述」。
    """
    policy = _policy()
    for leak in ("建卡", "字段怎么写", "交不交提示词", "几个场景"):
        assert leak not in policy, (
            f"反例清单回潮内部机制词「{leak}」——平台词会被模型当成事实复述"
            f"（4444/Q2①）")


def test_task_brief_points_at_section_as_the_basis():
    """①段必须把「执行所选 Skill 的本阶段章节」写成执行依据（章节即规范）。

    这是删掉复述后的**代替品**：不再由父代理转述规范，而是明确指向
    已在子代理手里的章节全文（唯一表述源，P1）。
    """
    policy = _policy()
    assert "执行所选 Skill 的本阶段章节" in policy, \
        "缺「执行依据＝所选 Skill 的本阶段章节」"
    assert "不要复述章节内容" in policy, \
        "缺「不要复述章节内容」——不写这句，模型会继续把章节抄进任务书"


def test_task_brief_states_why_not_just_forbids():
    """含因果说明而不只是禁令（G3：不写一句话让模型配合机制）。

    旧表述是纯禁令：没说为什么，且模型当时**有充分理由写**——它以为自己在
    "专业指导"。5555 实证后果：任务书照抄章节原文 + 声明"已写入规格"后
    又把同样内容列一遍（第二份事实源）。
    """
    policy = _policy()
    assert "复述只会和章节打架" in policy, \
        "缺因果说明「你复述只会和章节打架」（防退化成纯禁令）"
    assert "章节里都已经写全" in policy, "缺范围/规范/交付物归章节的事实说明"


def test_task_brief_carries_spec_write_principle_reference():
    """规格写入原则随任务书下发（用户 #7：「任务书上要加上」）。

    引用式（指向协议四条判据），不复制正文——P1 单一事实源。
    """
    policy = _policy()
    assert "写规格文档时按协议的四条写入判据分档" in policy, \
        "缺制作设定写入原则的任务书侧下发（用户 #7 明确要求）"
    assert "未确认的不得写成既定规格" in policy, "缺未确认不得写成规格"


def test_task_field_description_matches_policy():
    """工具 schema 的 task 描述与策略段同向（不产生第二份契约）。

    工具描述只留可照抄的字段用法，两段式完整表述与"为什么"唯一源 = SUBAGENT_POLICY。
    2026-09-21 批E（事故 4444/Q5）同批改口径：描述不得再复述「尚未落入规格
    文档的新决定」（旧口径锚在规格文档上，见 test_task_brief_drops_stale_...）。
    """
    from src.video_agent.tools.document_tools import RunSubagentInput

    desc = RunSubagentInput.model_fields["task"].description
    assert "①一句目标" in desc, "task 字段描述未承载①段（与策略段不同向）"
    assert "下游用途" not in desc, "task 字段回潮成三段式（含下游用途）"
    assert "尚未落入规格文档的新决定" not in desc, \
        "task 字段回潮成旧口径「尚未落入规格文档的新决定」（4444/Q5）"
    assert "用得上" in desc and "读不到" in desc, "task 字段缺②段新口径"
    assert "执行所选 Skill 的本阶段章节" in desc, \
        "task 字段缺「执行依据＝所选 Skill 本章节」"
    assert "不用复述" in desc, "task 字段缺「既有内容不用复述」事实"


# ---------- ④ 规格落盘时机（事故 4444/Q2②，批E） ----------

def test_spec_clause_declares_when_to_write():
    """规格条目须声明**落盘时机**（4444/Q2②：规则留了时机空档）。

    4444 实证：模型逐条过了四条判据、结论全对，但在「规格文档还没建」上
    反复权衡（conv-main seq47/49/50）——因为旧条款只说「必须落盘…未落盘的
    细节对下游不可见」（一条带因果的硬职责），**未声明相对 Skill 规格阶段的
    时机**。模型自行解开（「但阶段2才写规格…我可以先记着」），属规则空档。
    """
    clause = _spec_clause()
    assert "落盘时机" in clause, "缺规格落盘时机声明（4444/Q2②）"
    assert "不必提前创建" in clause, \
        "缺「不必提前创建」——不写则模型会在更早阶段抢建规格文档"
    assert "到规格阶段一并写入" in clause, "缺时机落点（规格阶段一并写入）"


# ---------- ④ run_subagent.stage 枚举可见（事故 2222/Q3b，批3） ----------

def test_stage_description_lists_every_enum_value():
    """stage 描述必须含 PIPELINE_STAGE_KINDS 的**每一个**键（防改枚举忘改描述）。

    2222 实测：模型先填中文「剧本分析」被拒 → 改 script_analyze，花 3.5s +
    一次失败往返，且每个新会话都会重犯。根因不是模型不聪明，是描述让它猜
    （旧描述只写"由系统枚举"，等于"考完试才给答案"）。
    """
    from src.video_agent.core.subagent import PIPELINE_STAGE_KINDS
    from src.video_agent.tools.document_tools import RunSubagentInput

    desc = RunSubagentInput.model_fields["stage"].description
    for key in PIPELINE_STAGE_KINDS:
        assert key in desc, (
            f"stage 描述缺枚举值「{key}」——模型只能靠猜（2222/Q3b）")


def test_stage_description_carries_chinese_labels():
    """顺带给出中文标签：模型不用自己做英中转换（2222 猜错的正是中文名）。"""
    from src.video_agent.core.subagent import PIPELINE_STAGE_KINDS
    from src.video_agent.skill_runtime.registry import STAGE_LABELS
    from src.video_agent.tools.document_tools import RunSubagentInput

    desc = RunSubagentInput.model_fields["stage"].description
    for key in PIPELINE_STAGE_KINDS:
        label = STAGE_LABELS.get(key)
        assert label and label in desc, f"stage 描述缺中文标签「{label}」"


def test_stage_description_is_dynamic_not_hardcoded():
    """描述值唯一源 = 枚举表（改枚举即改描述，无第二份名单）。

    钉死实现方式：若有人把枚举抄成字面量，改 PIPELINE_STAGE_KINDS 后本测试
    仍会因缺键而失败——这正是想要的耦合方向。
    """
    from src.video_agent.tools.document_tools import _stage_hint

    hint = _stage_hint()
    assert "留空 = 通用委派" in hint, "缺「留空 = 通用委派」语义"
    assert "章节即产出规范" in hint, "缺章节注入事实说明"


def test_stage_fail_loud_validation_still_present():
    """批3 只加 description 引导，**不动** fail-loud 校验（两层都在）。

    2222 实测：非法值（中文「剧本分析」）被 fail-loud 拒收并列白名单——
    该行为必须保留，description 是引导不是唯一防线。
    """
    from src.video_agent.tools.document_tools import RunSubagentInput

    # stage 仍是宽松 str（不改成 Literal）：校验发生在运行时派发层，
    # 改动它会波及「未知 stage 回落通用形态、不阻断委派」的既有语义。
    assert RunSubagentInput.model_fields["stage"].annotation is str, \
        "stage 类型被改成闭集——会破坏「未知值回落通用、不阻断委派」语义"
    desc = RunSubagentInput.model_fields["stage"].description
    assert "可选值" in desc, "缺可选值列举"


