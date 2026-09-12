# -*- coding: utf-8 -*-
"""批 12 · 同意口径告示牌一致性门禁（GOVERNANCE P1：同一规则定义处恒等于 1）。

「什么算用户同意」的判定唯一家 = core/guard_pipeline.CONSENT_CHARTER
（动作类 × 同意来源 = 放行范围）。本闸校验全部对外承诺文案（告示牌）的
承诺 ⊆ 章程允许范围，防「文案承诺了闸机不认的同意路径」再次发生
（1000 事故：通用拒因对非 costly 高危承诺「接受暂停卡后重提即放行」，
闸机按章程不认 → 空头支票 → 模型口播假完成）：

- 生成/规格类拒因 TOOL_RISK_BLOCKED 与生成确认拒因 GENERATION_CONFIRM_BLOCKED
  必须承诺「接受暂停卡后重提」——章程对 costly_generation/spec_write/
  gen_confirm 草稿目标允许 pause-accept，承诺成真；
- other_high 拒因 TOOL_RISK_BLOCKED_OTHER 必须指引用户「本次放行」、
  不得含任何 pause-accept 承诺（章程 other_high=False，fail-closed）；
  tool_risk 两分支拒因均不得指引「工作台确认相关草稿」——该同意路径
  归 gen_confirm 闸消费（drafts_confirmed），evaluate_tool_risk 不认；
- 协议（protocol.md）/ 执行偏好（execution_preference.md）/ 设置页 hint
  与上述口径同源；
- C1a 已废的「文本解读式同意」措辞（「消息明确指示」）全文本禁绝。

fail-closed：任何文件缺失 / 读取失败 / 分节缺失 / 断言不过 = 违规。
输出纯 ASCII（Windows GBK 纪律，acceptance 只认退出码）。
"""
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent

# 扫描面（相对 ROOT；canary monkeypatch ROOT 指向 tmp_path 副本）
COPY_FILES: Dict[str, str] = {
    "messages_md": "prompts/gates/messages.md",
    "protocol_md": "prompts/planner/protocol.md",
    "exec_pref_md": "prompts/planner/execution_preference.md",
    "settings_tsx": "src/web/components/layout/global-settings/ExecutionPreferenceSection.tsx",
}

# (文件键, 分节(None=全文), 必含子串, 必不含子串, 说明)
CHECKS: List[Tuple[str, Optional[str], List[str], List[str], str]] = [
    ("messages_md", "TOOL_RISK_BLOCKED",
     ["高风险工具确认闸拦截", "接受暂停卡后重提", "本次放行"],
     ["确认相关草稿"],
     "gen/spec refusal keeps pause-accept promise only (draft-confirm is "
     "gen_confirm's path, evaluate_tool_risk does not consume it)"),
    ("messages_md", "TOOL_RISK_BLOCKED_OTHER",
     ["高风险工具确认闸拦截", "本次放行"],
     ["接受暂停卡后重提", "重提即视为已确认", "确认相关草稿"],
     "other_high refusal must NOT promise pause-accept (charter denies)"),
    ("messages_md", "GENERATION_CONFIRM_BLOCKED",
     ["接受暂停卡后重提", "已确认"], [],
     "gen_confirm refusal keeps pause-accept promise (charter allows)"),
    ("protocol_md", None,
     [],
     ["接受暂停卡后重提", "重提即视为已确认", "本次放行"],
     "protocol carries no consent promise (2026-09-12 governance batch moved "
     "the promise to gates/exec-pref homes; P1 moved-out side must not relapse)"),
    ("exec_pref_md", "PREF_CONFIRM_BEFORE_GEN",
     ["不会重复拦截", "制片规格"], [],
     "exec-pref confirm hint in sync with charter incl. spec write"),
    ("settings_tsx", "confirm_before_gen",
     ["确认提示词草案", "不再重复拦截"], [],
     "settings-page hint promises only gen-draft review flow"),
]

# C1a 裁决（2026-08-31）已废「文本解读式同意」：任何告示牌不得再暗示
# 「消息文本 = 同意指示」。
GLOBAL_FORBIDDEN: List[str] = ["本条消息明确指示", "消息明确指示"]

# 设置页 TSX：先截取 PREF_HINTS 对象块（PREF_LABELS 也有 confirm_before_gen
# 同名键，直接全文搜索会误中标签），再抽取该档的 hint 字符串
_HINTS_BLOCK_RE = re.compile(r"PREF_HINTS\s*:\s*Record<string, string>\s*=\s*\{(.*?)\};", re.S)
_TSX_HINT_RE = re.compile(r"confirm_before_gen:\s*\n?\s*'((?:[^'\\]|\\.)*)'")


def _load(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _md_section(text: str, key: str) -> str:
    """prompts 外置分节提取（## KEY 到下一个 ## 标题），与
    utils.prompts.load_prompt_section 同口径；直读不走进程缓存
    （门禁须看磁盘现状，测试 canary 也避免缓存污染）。"""
    m = re.search(rf"(?ms)^## {re.escape(key)}\s*$\n(.*?)(?=^## |\Z)", text)
    return m.group(1).strip() if m else ""


def _scope_text(files: Dict[str, str], file_key: str,
                section: Optional[str], raw: str) -> Optional[str]:
    """按校验项圈定文本范围；分节/键缺失返回 None（fail-closed）。"""
    if section is None:
        return raw
    if file_key == "settings_tsx":
        block = _HINTS_BLOCK_RE.search(raw)
        if not block:
            return None
        m = _TSX_HINT_RE.search(block.group(1))
        return m.group(1) if m else None
    return _md_section(raw, section) or None


def main() -> int:
    violations: List[str] = []
    raws: Dict[str, str] = {}
    for fkey, rel in COPY_FILES.items():
        try:
            raws[fkey] = _load(rel)
        except OSError as exc:
            violations.append(f"[FAIL] missing/unreadable {rel}: {exc.errno}")

    for fkey, section, must_have, must_not, label in CHECKS:
        raw = raws.get(fkey)
        if raw is None:
            continue  # 文件级缺失已记，避免重复
        scope = _scope_text(raws, fkey, section, raw)
        if scope is None:
            rel = COPY_FILES[fkey]
            violations.append(
                f"[FAIL] {label}: section/key missing in {rel}"
                + (f"::{section}" if section else ""))
            continue
        for needle in must_have:
            if needle not in scope:
                violations.append(
                    f"[FAIL] {label}: missing required consent-copy phrase in "
                    f"{COPY_FILES[fkey]}"
                    + (f"::{section}" if section else ""))
        for needle in must_not:
            if needle in scope:
                violations.append(
                    f"[FAIL] {label}: forbidden promise (charter denies it) in "
                    f"{COPY_FILES[fkey]}"
                    + (f"::{section}" if section else ""))

    for fkey, raw in raws.items():
        for needle in GLOBAL_FORBIDDEN:
            if needle in raw:
                violations.append(
                    f"[FAIL] banned wording (C1a: text-as-consent) in "
                    f"{COPY_FILES[fkey]}: {needle!r}")

    if violations:
        for v in violations:
            sys.stdout.write(v + "\n")
        sys.stdout.write(f"consent_copy: FAIL ({len(violations)} violation(s))\n")
        return 1
    sys.stdout.write("consent_copy: PASS (all consent-copy homes within charter)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
