# -*- coding: utf-8 -*-
"""任务#2：正文语言声明探针回归。

产物提示词语言的唯一裁决源 = prompt_gates.resolve_prompt_language
（用户选择 > frontmatter language 声明 > 平台默认）；
scan_skills.language_claim_issues 拦截 Skill 正文再现声明性语言规则。配套钉死：
① 本次清理覆盖的全部句式命中（英文声明/中文声明/用途分配/键值式）；
② 清洗后的规范表述放行；
③ 格式与术语要求（英文双引号/英文标签/英文指令）、旁白语言创意约束、
   用户偏好征询不误伤。
任务#11 补钉：裸「为」字断定、「通常/默认/一般+语言词」、「均/一律」全称断定、
「英文正向视觉描述」类偏正句式的命中与放行反例；双源矛盾残留句（提示词通常英文）
改判为命中，征询式规范表述（遵循档案声明）放行。
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "scan_skills_lang_claim_probe", ROOT / "scripts" / "scan_skills.py")
scan_skills = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_skills)


def _lang_issues(body: str) -> list:
    return scan_skills.language_claim_issues(body)


def test_en_claims_flagged():
    """英文声明句式（历史形态）命中。"""
    assert _lang_issues("将提示词写成流畅、自然的英文描述，将这 6 条规则交织在一起。")
    assert _lang_issues("当用户使用中文输入时，prompt 仍须输出英文镜头语言。")
    assert _lang_issues("场景单图的提示词正文必须使用英文。")
    assert _lang_issues("场景单图的提示词正文必须为一段连贯的英文正向描述。")
    assert _lang_issues("提示词本体必须使用英文撰写。")


def test_zh_claims_flagged():
    """中文声明句式（历史形态）命中。"""
    assert _lang_issues("将提示词正文用中文书写（除制片规格明确要求英文的部分外）。")
    assert _lang_issues("提示词本体必须使用中文撰写。")
    assert _lang_issues("所有提示词均使用中文撰写。")
    assert _lang_issues("以正向英文描述将单图定义为无人、静止且完整的场景环境。")


def test_usage_split_and_kv_flagged():
    """语言用途分配与键值式声明命中。"""
    assert _lang_issues("中文仅用于字段标题与对用户说明。")
    assert _lang_issues("场景单图的英文正向提示词不写负面提示词。")
    assert _lang_issues("语言：中文")
    assert _lang_issues("语言: 英文")


def test_cleaned_phrasing_passes():
    """清洗后的规范表述放行（本次清理的落点句式）。"""
    assert not _lang_issues("将提示词写成流畅、自然的描述，将这 6 条规则交织在一起。")
    assert not _lang_issues("将这 6 条规则自然编织进描述中。")
    assert not _lang_issues("提示词须包含景别、运镜、光线与材质锚点，禁止匿名空镜与平铺直叙。")
    assert not _lang_issues("场景单图的提示词正文必须为一段连贯的正向描述。")
    assert not _lang_issues("场景单图的提示词正文不附带负面提示词。")


def test_format_and_term_requirements_not_flagged():
    """格式/术语类要求不误伤：语言词作对象名词，不是书写语言声明。"""
    assert not _lang_issues("提示词中需用英文双引号和中文括号将要呈现的字重叠括起。")
    assert not _lang_issues("在编写打斗镜头的运镜提示词时，必须使用以下特定英文标签及双语对照释义。")
    assert not _lang_issues("在描述动作提示词时，必须加入镜头慢速跟随或锁定的英文指令。")


def test_creative_and_preference_phrasing_not_flagged():
    """旁白语言创意约束与不矛盾的征询表述不误伤（不属提示词语言声明）。"""
    assert not _lang_issues("旁白语言英文锁定，禁中文旁白。")
    assert not _lang_issues("涉及对白台词、旁白等配音文本时，必须严格遵循 制片规格.md 所规定的输出语言。")
    assert not _lang_issues("使用连贯的自然语言描述场景内容（主体+行为+环境等）。")
    # 任务#11 修复后的征询式规范表述：保留征询交互、不与 frontmatter 矛盾，放行。
    assert not _lang_issues("输出语言偏好（征询用户；提示词语言遵循档案声明（英文），用户选择优先）")


# ---------- 任务#11：探针盲区补钉 ----------

def test_bare_wei_assertions_flagged():
    """裸「为」字断定命中（组3 放宽：主语 +（必须|须|均|一律）?为）。"""
    assert _lang_issues("提示词为英文。")
    assert _lang_issues("正文为中文。")
    assert _lang_issues("prompt 为英文。")
    assert _lang_issues("提示词必须为英文。")
    assert _lang_issues("提示词均为英文。")
    assert _lang_issues("提示词一律英文。")


def test_bare_wei_factual_descriptions_pass():
    """裸「为」放行反例：「分为/作为」类事实描述与非语言断定不误伤。"""
    assert not _lang_issues("正文分为中文、英文双语。")
    assert not _lang_issues("该产物作为中文示例收录于样例库。")
    assert not _lang_issues("场景单图的提示词正文必须为一段连贯的正向描述。")
    # 「分镜脚本」不在探针主语集内，其语言倾向不属提示词语言声明。
    assert not _lang_issues("分镜脚本通常中文。")
    # 「遵循档案声明」式引用裁决源，不是就地声明。
    assert not _lang_issues("提示词语言遵循档案声明（英文）。")
    assert not _lang_issues("提示词语言以用户选择为准。")
    assert not _lang_issues("提示词须包含景别、运镜、光线与材质锚点。")
    assert not _lang_issues("提示词为生成效果服务，不包含负面词汇。")
    # 「提示词环境」指工作环境而非产物（让步从句式事实描述，存量误伤修复）。
    assert not _lang_issues("即使规划思考和提示词环境为中文，也必须保证音频输出文本的语言契合预设。")


def test_usual_default_claims_flagged():
    """「通常/默认/一般 + 语言词」弱倾向断定命中（任务#11 新增组）。"""
    assert _lang_issues("提示词通常英文，但中文同样可行")
    assert _lang_issues("提示词一般为中文。")
    assert _lang_issues("正文默认英文。")
    # 双源矛盾残留句（与 frontmatter language.prompt: en 冲突）必须命中。
    assert _lang_issues("输出语言偏好（分镜脚本通常中文；提示词通常英文，但中文同样可行）")


def test_universal_quantifier_claims_flagged():
    """「均/一律/全部/统一/始终 + 语言词」全称断定命中（任务#11 新增组）。"""
    assert _lang_issues("提示词一律英文。")
    assert _lang_issues("提示词统一为英文。")
    assert _lang_issues("提示词始终中文。")


def test_language_modifying_product_relaxed_flagged():
    """偏正句式放宽命中：「英文正向视觉描述」（组5 补「视觉/的」间隙）。"""
    assert _lang_issues("以英文正向视觉描述定义镜头画面。")
    assert _lang_issues("英文的提示词需附带镜头号。")
    assert _lang_issues("场景单图的英文正向视觉描述不写负面词。")


def test_language_modifying_product_relaxed_pass():
    """偏正放宽的放行反例：「自然语言描述」等非语言修饰不误伤。"""
    assert not _lang_issues("用连贯的自然语言描述画面内容。")
    assert not _lang_issues("用中文自然语言描述画面内容。")
    assert not _lang_issues("将用户的视觉描述转交生成通道。")
