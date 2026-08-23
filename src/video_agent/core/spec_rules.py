"""项目「执行铁律」独立文档。

铁律原为规格文档末尾的附录章节，现拆为独立的「执行铁律.md」放进项目文档
（用户要求）：首次写入规格文档或每轮对话开始时由系统自动创建（幂等），
用户在文档面板可直接编辑、保存即生效；闸机按文档中的声明决定是否放行。
老项目兼容：规格文档里仍带旧铁律章节时，ensure 时自动迁移进独立文档
（保留用户改过的内容并从规格文档中移除该章节）。
执行优先级：用户最新指令 > 铁律文档 + 制片规格 > Skill/系统默认。
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

from src.video_agent.utils import gen_id

IRON_RULES_HEADING = "执行铁律"
IRON_RULES_DOC_NAME = "执行铁律.md"
ELEMENT_IMAGE_PREREQ_ON = "元素概念图前置：开启（当前生效）"
ELEMENT_IMAGE_PREREQ_OFF = "元素概念图前置：已由用户跳过（当前生效）"

# 状态行必须出现在行首（说明文字里的引号示例不算），避免误判
_OFF_RE = re.compile(r"(?m)^\s*(?:-\s*)?元素概念图前置：已由用户跳过")
_ON_RE = re.compile(r"(?m)^\s*(?:-\s*)?元素概念图前置：开启")
# 老项目规格文档内的铁律章节：从标题到下一个二级标题（或文末），整段迁移
_IRON_SECTION_RE = re.compile(r"##\s*执行铁律[^\n]*\n.*?(?=\n##\s|\Z)", re.S)
# 优先级文案升级（用户要求：制片规格与铁律文档同级）：仅精确替换旧措辞，
# 用户改过其它内容不受影响。措辞唯一源 = prompts/shared/iron_rules_header.md
#（F-2 优先级链统一：「用户最新指令」对齐模型可见文档）
_OLD_PRIORITIES = (
    "用户指令 > 本文档 > Skill/系统默认",
    "用户指令 > 本文档 + 制片规格 > Skill/系统默认",
)
_NEW_PRIORITY = "用户最新指令 > 本文档 + 制片规格 > Skill/系统默认"
#删除「不得拦截/强制暂停」半句（暂停语义唯一源=Skill 文本，此句与
# Skill 暂停条款打架只喂推理模型仲裁开销，且平台暂停由闸机代码驱动不受其影响）。
# 容忍旧文档里的换行/空白差异；用户改过其它内容不受影响
_NO_BLOCK_RE = re.compile(r"；\s*系统不得拦截用户要求的操作，\s*也不得强制暂停等待确认。")

# （用户裁决）：铁律第 4/5 条（提示词质量/产出形态）归 Skill 章节
# 唯一表述——存量项目铁律里的默认第 4/5 条升级迁移时剥离（保留用户自加的第 6+ 条）
_IRON_CLAUSE_45_RE = re.compile(
    r"(?m)^[ \t]*4\.[ \t]*提示词质量：[\s\S]*?^[ \t]*5\.[ \t]*产出形态：[\s\S]*?(?=^[ \t]*\d+\.[ \t]|\Z)")
# F-2 回复精简双源合并：模型可见表述归 prompts/shared/output_discipline.md 条目 1，
# 铁律第 3 条收敛为「回复纪律见平台协议」指针；存量文档同口径升级
_IRON_CLAUSE_3_RE = re.compile(
    r"(?m)^[ \t]*3\.[ \t]*回复精简[：:]?[\s\S]*?(?=^[ \t]*\d+\.[ \t]|\Z)")
# 铁律自动升级守卫（三维审查建议项）：第 3 条替换仅当正文与平台下发的
# 默认模板一致时才执行（去空白归一后比对）；标题匹配但正文已被用户
# 定制则跳过替换、用户措辞原样保留（留痕 = 日志登记）。
_CLAUSE_3_DEFAULT_BODIES = frozenset({
    "3.回复精简。",
    "3.回复精简：写入草稿的提示词正文只允许一句话汇总。",
})
_CLAUSE_3_POINTER = "3. 回复纪律见平台协议。\n"


def _upgrade_clause_3(body: str) -> str:
    """第 3 条守卫式升级：默认模板才替换为平台协议指针，定制正文跳过留痕。"""
    m = _IRON_CLAUSE_3_RE.search(body)
    if not m:
        return body
    normalized = re.sub(r"\s+", "", m.group(0))
    if normalized not in _CLAUSE_3_DEFAULT_BODIES:
        logger.info("[spec_rules] 铁律第 3 条正文已被用户定制，跳过自动升级"
                    "（保留用户措辞）：{}", normalized[:60])
        return body
    return _IRON_CLAUSE_3_RE.sub(_CLAUSE_3_POINTER, body)

_IRON_RULES_DOC_BODY = f"""# {IRON_RULES_HEADING}（系统约定，按优先级执行：{_NEW_PRIORITY}）

1. 执行优先：用户说什么就做什么。用户指令与本文档/制片规格/Skill 流程冲突时，先照常执行，
   再在回复末尾给出警告。
2. 拆解覆盖完整（系统机器验收）。
3. 回复纪律见平台协议。
"""


def find_iron_rules_doc(raw_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """定位项目里的铁律独立文档（名称含「执行铁律」即命中）。"""
    for d in raw_state.get("documents") or []:
        if isinstance(d, dict) and IRON_RULES_HEADING in str(d.get("name") or ""):
            return d
    return None


def find_spec_doc(raw_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """定位项目里的规格文档（名称模糊匹配，正文非空才算）。"""
    from src.video_agent.core.prompt_gates import is_spec_doc_name

    for d in raw_state.get("documents") or []:
        if not isinstance(d, dict):
            continue
        if not str(d.get("content") or "").strip():
            continue
        if is_spec_doc_name(d.get("name") or ""):
            return d
    return None


def ensure_iron_rules_doc(raw_state: Dict[str, Any]) -> bool:
    """幂等确保「执行铁律.md」独立文档存在；返回状态是否变化。

    - 不存在则创建（默认条款）；
    - 老项目规格文档里仍带铁律章节的：整段迁入独立文档（保留用户编辑），
      并从规格文档中移除该章节；迁移出的「已由用户跳过」状态一并同步。
    """
    docs = raw_state.get("documents")
    if docs is None:
        docs = []
        raw_state["documents"] = docs
    iron = find_iron_rules_doc(raw_state)
    changed = False
    migrated = ""
    # 1) 老项目迁移：规格文档内的铁律章节剥离出来（用户改过的内容原样保留）
    spec = find_spec_doc(raw_state)
    if spec:
        content = str(spec.get("content") or "")
        m = _IRON_SECTION_RE.search(content)
        if m:
            migrated = m.group(0).strip()
            spec["content"] = (content[:m.start()] + content[m.end():]).strip() + "\n"
            changed = True
    if iron is None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = migrated or _IRON_RULES_DOC_BODY.strip()
        # 老项目迁移来的正文同步升级：优先级措辞（含制片规格同级）
        # + 删「不得拦截/强制暂停」半句
        # + ：规格文档迁入的旧章节若带默认第 4/5 条同样剥离；
        # 第 3 条回复精简收敛为平台协议指针（F-2）
        for old in _OLD_PRIORITIES:
            body = body.replace(old, _NEW_PRIORITY)
        body = _NO_BLOCK_RE.sub("。", body)
        body = _IRON_CLAUSE_45_RE.sub("", body)
        body = _upgrade_clause_3(body).rstrip()
        docs.insert(0, {
            "id": gen_id("doc"),
            "name": IRON_RULES_DOC_NAME,
            "content": body + "\n",
            "created_at": now,
            "updated_at": now,
        })
        changed = True
    elif migrated:
        # 独立文档已存在且规格文档里还有旧章节：章节已从规格剥离；
        # 若旧章节里用户已声明「跳过元素概念图前置」，把状态同步进独立文档
        iron_content = str(iron.get("content") or "")
        if _OFF_RE.search(migrated) and not _OFF_RE.search(iron_content):
            if _ON_RE.search(iron_content):
                iron["content"] = _ON_RE.sub(
                    f"- {ELEMENT_IMAGE_PREREQ_OFF}", iron_content, count=1,
                )
            else:
                iron["content"] = iron_content.rstrip() + f"\n- {ELEMENT_IMAGE_PREREQ_OFF}\n"
            changed = True
    # 老项目措辞升级（精确应用，不动用户其它编辑）：
    # ① 优先级文案（含制片规格同级）；② 删「不得拦截/强制暂停」半句；
    # ③ ：剥离默认第 4/5 条（产出规范归 Skill 章节唯一表述）；
    # ④ 第 3 条回复精简收敛为平台协议指针（F-2 双源合并）
    if iron is not None:
        content = str(iron.get("content") or "")
        upgraded = content
        for old in _OLD_PRIORITIES:
            upgraded = upgraded.replace(old, _NEW_PRIORITY)
        upgraded = _NO_BLOCK_RE.sub("。", upgraded)
        # 第 2 条措辞迁移（自检→系统机器验收， 后验收已由代码承担）
        upgraded = upgraded.replace("（自检核对）", "（系统机器验收）")
        if _IRON_CLAUSE_45_RE.search(upgraded):
            upgraded = _IRON_CLAUSE_45_RE.sub("", upgraded).rstrip() + "\n"
        upgraded = _upgrade_clause_3(upgraded)
        if upgraded != content:
            iron["content"] = upgraded
            changed = True
    return changed


def spec_element_image_override(raw_state: Dict[str, Any]) -> bool:
    """铁律是否声明「元素概念图前置已由用户跳过」（优先读独立铁律文档，
    老项目未迁移时回落规格文档内嵌章节）。"""
    doc = find_iron_rules_doc(raw_state) or find_spec_doc(raw_state)
    if not doc:
        return False
    return bool(_OFF_RE.search(str(doc.get("content") or "")))


def apply_element_image_override(raw_state: Dict[str, Any]) -> bool:
    """把铁律中「元素概念图前置」改为「已由用户跳过」（幂等），返回是否发生修改。"""
    doc = find_iron_rules_doc(raw_state) or find_spec_doc(raw_state)
    if not doc:
        return False
    content = str(doc.get("content") or "")
    if _OFF_RE.search(content):
        return False
    if _ON_RE.search(content):
        content = _ON_RE.sub(f"- {ELEMENT_IMAGE_PREREQ_OFF}", content, count=1)
    else:
        # 标准状态行被用户改掉了：追加一行声明，保证闸机可读
        content = content.rstrip() + f"\n- {ELEMENT_IMAGE_PREREQ_OFF}\n"
    doc["content"] = content
    return True
