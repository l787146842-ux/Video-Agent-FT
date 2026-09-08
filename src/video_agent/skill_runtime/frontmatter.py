# -*- coding: utf-8 -*-
"""Skill 平台声明 frontmatter 存储（配置与正文合一）。

声明存于 Skill 文档头部 YAML frontmatter（`---` 包裹块，Agent Skills
开放标准）——每个 Skill 就是一个目录包 data/skills/<slug>/SKILL.md，
包内其余文件为资源（references/ 等）。

读写均为活读不快照：任意键原样透传，消费语义归 manifest_schema 校验器。
正文是唯一流程源：flow.steps/step_stages/dependencies 通道废除，
声明即 fail-hard（manifest_schema）。YAML 解析失败不静默吞掉，
以 _parse_error 哨兵键透传给校验器（注册期拒注册）。
"""
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml
from loguru import logger

from src.video_agent.core import ports
from src.video_agent.skill_runtime.manifest_schema import validate_manifest_data

# frontmatter 起止行（各自独占一行）
_FENCE = "---"

# C1c 裁决 2026-08-31：裸键兼容——无 `---` 包裹的文档头部
# 连续 skill_name:/skill_description: 行识别为最小声明（映射 name/description）。
_BARE_KEY_RE = re.compile(r"^(skill_name|skill_description)\s*:\s*(.+?)\s*$")


def _extract_bare_keys(lines: List[str]) -> Tuple[Dict[str, Any], int]:
    """提取文档头部连续的 裸键行 → (声明 dict, 消费行数)。

    只认 skill_name/skill_description 两键（最小声明）；值剥成对引号；
    首个非裸键行即停（其余正文原样保留）。无命中返 ({}, 0)。"""
    manifest: Dict[str, Any] = {}
    consumed = 0
    for ln in lines:
        m = _BARE_KEY_RE.match(ln.strip())
        if not m:
            break
        key = "name" if m.group(1) == "skill_name" else "description"
        val = m.group(2).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("\"", "'"):
            val = val[1:-1]
        manifest[key] = val
        consumed += 1
    return manifest, consumed

# 声明写入钩子：frontmatter 变更时通知消费方失效缓存（如 workflow
# 编译 per-turn 缓存）。注册方 = core.workflow_runtime（依赖方向不变：
# workflow_runtime 顶层已 import frontmatter，此处只被注册不反向 import）。
_WRITE_HOOKS: List[Callable[[], None]] = []


def register_write_hook(fn: Callable[[], None]) -> None:
    if fn not in _WRITE_HOOKS:
        _WRITE_HOOKS.append(fn)


def _fire_write_hooks() -> None:
    for fn in list(_WRITE_HOOKS):
        try:
            fn()
        except Exception as e:  # 钩子失败不阻断声明写入
            logger.debug(f"[Frontmatter] 写入钩子异常: {e}")


def _skills_dir() -> Path:
    """Skill 文档根目录（随 skill_docs 端口实现的 SKILL_DOCS_DIR 镜像切换，
    测试隔离同语义）。宪法铁律：skill_runtime 不 import web 层，
    经 core.ports.skill_docs_port 端口访问（依赖倒置）。"""
    return Path(ports.skill_docs_port().SKILL_DOCS_DIR)


# 单一包形态主文档名（Agent Skills 开放标准）
SKILL_DOC_NAME = "SKILL.md"


def resolve_doc_path(slug: str, directory: Optional[Path] = None) -> Optional[Path]:
    """Skill 主文档路径解析（单一包形态，唯一解析入口）：
    只认 data/skills/<slug>/SKILL.md；不存在返回 None。
    """
    base = Path(directory) if directory is not None else _skills_dir()
    f = base / slug / SKILL_DOC_NAME
    return f if f.exists() else None


def split_frontmatter(
    content: str,
) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """拆分文档头部 frontmatter：返回 (声明 dict, 正文, 解析错误)。

    - 无 frontmatter（首行非 `---`）→ 探测 裸键最小声明（C1c 裁决）：
      头部连续 skill_name:/skill_description: 行映射为 {name, description}；
      均无命中 → (None, 原文, "")；
    - 收尾 `---` 缺失 / YAML 非法 / 根非对象 → 正文照常返回，错误串非空
      （调用方决定是否 fail-hard：注册期经 _parse_error 哨兵拒注册）；
    - 空块 = 零声明 → (None, 正文, "")。
    """
    # BOM 容错：Windows 记事本默认带 UTF-8 BOM，不剥离会使首行
    # `---` 探测静默失效（utf-8-sig 读取已兜底，字符串入口再保险一层）
    text = (content or "").lstrip("\ufeff")
    lines = text.split("\n")
    if not lines or lines[0].strip() != _FENCE:
        manifest, consumed = _extract_bare_keys(lines)
        if manifest:
            body = "\n".join(lines[consumed:]).lstrip("\n")
            return manifest, body, ""
        return None, text, ""
    close = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            close = i
            break
    if close is None:
        return None, text, "frontmatter 缺少收尾 `---` 行（声明块未闭合）"
    body = "\n".join(lines[close + 1:]).lstrip("\n")
    block = "\n".join(lines[1:close])
    if not block.strip():
        return None, body, ""
    try:
        data = yaml.safe_load(block)
    except Exception as e:
        return None, body, f"frontmatter YAML 解析失败: {e}"
    if data is None:
        return None, body, ""
    if not isinstance(data, dict):
        return None, body, "frontmatter 根节点必须是 YAML 对象"
    return data, body, ""


def strip_frontmatter(content: str) -> str:
    """剥离 frontmatter 返回正文（注入链路用：声明经元数据头单独注入，
    正文注入不再携带 YAML 头）。"""
    _, body, _ = split_frontmatter(content)
    return body


def load_manifest(
    slug: str, directory: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """读 Skill frontmatter 声明；文档/声明缺失返回 None（零声明合法）。

    YAML 解析失败返回 {"_parse_error": …} 哨兵（schema 校验报出 →
    注册期 fail-hard；消费端读不到业务键自然 fail-closed）。
    """
    f = resolve_doc_path(slug, directory)
    if f is None:
        return None
    try:
        # utf-8-sig：容忍 Windows 记事本回存的 BOM（写入侧保持 utf-8）
        content = f.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        # 读取/编码失败 ≠ 零声明：返回 None 会被当成「无声明合法」
        # 静默放行，击穿 fail-closed 契约 → 哨兵走拒注册/拒入语义
        logger.warning(f"[Frontmatter] 读取失败 {f.name}: {e}")
        return {"_parse_error": f"文档读取失败: {e}"}
    data, _, err = split_frontmatter(content)
    if err:
        logger.warning(f"[Frontmatter] {f.name} 声明解析问题: {err}")
        return {"_parse_error": err}
    return data


def render_frontmatter(manifest: Dict[str, Any]) -> str:
    """声明 dict → frontmatter 块文本（`---` 包裹，尾随换行）。"""
    dumped = yaml.safe_dump(
        manifest, allow_unicode=True, sort_keys=False, default_flow_style=False)
    if not dumped.endswith("\n"):
        dumped += "\n"
    return f"{_FENCE}\n{dumped}{_FENCE}\n"


def write_manifest(
    slug: str, data: Dict[str, Any], directory: Optional[Path] = None,
) -> None:
    """把声明写入 Skill 文档头部 frontmatter（幂等：整块替换）。

    文档已存在 → 只替换头部声明块，正文不动；不存在 → 新建仅含声明的
    文档（测试/迁移用）。data 为空/None = 清除声明块。
    """
    base = Path(directory) if directory is not None else _skills_dir()
    f = resolve_doc_path(slug, directory) or (base / slug / SKILL_DOC_NAME)
    f.parent.mkdir(parents=True, exist_ok=True)
    old = ""
    if f.exists():
        old = f.read_text(encoding="utf-8")
    _, body, _ = split_frontmatter(old)
    if not isinstance(data, dict) or not data:
        f.write_text(body, encoding="utf-8")
    else:
        sep = "\n" if body and not body.startswith("\n") else ""
        f.write_text(render_frontmatter(data) + sep + body, encoding="utf-8")
    _fire_write_hooks()


def validate_manifest(data: Optional[Dict[str, Any]]) -> List[str]:
    """frontmatter 声明体检（注册期门禁）：全键 schema 校验，
    单一实现 = manifest_schema（非法声明 fail-closed，未声明键回落旧行为）。"""
    return validate_manifest_data(data)
