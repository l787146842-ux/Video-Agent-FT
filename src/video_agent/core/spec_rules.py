"""项目「执行铁律」独立文档。

铁律为独立的「执行铁律.md」放进项目文档：
首次写入规格文档或每轮对话开始时由系统自动创建（幂等），
用户在文档面板可直接编辑、保存即生效；闸机按文档中的声明决定是否放行。
老项目兼容：规格文档里仍带旧铁律章节时，ensure 时自动迁移进独立文档
（保留用户改过的内容并从规格文档中移除该章节）。
执行优先级链唯一表述源 = prompts/shared/iron_rules_header.md
（用户最新指令 > 铁律文档 + 制片规格 > Skill/系统默认）。
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

from src.video_agent.utils import gen_id

IRON_RULES_HEADING = "执行铁律"
IRON_RULES_DOC_NAME = "执行铁律.md"

# 老项目规格文档内的铁律章节：从标题到下一个二级标题（或文末），整段迁移
_IRON_SECTION_RE = re.compile(r"##\s*执行铁律[^\n]*\n.*?(?=\n##\s|\Z)", re.S)
# 优先级文案升级：仅精确替换旧措辞，
# 用户改过其它内容不受影响。措辞唯一源 = prompts/shared/iron_rules_header.md；
# 铁律文档内只留链本体 + 指向头部的指针（单源收敛：完整声明含硬闸
# 效力边界只在头部，_NEW_PRIORITY 保留链本体供快照锁与迁移替换同口径）
_OLD_PRIORITIES = (
    "用户指令 > 本文档 > Skill/系统默认",
    "用户指令 > 本文档 + 制片规格 > Skill/系统默认",
)
_NEW_PRIORITY = "用户最新指令 > 本文档 + 制片规格 > Skill/系统默认"
# 铁律文档内落盘口径 = 链本体 + 指向头部的指针（单源收敛：完整声明含
# 硬闸效力边界只在头部，快照锁只钉链本体与头部一致）
_NEW_PRIORITY_POINTER = _NEW_PRIORITY + "（优先级链完整声明与硬闸效力边界见平台注入的《执行铁律》头部）"
# 容忍旧文档里的换行/空白差异；用户改过其它内容不受影响
_NO_BLOCK_RE = re.compile(r"；\s*系统不得拦截用户要求的操作，\s*也不得强制暂停等待确认。")

# 铁律第 4/5 条（提示词质量/产出形态）归 Skill 章节
# 唯一表述——存量项目铁律里的默认第 4/5 条升级迁移时剥离（保留用户自加的第 6+ 条）
_IRON_CLAUSE_45_RE = re.compile(
    r"(?m)^[ \t]*4\.[ \t]*提示词质量：[\s\S]*?^[ \t]*5\.[ \t]*产出形态：[\s\S]*?(?=^[ \t]*\d+\.[ \t]|\Z)")
# 模型可见表述归 prompts/shared/output_discipline.md，
# 铁律第 3 条收敛为「回复纪律见平台协议」指针；存量文档同口径升级
_IRON_CLAUSE_3_RE = re.compile(
    r"(?m)^[ \t]*3\.[ \t]*回复精简[：:]?[\s\S]*?(?=^[ \t]*\d+\.[ \t]|\Z)")
# 铁律自动升级守卫：第 3 条替换仅当正文与平台下发的
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

_IRON_RULES_DOC_BODY = f"""# {IRON_RULES_HEADING}（系统约定，按优先级执行：{_NEW_PRIORITY_POINTER}）

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
      并从规格文档中移除该章节。
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
        # + 规格文档迁入的旧章节若带默认第 4/5 条同样剥离；
        # 第 3 条回复精简收敛为平台协议指针
        for old in _OLD_PRIORITIES:
            body = body.replace(old, _NEW_PRIORITY_POINTER)
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
    # 老项目措辞升级（精确应用，不动用户其它编辑）：
    # ① 优先级文案（含制片规格同级）；② 删「不得拦截/强制暂停」半句；
    # ③ 剥离默认第 4/5 条（产出规范归 Skill 章节唯一表述）；
    # ④ 第 3 条回复精简收敛为平台协议指针
    if iron is not None:
        content = str(iron.get("content") or "")
        upgraded = content
        for old in _OLD_PRIORITIES:
            upgraded = upgraded.replace(old, _NEW_PRIORITY_POINTER)
        upgraded = _NO_BLOCK_RE.sub("。", upgraded)
        # 第 2 条措辞迁移（自检→系统机器验收，验收已由代码承担）
        upgraded = upgraded.replace("（自检核对）", "（系统机器验收）")
        if _IRON_CLAUSE_45_RE.search(upgraded):
            upgraded = _IRON_CLAUSE_45_RE.sub("", upgraded).rstrip() + "\n"
        upgraded = _upgrade_clause_3(upgraded)
        if upgraded != content:
            iron["content"] = upgraded
            changed = True
    return changed
