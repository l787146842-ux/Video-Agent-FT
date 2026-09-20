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
    assert "逐条细节" in clause and "故事板元素" in clause, \
        "缺判据③：只影响某镜头/某角色的逐条细节归故事板"
    assert "未确认" in clause and "待定" in clause, \
        "缺判据④：未确认的创作选择不得写成既定规格"


def test_spec_clause_carries_narrative_direction():
    """判据②的举例含「角色方向」——对齐 flova 规格文档的实际字段名。"""
    assert "角色方向" in _spec_clause(), \
        "判据②缺「角色方向」举例（flova 规格文档字段名，实体细节落盘的直接证据）"


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
