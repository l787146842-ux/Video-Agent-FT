"""
状态增量对账模块（B 方案）。

职责：
- 计算 state_dict 分组的 SHA256 指纹（digest），作为「内容有无变化」的判断依据
- 比较两轮之间的 digest 差异，输出新增/替换/移除三类变化
- 构建增量状态消息正文（供模型消费）

对齐 dsh agent-instructions：路径与 digest 未变绝不重复注入。
"""

import hashlib
import json
from typing import Any, Dict, List, Optional

from src.video_agent.state.models import (
    CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS,
)

# 三大分组类别（状态 JSON 里的 key）
_GROUP_CATS = (CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS)

# 非分组状态键——变化时触发标记而非全量重推
# analysis 已移出（2026-09-18 批 B）：改走 A' 阶段键控临时尾，不再进模型
# 状态快照，故 delta 不监控其变化（模型从 A' 尾拿最新 analysis）。
_NON_GROUP_KEYS = frozenset({
    "assets", "documents", "interaction", "uploadedDocs",
})


def compute_group_digests(raw_state: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """为每个分组计算内容指纹。

    返回 {cat_key: {group_id: sha256_hex, ...}, ...}
    空类别返回空 dict。
    """
    digests: Dict[str, Dict[str, str]] = {}
    for cat in _GROUP_CATS:
        groups = raw_state.get(cat, []) or []
        cat_digests: Dict[str, str] = {}
        for g in groups:
            if not isinstance(g, dict):
                continue
            gid = str(g.get("id", "") or "")
            if not gid:
                continue
            # 排序 key + 紧凑 JSON = 可重复哈希
            group_json = json.dumps(g, sort_keys=True, ensure_ascii=False)
            cat_digests[gid] = _sha256(group_json)
        digests[cat] = cat_digests
    return digests


def compute_state_hash(raw_state: Dict[str, Any]) -> str:
    """整份状态的总体哈希（分组 + 非分组键，排除元数据字段）。

    用于兜底检测非分组内容的变化（如 analysis 摘要更新）。
    """
    snapshot: Dict[str, Any] = {}
    for cat in _GROUP_CATS:
        if cat in raw_state:
            snapshot[cat] = raw_state[cat]
    for k in _NON_GROUP_KEYS:
        if k in raw_state:
            snapshot[k] = raw_state[k]
    return _sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False))


def compare_state(
    old_digests: Optional[Dict[str, Dict[str, str]]],
    old_hash: str,
    new_state: Dict[str, Any],
) -> tuple:
    """比较新旧状态，返回 (new_digests, new_hash, delta)。

    delta = {
        "add": [{"cat": "...", "id": "...", "group": {...}}, ...],
        "replace": [{"cat": "...", "id": "...", "group": {...}}, ...],
        "remove": [{"cat": "...", "id": "..."}, ...],
        "non_group_changed": bool,   # 非分组键有变
    }

    如果 old_digests 为 None（首轮 / 恢复后首轮），
    返回 ``has_changed=False``，调用方据此退化全量。
    """
    new_digests = compute_group_digests(new_state)
    new_hash = compute_state_hash(new_state)

    if old_digests is None:
        return new_digests, new_hash, {"_fresh": True}

    delta: Dict[str, Any] = {
        "add": [], "replace": [], "remove": [],
        "non_group_changed": False,
    }

    # 组级变化
    all_cats = set(old_digests.keys()) | set(new_digests.keys())
    for cat in all_cats:
        old_groups = old_digests.get(cat, {})
        new_groups = new_digests.get(cat, {})
        old_ids = set(old_groups.keys())
        new_ids = set(new_groups.keys())

        for gid in (old_ids - new_ids):
            delta["remove"].append({"cat": cat, "id": gid})
        for gid in (new_ids - old_ids):
            group = _find_group(new_state, cat, gid)
            if group is not None:
                delta["add"].append({"cat": cat, "id": gid, "group": group})
        for gid in (old_ids & new_ids):
            if old_groups[gid] != new_groups[gid]:
                group = _find_group(new_state, cat, gid)
                if group is not None:
                    delta["replace"].append({"cat": cat, "id": gid, "group": group})

    # 非分组变化（没有组级变化时的兜底标记）
    if old_hash != new_hash and not any(delta.values()):
        delta["non_group_changed"] = True

    return new_digests, new_hash, delta


def has_any_change(delta: Dict[str, Any]) -> bool:
    """delta 里是否有实质变化（非 fresh）。"""
    if delta.get("_fresh"):
        return True
    if delta.get("add") or delta.get("replace") or delta.get("remove"):
        return True
    if delta.get("non_group_changed"):
        return True
    return False


def build_delta_message(delta: Dict[str, Any]) -> str:
    """构建增量状态消息正文。

    返回格式为纯文本 + JSON 片段的混合，模型可直接消费。
    docstring 示例略（避免 category_keys 门禁检测字面量）。
    """
    if delta.get("_fresh"):
        # 首轮/恢复后全量——不应走此路径
        return ""

    lines = ["[状态增量] 以下分组内容有变化，其余与上轮一致：\n"]

    for action, label in [("add", "新增"), ("replace", "有更改")]:
        items = delta.get(action, [])
        if not items:
            continue
        by_cat: Dict[str, list] = {}
        for item in items:
            by_cat.setdefault(item["cat"], []).append(item["group"])
        lines.append(f"--- {label}的组 ---")
        for cat, groups in by_cat.items():
            lines.append(json.dumps({cat: groups}, ensure_ascii=False))
        lines.append("")

    removed = delta.get("remove", [])
    if removed:
        lines.append("--- 已移除的组 ---")
        for item in removed:
            lines.append(f"  - [{item['cat']}] {item['id']}")
        lines.append("")

    if delta.get("non_group_changed"):
        lines.append(
            "--- 注意：素材/文档/交互状态等非分组信息有变化，"
            "如需全量状态请调 read_state_group 按分组读取 ---"
        )

    return "\n".join(lines)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _find_group(
    raw_state: Dict[str, Any], cat: str, gid: str,
) -> Optional[Dict[str, Any]]:
    for g in (raw_state.get(cat, []) or []):
        if isinstance(g, dict) and str(g.get("id", "") or "") == gid:
            return g
    return None