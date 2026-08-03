"""
Skill 文档化存储层。

对标 FTDYB：Skill 不是代码里的一段提示词，而是用户可见、可编辑的 Markdown 文档，
存放在 data/skills/，全文注入 LLM system prompt——"流程即数据"。

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

# 版本历史：保存前把旧版备份到 .history/，每个 slug 保留最近 N 版
_HISTORY_DIR_NAME = ".history"
_HISTORY_MAX = 10

DEFAULT_SKILL_SLUG = "script-to-video"
DEFAULT_SKILL_DOC = """# 剧本生视频（需上传剧本）

> 调用规则：用户上传剧本/故事文档以生成视频时使用。在关键阶段暂停以供用户确认；
> 所有图片/视频/音频生成必须经用户明确指令才能执行，Agent 不得自动触发。

## 流程规划（三段式：规划 → 提示词草案 → 生成）

### 第一段：规划结构
1. 分析素材 → write_document(Final_Video_Spec.md) → request_confirmation
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
