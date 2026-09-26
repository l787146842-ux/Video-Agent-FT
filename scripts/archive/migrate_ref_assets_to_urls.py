# -*- coding: utf-8 -*-
"""一次性迁移：故事板草稿 `refAssets` 里的**草稿 id** 归一到媒体 URL。

## 为什么需要

`refAssets` 的契约是**媒体 URL 列表**（`models.DraftRecord.ref_assets`；前端
`refAssetName` / `refAssetType` / `safeUrl` 全按 URL 消费），而模型的写入口径是
**草稿身份**（状态快照里它看得见 `drafts[].id`，看不见分组标题），照抄即落
`draft-1790359321-a010380d` 这类 id。实测 9999 项目（`proj-1790358500-25465d26`）
**79 条引用全是 id 形态、合法 URL 0 条**，后果两处：

1. 前端 `<img src="draft-…">` 被 `safeUrl` 拦成空串 ⇒ 参考素材栏**图裂成 alt 文字**
   （用户截图「参考素材 1/2/3/4/5」即此）；
2. 生成时该字符串被当 URL 塞进 `reference_images` ⇒ **参考图静默落空**
   （花钱生成白挂参考）。

## 状态：**未执行**（2026-09-26 用户裁决「只修代码，存量不管」）

代码侧写口归一已落地并全路径覆盖，**新写入不再产 id 形态**；存量 79 条经用户
裁决**不清偿**——后果如实登记：旧卡参考素材栏仍图裂（alt 文字）、生成时该字段
仍会被当 URL 发出而落空。用户如需清偿，跑本脚本即可（幂等，可重复执行）。

用法（默认 dry-run 只报告，不落盘）：

    python scripts/archive/migrate_ref_assets_to_urls.py
    python scripts/archive/migrate_ref_assets_to_urls.py --apply

注意：真实服务运行时会把项目缓存在内存并带版本账本（`board_version`），
**直接改库可能被其下次落盘覆盖**——apply 前应先停服务，改完再启动。

退出码：0 = 处理完毕（dry-run 视为成功）；1 = 落盘失败。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.video_agent.state import storyboard_ops as ops  # noqa: E402
from src.video_agent.state.models import ALL_CATEGORIES  # noqa: E402

DB_PATH = ROOT / "workspace" / "state.sqlite3"


def _iter_drafts(state: Dict[str, Any]):
    """遍历 (类别, 组, 卡) 三元组（只读）。"""
    for cat_key in ALL_CATEGORIES:
        for group in state.get(cat_key) or []:
            if not isinstance(group, dict):
                continue
            for draft in group.get("drafts") or []:
                if isinstance(draft, dict):
                    yield cat_key, group, draft


def migrate_state(state: Dict[str, Any]) -> List[Tuple[str, str, str, List[str], List[str]]]:
    """就地归一单个项目 state，返回变更明细（不改 db）。

    返回 [(类别, 组标题, 卡标签, 原列表, 新列表)]，仅含**确有变化**的卡。
    """
    changes: List[Tuple[str, str, str, List[str], List[str]]] = []
    for cat_key, group, draft in _iter_drafts(state):
        raw = draft.get("refAssets") or []
        if not raw:
            continue
        fixed = ops.normalize_ref_assets(state, raw)
        if fixed != list(raw):
            changes.append((
                cat_key,
                str(group.get("title") or ""),
                str(draft.get("label") or ""),
                [str(x) for x in raw],
                fixed,
            ))
            draft["refAssets"] = fixed
    return changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真写回（默认 dry-run 只报告）")
    ap.add_argument("--db", default=str(DB_PATH), help="state.sqlite3 路径")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"[FAIL] 找不到状态库：{db}")
        return 1

    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    rows = list(con.execute("SELECT id, state FROM projects"))

    total_cards = 0
    total_items = 0
    touched_projects = 0
    report: List[str] = [f"扫描 {len(rows)} 个项目（{'APPLY' if args.apply else 'DRY-RUN'}）"]

    for row in rows:
        pid = row["id"]
        try:
            state = json.loads(row["state"])
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] 项目 {pid} state 解析失败：{e}")
            return 1
        changes = migrate_state(state)
        if not changes:
            continue
        touched_projects += 1
        name = state.get("project_name") or ""
        report.append(f"\n=== {pid}（{name}）：{len(changes)} 张卡需归一")
        for cat_key, gtitle, dlabel, old, new in changes:
            total_cards += 1
            total_items += len(old)
            report.append(f"  [{cat_key}] {gtitle} / {dlabel}")
            report.append(f"      原 {len(old)} 条 → 新 {len(new)} 条")
            for a, b in zip(old, new):
                if a != b:
                    report.append(f"        {a}  →  {b}")
        if args.apply:
            con.execute(
                "UPDATE projects SET state=? WHERE id=?",
                (json.dumps(state, ensure_ascii=False), pid),
            )

    if args.apply and touched_projects:
        con.commit()
    con.close()

    report.append(
        f"\n汇总：{touched_projects} 个项目 / {total_cards} 张卡 / {total_items} 条引用"
        f"（{'已写回' if args.apply else '未写回（dry-run）'}）")
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
