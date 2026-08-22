# -*- coding: utf-8 -*-
"""Skill 平台声明 sidecar 存储（0818 B0）。

manifest 声明从 skill 文档外置到平台档案，文档还原纯散文（与源平台一致）；
registry 双读 sidecar 优先，文档 manifest 回落（文档通道 B4 退役）。
sidecar 存放清洗后声明（与旧文档通道输出同构），双读零行为变化。

读写均为活读不快照：任意键（含 v3 的 schema_version/kind/requires_inputs/
language/pause_points/scripts，任务#34 B1）原样透传，消费语义归 schema 校验器。
"""
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from src.video_agent.skill_runtime.sidecar_schema import validate_sidecar_data

_MANIFEST_FENCE_RE = re.compile(r"```json skill_manifest.*?```\n?", re.S)

# 声明写入钩子：sidecar 变更时通知消费方失效缓存（如 workflow
# 编译 per-turn 缓存）。注册方 = core.workflow_runtime（依赖方向不变：
# workflow_runtime 顶层已 import sidecar，此处只被注册不反向 import）。
_WRITE_HOOKS: List[Callable[[], None]] = []


def register_write_hook(fn: Callable[[], None]) -> None:
    if fn not in _WRITE_HOOKS:
        _WRITE_HOOKS.append(fn)


def _fire_write_hooks() -> None:
    for fn in list(_WRITE_HOOKS):
        try:
            fn()
        except Exception as e:  # 钩子失败不阻断声明写入
            logger.debug(f"[Sidecar] 写入钩子异常: {e}")


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
    _fire_write_hooks()


def validate_sidecar(data: Optional[Dict[str, Any]]) -> List[str]:
    """sidecar 声明体检（注册期门禁）：全键 schema 校验，
    单一实现 = sidecar_schema（非法声明 fail-closed，未声明键回落旧行为）。"""
    return validate_sidecar_data(data)


def migrate_doc_to_sidecar(doc_path: Path, directory: Optional[Path] = None) -> bool:
    """单文档 manifest 围栏剥离（幂等；无围栏返回 False）。

    0818 B4：声明唯一源 = sidecar；文档若仍带 manifest 围栏只剥离不消费，
    声明内容请以 data/skills_manifests/ 为准编辑。"""
    content = doc_path.read_text(encoding="utf-8")
    if not _MANIFEST_FENCE_RE.search(content):
        return False
    doc_path.write_text(
        _MANIFEST_FENCE_RE.sub("", content, count=1), encoding="utf-8")
    logger.info(f"[Sidecar] {doc_path.stem} 文档 manifest 围栏已剥离（声明以 sidecar 为准）")
    _fire_write_hooks()
    return True
