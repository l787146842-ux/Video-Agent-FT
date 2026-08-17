"""五轮 S7：指令归位迁移回归（#4/#5，D1 改判；Rule 6 快照锁语义）。

产出形态条款（skill_discipline 原第 8 条）与提示词质量铁律（important_rules
原质量块）迁至《执行铁律》模板（层 4 唯一表述源）；原平台提示词位置不得复述（P1）。
顺带清偿 D8（体量相称条款入模板，老项目铁律已删重建）。
"""
from pathlib import Path

from src.video_agent.core.spec_rules import _IRON_RULES_DOC_BODY
from src.video_agent.utils.prompts import load_prompt

ROOT = Path(__file__).resolve().parents[2]


# ---------- 迁入端：铁律模板只留契约条款（0817 B18 用户裁决：原第 4/5 条
# 提示词质量/产出形态归 Skill 章节唯一表述，铁律不再承载产出规范） ----------

def test_s7_iron_rules_template_carries_migrated_clauses():
    body = _IRON_RULES_DOC_BODY
    # 0817 B18：第 4/5 条已废除
    assert "提示词质量" not in body
    assert "产出形态" not in body
    assert "摄像机→主体→空间→音频" not in body
    # 契约条款保留
    assert "执行优先" in body and "拆解覆盖完整" in body and "回复精简" in body
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

def test_s7_skill_discipline_no_output_form_clause():
    sd = load_prompt("planner/skill_discipline.md")
    assert sd
    # 原第 8 条产出形态已迁走（不得残留实质条款；留迁移指引注释可以）
    assert "摄像机→主体→空间→音频" not in sd
    assert "中文叙事式多节拍" not in sd
    # 标题客观化：不再自称「最高优先级」（与 13.3 裁决链冲突的措辞）
    assert "最高优先级" not in sd
    # 流程纪律其余条款保留（快照锁语义：暂停/分批/自检/规格收集/元素图闸）
    for kept in ("阶段逐段执行", "request_confirmation", "分批次确认",
                 "交付自检", "规格收集交互", "元素图像就绪闸门", "不超前承诺"):
        assert kept in sd, f"流程纪律条款丢失: {kept}"


def test_s7_important_rules_no_quality_block():
    ir = (ROOT / "prompts/shared/important_rules.md").read_text(encoding="utf-8")
    # 质量铁律实质条款已迁走（迁移指引注释可含原条款名，实质内容不得复述）
    assert "6 大核心规则" not in ir
    assert "千篇一律的开头句式" not in ir
    assert "每张卡按画面内容个性化撰写" not in ir
    # 其余条款保留（渐进式披露）
    for kept in ("渐进式披露",):
        assert kept in ir, f"important_rules 条款丢失: {kept}"
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
