# -*- coding: utf-8 -*-
"""故事板三向合并域（G1 并行局部修改，2026-08-31 用户裁决立项）。

Flova 对齐：多镜头可同时细修；用户编辑与 Agent 写入并行时，系统按
元素粒度检测冲突并以冲突面板交由用户选择，取代「整板 409 丢弃重做」。

机制：
- 版本历史缓冲（内存，重启即弃）：每次落盘记录该版号的故事板四类别
  内容快照；客户端携 base_version 请求合并时据此做三向合并
  （base=客户端所见 / mine=客户端提交 / theirs=服务端当前）。
- 合并粒度：分组字段级 + 草稿级（id 对齐）；单方改动直接采纳，
  双方同改同一处 → 冲突项进面板；新增/删除按三向规则自动判定。
- 冲突项默认保留用户版进 merged 结果，前端按用户选择回替后整板提交。
"""
import copy
import json
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from .models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS

# 故事板四类别（整板 PUT 同口径；对话不参与合并；类别键归 models.py 常量）
CAT_ASSETS = "assets"
BOARD_CATEGORIES = (CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS, CAT_ASSETS)

# 每项目保留的版号快照条数（够覆盖一次编辑会话的在途竞态即可）
_HISTORY_MAX = 20

# pid → [(board_version, 四类别快照)]；内存态，重启清零（base 不可得时回落旧 409 语义）
_BOARD_HISTORY: Dict[str, Deque[Tuple[int, Dict[str, List[Dict[str, Any]]]]]] = {}

_CAT_LABELS = {
    CAT_KEY_ELEMENTS: "关键元素", CAT_SHOTS: "分镜",
    CAT_AUDIO_ITEMS: "音频", CAT_ASSETS: "素材",
}


def cat_label(category: str) -> str:
    """类别中文标签（冲突面板展示用）。"""
    return _CAT_LABELS.get(category, category)


def _board_of(raw_state: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    return {cat: copy.deepcopy(list(raw_state.get(cat) or []))
            for cat in BOARD_CATEGORIES}


def record_board(pid: str, version: int, raw_state: Dict[str, Any]) -> None:
    """落盘后记录该版号的故事板快照（save_ops 升版后调用）。"""
    if not pid:
        return
    hist = _BOARD_HISTORY.setdefault(pid, deque(maxlen=_HISTORY_MAX))
    hist.append((int(version), _board_of(raw_state)))


def base_board(pid: str, version: Optional[int]) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """取指定版号的故事板快照；不可得返 None（调用方回落旧冲突语义）。"""
    if not pid or version is None:
        return None
    for v, snap in _BOARD_HISTORY.get(pid, ()):
        if v == int(version):
            return copy.deepcopy(snap)
    return None


def clear_history(pid: str = "") -> None:
    """清空历史（项目删除/测试复位用；空参=全清）。"""
    if pid:
        _BOARD_HISTORY.pop(pid, None)
    else:
        _BOARD_HISTORY.clear()


def _j(v: Any) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)


def _group_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in item.items() if k != "drafts"}


def _conflict(category: str, kind: str, item: Dict[str, Any],
              mine: Any, theirs: Any,
              group: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    g = group or item
    return {
        "category": category,
        "category_label": cat_label(category),
        "kind": kind,  # group=分组字段冲突 / draft=草稿冲突 / delete_vs_modify=删改冲突
        "group_id": str(g.get("id") or ""),
        "group_title": str(g.get("title") or g.get("label") or ""),
        "id": str(item.get("id") or ""),
        "label": str(item.get("label") or item.get("title") or ""),
        "mine": mine,
        "theirs": theirs,
    }


def _merge_item_list(
    category: str, base_items: List[Dict[str, Any]],
    mine_items: List[Dict[str, Any]], theirs_items: List[Dict[str, Any]],
    conflicts: List[Dict[str, Any]], is_group: bool,
    parent: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """三向合并一组条目（分组级或草稿级同构）：
    mine 顺序为主，theirs 新增追加末尾；单方改动直接采纳，
    双方同改 → 冲突（默认保留 mine 进结果，面板定夺）。"""
    b_idx = {str(i.get("id") or ""): i for i in base_items if isinstance(i, dict)}
    t_idx = {str(i.get("id") or ""): i for i in theirs_items if isinstance(i, dict)}
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for m in mine_items:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "")
        seen.add(mid)
        b, t = b_idx.get(mid), t_idx.get(mid)
        if t is None:
            if b is None:
                out.append(m)  # mine 新增
            elif _j(m) == _j(b):
                pass  # theirs 删除、mine 未改 → 采纳删除
            else:
                conflicts.append(_conflict(category, "delete_vs_modify", m, m, None, parent))
                out.append(m)
            continue
        if b is None:
            if _j(m) != _j(t):
                conflicts.append(_conflict(category, "draft" if not is_group else "group", m, m, t, parent))
            out.append(m)
            continue
        if is_group:
            out.append(_merge_group(category, b, m, t, conflicts))
        else:
            if _j(m) == _j(b):
                out.append(copy.deepcopy(t))
            elif _j(t) == _j(b):
                out.append(copy.deepcopy(m))
            elif _j(m) == _j(t):
                out.append(copy.deepcopy(m))
            else:
                conflicts.append(_conflict(category, "draft", m, m, t, parent))
                out.append(copy.deepcopy(m))
    for t in theirs_items:
        if isinstance(t, dict) and str(t.get("id") or "") not in seen:
            out.append(copy.deepcopy(t))  # Agent 新增
    return out


def _merge_group(category: str, b: Dict[str, Any], m: Dict[str, Any],
                 t: Dict[str, Any], conflicts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """分组合并：外壳字段三向 + drafts 列表三向。"""
    bf, mf, tf = _group_fields(b), _group_fields(m), _group_fields(t)
    if _j(mf) == _j(bf):
        fields = copy.deepcopy(tf)
    elif _j(tf) == _j(bf):
        fields = copy.deepcopy(mf)
    elif _j(mf) == _j(tf):
        fields = copy.deepcopy(mf)
    else:
        conflicts.append(_conflict(category, "group", m, mf, tf))
        fields = copy.deepcopy(mf)
    fields["drafts"] = _merge_item_list(
        category, list(b.get("drafts") or []), list(m.get("drafts") or []),
        list(t.get("drafts") or []), conflicts, is_group=False, parent=m)
    return fields


def merge_board(
    base: Dict[str, List[Dict[str, Any]]],
    mine: Dict[str, List[Dict[str, Any]]],
    theirs: Dict[str, List[Dict[str, Any]]],
) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """三向合并四类别；返回 (合并结果, 冲突清单)。冲突清单空 = 可直接落盘。"""
    merged: Dict[str, List[Dict[str, Any]]] = {}
    conflicts: List[Dict[str, Any]] = []
    for cat in BOARD_CATEGORIES:
        merged[cat] = _merge_item_list(
            cat, list(base.get(cat) or []), list(mine.get(cat) or []),
            list(theirs.get(cat) or []), conflicts, is_group=True)
    return merged, conflicts
