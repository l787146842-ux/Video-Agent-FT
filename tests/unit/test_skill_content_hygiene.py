"""整改批 1.2：优先级宣称门禁词序无关化回归。

scan_skills._PRIORITY_CLAIM_RE 从「最高优先级|第一优先级」单边写法
扩为直连形态双向拦截；配套钉死：
① 正序/倒序宣称均命中；
② 带间隔的领域语句（如「参考图优先级为最高级别」）不误伤；
③ 「强制基线」式正向表述放行（清洗后的规范措辞）。
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "scan_skills_hygiene_probe", ROOT / "scripts" / "scan_skills.py")
scan_skills = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_skills)


def _priority_issues(body: str) -> list:
    return [i for i in scan_skills.content_hygiene_issues(body) if "优先级宣称" in i]


def test_forward_order_claim_flagged():
    """正序写法（历史形态）命中。"""
    assert _priority_issues("本规则最高优先级，适用于所有提示词。")
    assert _priority_issues("第一优先级：先定规格再写提示词。")


def test_inverted_order_claim_flagged():
    """倒序写法（整改批 1.2 新拦截面：存量 8 处 skill 的历史形态）。"""
    assert _priority_issues("优先级最高、适用于所有prompt编写情况。")
    assert _priority_issues("优先级第一，覆盖全部镜头提示词。")


def test_spaced_domain_statement_not_flagged():
    """带间隔的领域语句不误伤（参考图 vs 剧本的优先级描述，非平台层级宣称）。"""
    assert not _priority_issues("参考图优先级为最高级别，仅在剧本明确描述范围内让步。")


def test_baseline_phrasing_passes():
    """清洗后的「强制基线」式正向表述放行。"""
    assert not _priority_issues("强制基线、适用于所有prompt编写情况。")
