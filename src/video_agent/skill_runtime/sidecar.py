# -*- coding: utf-8 -*-
"""Skill 平台声明 sidecar 存储（0818 架构板正批 B0）。

manifest 声明从 skill 文档外置到平台档案，文档还原纯散文（与源平台一致）；
registry 双读 sidecar 优先，文档 manifest 回落（文档通道 B4 退役）。
sidecar 存放清洗后声明（与旧文档通道输出同构），双读零行为变化。
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

_MANIFEST_FENCE_RE = re.compile(r"```json skill_manifest.*?```\n?", re.S)


def sidecar_dir() -> Path:
    """sidecar 根目录：与 skill 文档同根（data/skills_manifests）。"""
    from src.video_agent.web import skill_docs as sd

    return Path(sd.SKILL_DOCS_DIR).parent / "skills_manifests"


def load_sidecar(slug: str, directory: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """读 sidecar 声明；缺失/非法返回 None（回落文档通道）。"""
    f = (directory or sidecar_dir()) / f"{slug}.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[Sidecar] 解析失败 {f.name}: {e}")
        return None
    return data if isinstance(data, dict) else None


def write_sidecar(
    slug: str, data: Dict[str, Any], directory: Optional[Path] = None
) -> None:
    d = directory or sidecar_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def migrate_doc_to_sidecar(doc_path: Path, directory: Optional[Path] = None) -> bool:
    """单文档 manifest 迁 sidecar 并去围栏（幂等；无围栏返回 False）。

    写入 sidecar 的是清洗后声明（parse_skill_manifest 输出），
    与旧文档通道逐键相等，保证双读零行为变化。
    """
    from src.video_agent.web.skill_docs import parse_skill_manifest

    content = doc_path.read_text(encoding="utf-8")
    if not _MANIFEST_FENCE_RE.search(content):
        return False
    cleaned = parse_skill_manifest(content)
    if cleaned is not None:
        write_sidecar(doc_path.stem, cleaned, directory)
    doc_path.write_text(
        _MANIFEST_FENCE_RE.sub("", content, count=1), encoding="utf-8")
    logger.info(f"[Sidecar] {doc_path.stem} manifest 已迁 sidecar，文档还原纯散文")
    return True
