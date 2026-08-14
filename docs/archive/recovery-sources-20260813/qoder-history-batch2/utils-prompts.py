"""
Prompt 加载器 — 从 prompts/ 目录读取 Markdown 模板（Rule4: Prompt 外置管理）。

用法：
    from src.video_agent.utils.prompts import load_prompt, render_prompt

    system = load_prompt("planner/system.md")
    rendered = render_prompt("planner/context_template.md", state_json="...", selected_draft_id="x")
"""
import re
from pathlib import Path
from typing import Any

from loguru import logger

from src.video_agent.utils.paths import PROMPTS_DIR

# 简单缓存，避免每次请求都读磁盘
_cache: dict[str, str] = {}


def load_prompt(relative_path: str, use_cache: bool = True, lang: str = "") -> str:
    """加载 prompts/ 下的 Markdown 文件原文。

    Args:
        relative_path: 相对于 prompts/ 的路径，如 "planner/system.md"
        use_cache: 是否使用内存缓存（默认 True）
        lang: 语言后缀（如 "en"），优先加载 {name}_{lang}.md，不存在时 fallback 到 {name}.md

    Returns:
        文件文本内容；文件不存在时返回空字符串并记录警告。
    """
    # 如果指定了 lang，尝试加载本地化版本
    if lang:
        stem = relative_path.rsplit(".", 1)[0]  # "planner/system"
        ext = relative_path.rsplit(".", 1)[1] if "." in relative_path else "md"
        localized_path = f"{stem}_{lang}.{ext}"  # "planner/system_en.md"
        localized_fpath = PROMPTS_DIR / localized_path
        if localized_fpath.exists():
            return _load_file(localized_path, use_cache)

    return _load_file(relative_path, use_cache)


def _load_file(relative_path: str, use_cache: bool = True, _depth: int = 0) -> str:
    """内部文件加载（带缓存）。

    批次5：支持 {{include:path}} 组装指令——把 prompts/ 下另一文件的全文
    嵌入当前位置（共有段落单一事实源，防多处复制漂移）；递归深度限制防环。
    """
    cache_key = relative_path
    if use_cache and cache_key in _cache:
        return _cache[cache_key]

    fpath = PROMPTS_DIR / relative_path
    if not fpath.exists():
        logger.warning(f"[Prompts] 文件不存在: {fpath}")
        return ""

    try:
        text = fpath.read_text(encoding="utf-8")
    except OSError as e:
        logger.error(f"[Prompts] 读取失败: {fpath} - {e}")
        return ""

    if _depth < 4 and "{{include:" in text:
        def _sub(m: re.Match) -> str:
            inc_path = m.group(1).strip()
            return _load_file(inc_path, use_cache=False, _depth=_depth + 1)
        text = re.sub(r"\{\{include:([^}]+)\}\}", _sub, text)

    if use_cache:
        _cache[cache_key] = text
    return text


def load_prompt_section(relative_path: str, section: str) -> str:
    """加载文件的指定分节（批次5：系统文案外置的读取入口）。

    分节格式：`## KEY` 标题到下一个 `## ` 标题（或文件末尾）之间的正文。
    未找到分节时返回空串并告警（调用方应有内置兜底）。"""
    text = load_prompt(relative_path)
    if not text:
        return ""
    pattern = re.compile(
        rf"(?m)^##\s+{re.escape(section)}\s*\n(.*?)(?=^##\s+|\Z)", re.S)
    m = pattern.search(text)
    if not m:
        logger.warning(f"[Prompts] 分节不存在: {relative_path} :: {section}")
        return ""
    return m.group(1).strip()


def render_prompt(relative_path: str, **kwargs: Any) -> str:
    """加载并渲染 Handlebars 风格的模板（仅支持简单变量替换和 {{#if}}）。

    支持的语法：
    - {{variable}} → 替换为 kwargs[variable]
    - {{#if variable}}...{{/if}} → 当 kwargs[variable] 为真值时保留块内容

    Args:
        relative_path: 相对于 prompts/ 的路径
        **kwargs: 模板变量

    Returns:
        渲染后的文本
    """
    template = load_prompt(relative_path)
    if not template:
        return ""

    # 处理 {{#if var}}...{{/if}} 条件块
    def _replace_if_block(match: re.Match) -> str:
        var_name = match.group(1).strip()
        block_content = match.group(2)
        value = kwargs.get(var_name)
        if value:
            return block_content
        return ""

    result = re.sub(
        r"\{\{#if\s+(\w+)\s*\}\}([\s\S]*?)\{\{/if\}\}",
        _replace_if_block,
        template,
    )

    # 处理 {{variable}} 简单替换
    def _replace_var(match: re.Match) -> str:
        var_name = match.group(1).strip()
        value = kwargs.get(var_name, "")
        return str(value) if value is not None else ""

    result = re.sub(r"\{\{(\w+)\}\}", _replace_var, result)

    return result


def clear_cache() -> None:
    """清除 prompt 缓存（开发/测试用）"""
    _cache.clear()
