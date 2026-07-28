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


def load_prompt(relative_path: str, use_cache: bool = True) -> str:
    """加载 prompts/ 下的 Markdown 文件原文。

    Args:
        relative_path: 相对于 prompts/ 的路径，如 "planner/system.md"
        use_cache: 是否使用内存缓存（默认 True）

    Returns:
        文件文本内容；文件不存在时返回空字符串并记录警告。
    """
    if use_cache and relative_path in _cache:
        return _cache[relative_path]

    fpath = PROMPTS_DIR / relative_path
    if not fpath.exists():
        logger.warning(f"[Prompts] 文件不存在: {fpath}")
        return ""

    try:
        text = fpath.read_text(encoding="utf-8")
    except OSError as e:
        logger.error(f"[Prompts] 读取失败: {fpath} - {e}")
        return ""

    if use_cache:
        _cache[relative_path] = text
    return text


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
