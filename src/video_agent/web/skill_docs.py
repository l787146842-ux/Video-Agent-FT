"""
Skill 文档化存储层。

对标 FTDYB：Skill 不是代码里的一段提示词，而是用户可见、可编辑的 Markdown 文档，
存放在 data/skills/。渐进式披露：上下文只注入 Skill 目录（名称+摘要），
全文由模型调 read_skill 按需加载——"流程即数据"。

文档格式约定：
    # Skill 名称
    > 调用规则：一句话说明何时使用本 Skill
    ## 流程规划
    ……正文……
"""
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.utils.fileio import atomic_write_text
from src.video_agent.utils.paths import SKILL_DOCS_DIR

_SLUG_RE = re.compile(r"^[\w一-鿿-]{1,64}$")  # 允许中英文/数字/下划线/连字符

# 外来 Skill 常见工具名 → 本系统动作对照表（第三方平台工作流直译的 Skill
# 常引用本系统不存在的工具名，模型只能「近似映射」导致阶段纪律失真；
# 注入时检测到这些名称就自动追加对照说明，把映射从模型猜测变成显式指令）
FOREIGN_TOOL_MAP: Dict[str, str] = {
    "resource_prepare_and_analyze": "read_uploaded_doc（读取上传文档全文）",
    "multimodal_analyze_tool": "read_uploaded_doc + 直接分析总结",
    "text_editor": "document_write（写入/更新项目文档，文本模式 write_document）",
    "storyboard_designer": "storyboard_create_group / storyboard_add_draft / storyboard_patch_draft（故事板结构操作）",
    "write_media_prompt": "storyboard_patch_draft / update_draft 的 patch.prompt（写入草稿提示词）",
    "media_generator": "generate_image / generate_video（图片/视频生成，危险操作需用户明确指令）",
    "reply_to_user": "workflow_pause（Tool 模式）/ request_confirmation（文本模式）",
    "video_assembler": "本系统暂无最终剪辑工具：引导用户在画布中按分镜与时间轴组装导出",
}


def build_foreign_tool_note(content: str) -> str:
    """检测 Skill 正文中出现的外来工具名，返回映射对照说明块；无则返回空串。

    只匹配 FOREIGN_TOOL_MAP 已知的词汇表（不做开放式 snake_case 扫描，
    避免把 element_id/shot_id 这类字段名误判为工具）。
    """
    if not content:
        return ""
    found = [
        name for name in FOREIGN_TOOL_MAP
        if re.search(rf"\b{re.escape(name)}\b", content, re.IGNORECASE)
    ]
    if not found:
        return ""
    lines = [f"- {name} → {FOREIGN_TOOL_MAP[name]}" for name in found]
    return (
        "== 外来工具名映射（本文档引用了本系统不存在的工具名，必须按下表映射为本系统动作执行，"
        "不得假装调用不存在的工具）==\n" + "\n".join(lines)
        + "\n文中未在上表列出的其他英文工具名一律视为描述性文字，不得当作必须调用的工具。"
    )

# 版本历史：保存前把旧版备份到 .history/，每个 slug 保留最近 N 版
_HISTORY_DIR_NAME = ".history"
_HISTORY_MAX = 10

# ---------- Skill 章节分阶段解析（分段聚焦注入用） ----------
# 外来 Skill（如 flova 导出）原生就是「每个工具一节」的结构（<planner>/<write_the_prompt>…），
# 它们的运行时把各节分别注入对应阶段的子工具；本系统把全文一次性注入单一编排模型，
# 只能靠「识别当前阶段 → 重复强调对应章节」来逼近同等遵循度。
SECTION_TAG_STAGES: Dict[str, str] = {
    "planner": "planning",
    "resource_prepare_and_analyze": "planning",
    "multimodal_analyze_tool": "planning",
    "text_editor": "planning",
    "storyboard_designer": "storyboard",
    "write_media_prompt": "prompt_draft",
    "write_the_prompt": "prompt_draft",
    "media_generator": "generation",
    "video_assembler": "assembly",
    "reply_to_user": "",
}

# 本地改写版 Skill（标题式）的标题关键字 → 阶段兜底映射
_HEADING_STAGE_HINTS = [
    (("提示词写法", "提示词规范", "prompt 编写", "prompt编写"), "prompt_draft"),
    (("故事板设计", "故事板规范", "分镜设计"), "storyboard"),
    (("生成规范", "元素生成", "视频生成"), "generation"),
    (("组装", "导出"), "assembly"),
    (("流程规划", "阶段逻辑", "依赖关系"), "planning"),
]


def _stage_from_heading(heading: str) -> str:
    """标题关键字 → 阶段；未命中返回空串"""
    h = (heading or "").strip()
    for hints, stage in _HEADING_STAGE_HINTS:
        if any(k in h for k in hints):
            return stage
    return ""


def split_skill_sections(content: str) -> Dict[str, str]:
    """把 Skill 全文拆成 阶段 → 章节文本（同阶段多节合并）。

    支持两种格式：
    1. flova 原生 <tag>…</tag> 章节（tag 按 SECTION_TAG_STAGES 映射到阶段）；
    2. 本地改写的 Markdown 标题式（按 _HEADING_STAGE_HINTS 关键字兜底，
       未映射标题下的正文沿用上一个已识别阶段）。
    未识别章节不返回（全文本就整体注入，本函数只服务于分阶段聚焦再强调）。
    """
    content = content or ""
    collected: Dict[str, List[str]] = {}

    def _add(stage: str, body: str) -> None:
        body = (body or "").strip()
        if not stage or not body:
            return
        collected.setdefault(stage, []).append(body)

    # 1) <tag> 章节（flova 原生格式）
    tag_alt = "|".join(re.escape(t) for t in SECTION_TAG_STAGES)
    tag_re = re.compile(rf"<(?P<tag>{tag_alt})>(?P<body>.*?)</(?P=tag)>", re.S | re.I)
    found_tag = False
    for m in tag_re.finditer(content):
        found_tag = True
        _add(SECTION_TAG_STAGES.get(m.group("tag").lower(), ""), m.group("body"))
    if found_tag:
        return {k: "\n\n".join(v) for k, v in collected.items()}

    # 2) Markdown 标题兜底
    parts = re.split(r"(?m)^(#{1,4}[^\n]*)$", content)
    stage_now = ""
    for i in range(1, len(parts), 2):
        heading = parts[i].lstrip("#").strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        stage_now = _stage_from_heading(heading) or stage_now
        _add(stage_now, body)
    return {k: "\n\n".join(v) for k, v in collected.items()}

DEFAULT_SKILL_SLUG = "script-to-video"
DEFAULT_SKILL_DOC = """# 剧本生视频（需上传剧本）

> 调用规则：用户上传剧本/故事文档以生成视频时使用。在关键阶段暂停以供用户确认；
> 所有图片/视频/音频生成必须经用户明确指令才能执行，Agent 不得自动触发。

## 流程规划（三段式：规划 → 提示词草案 → 生成）

### 第一段：规划结构
1. 剧本正文不会自动注入上下文：先用 read_uploaded_doc 读取剧本全文；
   若 documents 清单里已有规格文档，先用 read_project_doc 读取并遵守；
   然后分析素材 → write_document(Final_Video_Spec.md) → request_confirmation
2. 规划故事板：add_group keyElement(只写 title+desc) + add_group shot(只写 title+shotType+sceneRefs+roughDesc+duration)
   此阶段不写详细提示词 → request_confirmation "故事板已建立，请审阅"

### 第二段：提示词草案
3. 用户确认后：为关键元素写入详细生图提示词(update_draft) → request_confirmation "尚未生成任何画面"
4. 用户确认后：为分镜写入详细视频提示词(update_draft) → request_confirmation

### 第三段：生成（用户明确发起）
5. 用户说"生成概念图" → generate_image(target="all_keyElements")
6. 用户说"生成关键帧" → generate_image(target="all_shots")，自动注入 sceneRefs 参考图

### 【铁律】
- 规划阶段不写详细提示词，只建结构
- 提示词草案阶段不触发任何生成
- "确认" ≠ "生成"，生成需要用户额外指令

## 提示词写法
- 中文分层描述 + 英文风格标签收尾
- 只写客观可见画面，禁止解释角色内心
- 关键元素 prompt ≥ 100 字，分镜关键帧 ≥ 60 字
- 视频提示词必含镜头运动指令 + 时间节奏
"""


def ensure_default_skill_docs() -> None:
    """启动时确保至少存在默认 Skill 文档"""
    SKILL_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    if not any(SKILL_DOCS_DIR.glob("*.md")):
        atomic_write_text(SKILL_DOCS_DIR / f"{DEFAULT_SKILL_SLUG}.md", DEFAULT_SKILL_DOC)
        logger.info(f"[SkillDocs] 已生成默认 Skill 文档: {DEFAULT_SKILL_SLUG}.md")


def _parse_doc(slug: str, content: str) -> Dict[str, Any]:
    name = slug
    description = ""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# ") and name == slug:
            name = line[2:].strip()
        elif line.startswith(">") and not description:
            description = line.lstrip("> ").strip()
        if name != slug and description:
            break
    return {"id": f"doc:{slug}", "slug": slug, "name": name,
            "description": description, "content": content}


def _validate_slug(slug: str) -> str:
    slug = slug.strip()
    if not _SLUG_RE.match(slug) or slug in (".", ".."):
        raise ValueError(f"非法 Skill 标识: {slug!r}")
    return slug


def list_skill_docs() -> List[Dict[str, Any]]:
    ensure_default_skill_docs()
    docs = []
    for f in sorted(SKILL_DOCS_DIR.glob("*.md")):
        try:
            docs.append(_parse_doc(f.stem, f.read_text(encoding="utf-8")))
        except OSError as e:
            logger.warning(f"[SkillDocs] 读取失败 {f.name}: {e}")
    return docs


def get_skill_doc(slug: str) -> Optional[Dict[str, Any]]:
    slug = _validate_slug(slug)
    f = SKILL_DOCS_DIR / f"{slug}.md"
    if not f.exists():
        return None
    return _parse_doc(slug, f.read_text(encoding="utf-8"))


def save_skill_doc(slug: str, content: str) -> Dict[str, Any]:
    slug = _validate_slug(slug)
    if not content.strip():
        raise ValueError("Skill 文档内容不能为空")
    SKILL_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    target = SKILL_DOCS_DIR / f"{slug}.md"
    # 覆盖前备份旧版（版本历史，供文档面板查看/回滚）
    if target.exists():
        _backup_skill_doc(slug, target)
    atomic_write_text(target, content)
    logger.info(f"[SkillDocs] 已保存 Skill 文档: {slug}.md")
    return _parse_doc(slug, content)


def _backup_skill_doc(slug: str, target: Path) -> None:
    """把旧版备份到 .history/{slug}-{毫秒时间戳}.md，并只保留最近 _HISTORY_MAX 版。

    用毫秒时间戳命名（位数固定）：字典序 = 时序，同毫秒冲突时递增。
    """
    try:
        hdir = SKILL_DOCS_DIR / _HISTORY_DIR_NAME
        hdir.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time() * 1000)
        backup = hdir / f"{slug}-{stamp}.md"
        while backup.exists():
            stamp += 1
            backup = hdir / f"{slug}-{stamp}.md"
        backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        # 裁剪：仅保留最近 _HISTORY_MAX 版（按文件名时间戳排序）
        versions = sorted(hdir.glob(f"{slug}-*.md"), key=lambda p: p.name)
        for old in versions[:-_HISTORY_MAX]:
            old.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"[SkillDocs] 版本备份失败 {slug}: {e}")


def list_skill_doc_history(slug: str) -> List[Dict[str, Any]]:
    """列出某 Skill 文档的历史版本（新→旧，含全文，供查看/回滚）"""
    slug = _validate_slug(slug)
    hdir = SKILL_DOCS_DIR / _HISTORY_DIR_NAME
    if not hdir.exists():
        return []
    items: List[Dict[str, Any]] = []
    for f in sorted(hdir.glob(f"{slug}-*.md"), key=lambda p: p.name, reverse=True):
        try:
            content = f.read_text(encoding="utf-8")
        except OSError:
            continue
        # 版本名 = 文件名去掉 slug 前缀（即时间戳部分）
        version = f.stem[len(slug) + 1:]
        items.append({"version": version, "content": content})
    return items


def delete_skill_doc(slug: str) -> None:
    """删除指定 Skill 文档，不存在时抛出 ValueError"""
    slug = _validate_slug(slug)
    f = SKILL_DOCS_DIR / f"{slug}.md"
    if not f.exists():
        raise ValueError(f"Skill 文档 '{slug}' 不存在")
    f.unlink()
    logger.info(f"[SkillDocs] 已删除 Skill 文档: {slug}.md")


def _norm_skill_name(s: str) -> str:
    """Skill 名称归一化：去空格/后缀/大小写"""
    s = (s or "").strip().casefold()
    for ext in (".md", ".txt"):
        if s.endswith(ext):
            s = s[: -len(ext)]
    return s.replace(" ", "")


def resolve_skill_content(wanted: str) -> tuple:
    """按名称解析 Skill 全文（仅文档 Skill，模糊匹配）。

    read_skill 工具与 Planner 选中项硬注入共用同一套解析，保证两处行为一致。
    代码内置 Skill（编剧/分镜师/制片）已彻底移除，不再是解析来源。
    返回 (display_name, content)，未命中返回 ("", "")。
    """
    wanted = (wanted or "").strip()
    wn = _norm_skill_name(wanted)
    if not wn:
        return "", ""

    candidates: List[Dict[str, Any]] = []
    try:
        candidates += [
            {"name": d.get("name", ""), "alias": d.get("slug", ""), "content": d.get("content", "")}
            for d in list_skill_docs()
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[SkillDocs] Skill 目录读取失败: {e}")

    def names(c: Dict[str, Any]) -> List[str]:
        return [str(c.get("name", "")), str(c.get("alias", ""))]

    # 1. 精确 → 2. 归一化相等 → 3. 双向包含（防单字误匹配）
    for c in candidates:
        if wanted in names(c):
            return str(c.get("name", "")), str(c.get("content", ""))
    for c in candidates:
        if any(_norm_skill_name(n) == wn for n in names(c) if n):
            return str(c.get("name", "")), str(c.get("content", ""))
    if len(wn) >= 2:
        for c in candidates:
            for n in names(c):
                nn = _norm_skill_name(n)
                if nn and len(nn) >= 2 and (wn in nn or nn in wn):
                    return str(c.get("name", "")), str(c.get("content", ""))
    return "", ""
