"""五轮 S7：指令归位迁移回归（#4/#5，D1 改判；Rule 6 快照锁语义）。

产出形态条款（skill_runtime 原第 8 条）与提示词质量铁律（protocol
原质量块）迁至《执行铁律》模板（层 4 唯一表述源）；原平台提示词位置不得复述（P1）。
顺带清偿 D8（体量相称条款入模板，老项目铁律已删重建）。
"""
from pathlib import Path

from src.video_agent.core.spec_rules import _IRON_RULES_DOC_BODY
from src.video_agent.utils.prompts import load_prompt, load_prompt_section

ROOT = Path(__file__).resolve().parents[2]


# ---------- 迁入端：铁律模板只留契约条款（0817 B18 用户裁决：原第 4/5 条
# 提示词质量/产出形态归 Skill 章节唯一表述，铁律不再承载产出规范） ----------

def test_s7_iron_rules_template_carries_migrated_clauses():
    body = _IRON_RULES_DOC_BODY
    # 0817 B18：第 4/5 条已废除
    assert "提示词质量" not in body
    assert "产出形态" not in body
    assert "摄像机→主体→空间→音频" not in body
    # 契约条款保留；批 A3（指令收拢批）：第 1 条「执行优先」与头部同义
    # 复述已删，冲突与缺信息处置唯一表述源 = iron_rules_header.md
    assert "拆解覆盖完整" in body
    assert "见平台注入的《执行铁律》头部声明" in body
    assert "执行优先" not in body
    assert "回复精简" not in body
    # C6 基线对齐：粒度裁量归模型+Skill，铁律刻意不承载粒度细则
    assert "宁缺毋滥" not in body


def test_s7_iron_rules_ensure_creates_new_template():
    """ensure 幂等创建的新文档即新模板（不再含已废除的第 4/5 条）"""
    from src.video_agent.core.spec_rules import ensure_iron_rules_doc, find_iron_rules_doc

    raw = {"documents": []}
    assert ensure_iron_rules_doc(raw) is True
    doc = find_iron_rules_doc(raw)
    assert doc is not None
    assert "产出形态" not in doc["content"]
    assert "提示词质量" not in doc["content"]
    # 幂等：二次调用不再变更
    assert ensure_iron_rules_doc(raw) is False


# ---------- 迁出端：平台提示词不得复述（P1 单一表述源） ----------

def test_s7_skill_runtime_no_output_form_clause():
    sd = load_prompt_section("planner/skill_runtime.md", "DISCIPLINE")
    assert sd
    # 原第 8 条产出形态已迁走（不得残留实质条款；留迁移指引注释可以）
    assert "摄像机→主体→空间→音频" not in sd
    assert "中文叙事式多节拍" not in sd
    # 标题客观化：不再自称「最高优先级」（与冲突裁决链冲突的措辞）
    assert "最高优先级" not in sd
    # 流程纪律其余条款保留（快照锁语义：暂停/分批/小步推进；
    # audit-0819d：暂停正名钉 workflow_pause，request_confirmation 别名已删。
    # 2026-09-12 治理批：纪律2/4/6 退役重编号，「不超前承诺」随纪律6 迁出，
    # 选项语义唯一家 = workflow_pause options 参数描述。
    # 同日规格收集退役批（2222 诊断后用户裁决）：原纪律3「规格收集交互
    # 一次性分组收集」退役——向导卡片契约唯一家 = workflow_pause options
    # 参数描述（group/分页/一次性发回），纪律 4-7 重编号为 3-6）
    for kept in ("阶段逐段执行", "workflow_pause", "分批次确认",
                 "状态对账", "小步推进"):
        assert kept in sd, f"流程纪律条款丢失: {kept}"
    for retired in ("交付自检", "元素图像就绪闸门", "何时停（唯一判定）",
                    "机械附挂", "一次性分组收集"):
        assert retired not in sd, f"流程纪律退役条款残留: {retired}"


def test_s7_protocol_no_quality_block():
    ir = (ROOT / "prompts/planner/protocol.md").read_text(encoding="utf-8")
    # 质量铁律实质条款已迁走（迁移指引注释可含原条款名，实质内容不得复述）
    assert "6 大核心规则" not in ir
    assert "千篇一律的开头句式" not in ir
    assert "每张卡按画面内容个性化撰写" not in ir
    # 其余条款保留（渐进式披露）
    for kept in ("渐进式披露",):
        assert kept in ir, f"protocol 条款丢失: {kept}"
    # 0817 B25：产出/流程规范已从平台层删除（归 Skill 章节/代码闸）
    for gone in ("关键元素独立分组铁律", "阶段暂停铁律", "分镜视频提示词时长规则"):
        assert gone not in ir, f"平台层不得复述产出规范: {gone}"


# ---------- 台账一致性：D8 归位裁决 ----------

def test_s7_d8_attribution():
    """D8（老项目铁律缺体量条款）按 C6 基线归位：粒度裁量归模型+Skill，
    铁律刻意不承载粒度细则；存量项目铁律已删重建（2026-08-16 用户裁决执行），
    重建后与新建项目同模板，D8 的「老新不一致」消除。"""
    assert "宁缺毋滥" not in _IRON_RULES_DOC_BODY
    assert "拆解覆盖完整" in _IRON_RULES_DOC_BODY


# ---------- 铁律自动升级守卫（三维审查建议项）：第 3 条替换仅当
# 正文与默认模板一致；标题匹配但正文已定制则跳过留痕 ----------

def test_clause_3_upgrade_guard_default_template_replaced():
    """第 3 条默认模板正文 → 照常升级为平台协议指针（存量口径不变）。"""
    from src.video_agent.core.spec_rules import IRON_RULES_DOC_NAME, ensure_iron_rules_doc

    old = ("# 执行铁律（系统约定）\n\n"
           "1. 执行优先：用户说什么就做什么。\n"
           "2. 拆解覆盖完整（自检核对）。\n"
           "3. 回复精简：写入草稿的提示词正文只允许一句话汇总。\n")
    raw = {"documents": [{"id": "d1", "name": IRON_RULES_DOC_NAME, "content": old}]}
    assert ensure_iron_rules_doc(raw) is True
    content = raw["documents"][0]["content"]
    assert "回复纪律见平台协议" in content and "回复精简" not in content


def test_clause_3_upgrade_guard_customized_body_preserved():
    """标题匹配但正文已被用户定制 → 跳过替换，用户措辞逐字保留。

    2026-09-26 11111 取证批（R9）：夹具里的「（系统机器验收）」现属第 1 条
    口径漂移点（收敛为自查口径）⇒ `ensure_iron_rules_doc` 返回 True 属预期；
    本用例的**核心不变式**仍是「用户定制的第 3 条逐字保留、不被平台改写」。
    """
    from src.video_agent.core.spec_rules import IRON_RULES_DOC_NAME, ensure_iron_rules_doc

    custom = "3. 回复精简：回复一律先给结论再给依据，且不超过两百字。\n"
    old = ("# 执行铁律（系统约定）\n\n"
           "1. 执行优先：用户说什么就做什么。\n"
           "2. 拆解覆盖完整（系统机器验收）。\n" + custom)
    raw = {"documents": [{"id": "d1", "name": IRON_RULES_DOC_NAME, "content": old}]}
    assert ensure_iron_rules_doc(raw) is True  # 第 1 条口径漂移 → 升级
    content = raw["documents"][0]["content"]
    assert custom in content, "用户定制的第 3 条必须原样保留"
    assert "回复纪律见平台协议" not in content
    # R9：旧口径收敛为现行自查口径
    assert "系统机器验收" not in content
