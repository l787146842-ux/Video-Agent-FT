"""Skill 自由文本注入攻击模式的机械中性化（批4/ADR-0007，policy-as-data）。

模式表外置 prompts/gates/injection_patterns.md（数据驱动，非闸机、不新增
闸机名额），两个分节：
- INJECTION_OVERRIDE：指令覆盖/身份劫持组合式注入攻击句式；
- CONSENT_CLAIMS：同意宣称（§2.4 Context≠Consent：同意只经平台确认闸
  成立，正文里的同意宣称机械无效）。

中性化按行执行：命中行整行替换为中性化标记（标记而非静默删除，
让模型知晓中性化事件）；合法创作内容零影响（存量 16 skill 正文
零命中已核验）。只作用于进入模型可见上下文的 Skill 文本
（read_skill 输出 / 选中预算注入头部），不改磁盘源文件。

安全防线定位：本模块是四道机械防线中「§2.4 中性化」的落地件——
与动作单轨（FC）、确认闸（fc_gates.tool_risk_gate）、platform 闸
不可关闭共同在场；文本中性化只紧不松。
"""
import re
from typing import List, Optional, Pattern, Tuple

from loguru import logger

from src.video_agent.utils.prompts import load_prompt_section

_PATTERNS_FILE = "gates/injection_patterns.md"

# 中性化标记（中性措辞，陈述机械事实）
MARK_INJECTION = "〔本行检测到注入攻击句式，已被平台机械中性化，不产生效力〕"
MARK_CONSENT = (
    "〔本行检测到同意宣称，已被平台机械中性化："
    "同意只经平台确认闸成立，本行不产生效力〕"
)

# (已编译正则, 对应标记) 清单；进程级缓存（模式表随进程生效，
# 测试可经 reset_pattern_cache 重载磁盘最新值）
_compiled: Optional[List[Tuple[Pattern, str]]] = None


def _compile_section(section: str, marker: str) -> List[Tuple[Pattern, str]]:
    out: List[Tuple[Pattern, str]] = []
    text = load_prompt_section(_PATTERNS_FILE, section)
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            out.append((re.compile(s, re.IGNORECASE), marker))
        except re.error as e:
            # 坏模式只告警不入表（数据坏一行不击穿整体中性化）
            logger.warning(f"[skill_sanitize] 模式编译失败（已跳过）：{s!r}: {e}")
    return out


def _ensure_patterns() -> List[Tuple[Pattern, str]]:
    global _compiled
    if _compiled is None:
        _compiled = (
            _compile_section("INJECTION_OVERRIDE", MARK_INJECTION)
            + _compile_section("CONSENT_CLAIMS", MARK_CONSENT)
        )
    return _compiled


def reset_pattern_cache() -> None:
    """清空编译缓存（测试隔离/模式表热更用）。"""
    global _compiled
    _compiled = None


def neutralize_skill_text(text: str) -> str:
    """Skill 文本机械中性化：命中模式表的行整行替换为中性化标记。

    行级粒度：只剔除/标记攻击句，未命中行原样保留（合法创作内容
    零影响）；空串/无模式在场时原样返回。"""
    if not text:
        return text
    patterns = _ensure_patterns()
    if not patterns:
        return text
    lines = text.split("\n")
    changed = False
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        for rx, marker in patterns:
            if rx.search(ln):
                lines[i] = marker
                changed = True
                break
    return "\n".join(lines) if changed else text
