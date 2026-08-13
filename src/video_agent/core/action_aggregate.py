"""动作记录聚合（前端「阶段完成卡片」展开明细的粗粒度展示）。"""
from typing import Any, Dict, List

# 可聚合的动作名 → 聚合后的通用摘要（保留动词+对象类别，剔除具体标题）
_GROUP_LABELS = {
    "update_draft": "更新草稿的提示词",
    "patch_draft": "更新草稿的提示词",
    "add_draft": "新增草稿",
    "update_group": "更新分组",
    "add_group": "新建分组",
}


def aggregate_action_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把同 action 名的连续记录聚合为一条（首个保留原文，后续折叠进末条）。

    - 不可聚合项（read_* 等）自成一条；
    - 聚合后 summary 为「通用摘要 ×N」，elapsed_ms 求和，ok = 全成功才 True。
    """
    merged: List[Dict[str, Any]] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        name = str(rec.get("name") or "")
        can_group = name in _GROUP_LABELS
        if can_group and merged and merged[-1].get("name") == name:
            prev = merged[-1]
            prev["count"] = int(prev.get("count") or 1) + 1
            prev["elapsed_ms"] = round(
                float(prev.get("elapsed_ms") or 0.0) + float(rec.get("elapsed_ms") or 0.0), 1,
            )
            prev["ok"] = bool(prev.get("ok")) and bool(rec.get("ok"))
            prev["summary"] = f"{_GROUP_LABELS[name]} ×{prev['count']}"
            continue
        item = dict(rec)
        item.setdefault("count", 1)
        merged.append(item)
    return merged
