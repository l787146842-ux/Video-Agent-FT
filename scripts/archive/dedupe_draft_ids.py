"""
存量项目 draft/group/asset id 去重脚本（一次性修复）。

背景：旧版 gen_id 随机部分仅 3 位（900 种取值），同秒批量建卡碰撞率约 14%，
导致前端"选中 A 卡预览显示 B 卡"。本脚本扫描所有存量项目，检测重复 id，
对重复项重新分配新 id（保留原前缀），先备份再写回。

同时处理两种存储后端：
- JSON（默认）：workspace/projects/<pid>/state.json
- SQLite：workspace/state.sqlite3（projects 表）

用法：
    python scripts/dedupe_draft_ids.py              # 实际修复
    python scripts/dedupe_draft_ids.py --dry-run    # 只报告不修改
    python scripts/dedupe_draft_ids.py --workspace <path>
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.video_agent.utils import gen_id  # noqa: E402
from src.video_agent.utils.fileio import atomic_write_text  # noqa: E402
from src.video_agent.utils.paths import WORKSPACE_DIR  # noqa: E402

_ID_RE = re.compile(r"^([A-Za-z]+)[-_]")


def _prefix_of(old_id: str, fallback: str) -> str:
    m = _ID_RE.match(old_id or "")
    return m.group(1) if m else fallback


def dedupe_state(state: Dict[str, Any]) -> List[Tuple[str, str]]:
    """就地修复 state 字典中的重复 id，返回 (旧id, 新id) 列表。

    检查范围（与前端共用同一 selectedId 命名空间的对象）：
    - keyElements / shots / audioItems 各分组的 id
    - 各分组 drafts 内的 draft id
    - assets 列表的 asset id
    """
    renames: List[Tuple[str, str]] = []
    seen: set = set()

    def _ensure_unique(obj: Dict[str, Any], fallback_prefix: str) -> None:
        oid = obj.get("id")
        if not oid:
            return
        if oid in seen:
            nid = gen_id(_prefix_of(oid, fallback_prefix))
            while nid in seen:
                nid = gen_id(_prefix_of(oid, fallback_prefix))
            obj["id"] = nid
            renames.append((oid, nid))
            seen.add(nid)
        else:
            seen.add(oid)

    for cat in ("keyElements", "shots", "audioItems"):
        for group in state.get(cat) or []:
            if not isinstance(group, dict):
                continue
            _ensure_unique(group, "group")
            for draft in group.get("drafts") or []:
                if isinstance(draft, dict):
                    _ensure_unique(draft, "draft")

    for asset in state.get("assets") or []:
        if isinstance(asset, dict):
            _ensure_unique(asset, "asset")

    # 引用修正：interaction.selectedDraftId 指向被改名的 id 时，置空
    # （重复 id 本身有歧义，无法确定指向哪张卡，置空让前端回到未选中态最安全）
    interaction = state.get("interaction") or {}
    renamed_away = {old for old, _ in renames}
    if interaction.get("selectedDraftId") in renamed_away:
        interaction["selectedDraftId"] = ""
        interaction["selectedType"] = ""

    return renames


def _process_state_text(pid: str, state_text: str, dry_run: bool) -> Tuple[str, int]:
    """返回 (新 state 文本, 修复数量)；无重复或 dry_run 时返回原文本。"""
    state = json.loads(state_text)
    renames = dedupe_state(state)
    if not renames or dry_run:
        return state_text, len(renames)
    return json.dumps(state, ensure_ascii=False, indent=2), len(renames)


def run(workspace: Path, dry_run: bool) -> int:
    total_fixed = 0
    projects_dir = workspace / "projects"

    # ===== JSON 后端 =====
    if projects_dir.exists():
        for sfile in sorted(projects_dir.glob("*/state.json")):
            pid = sfile.parent.name
            try:
                text = sfile.read_text(encoding="utf-8")
                new_text, n = _process_state_text(pid, text, dry_run)
            except Exception as e:
                print(f"[跳过] {pid}: 读取/解析失败 {e}")
                continue
            if n == 0:
                print(f"[正常] {pid}: 无重复 id")
                continue
            total_fixed += n
            if dry_run:
                print(f"[DRY]  {pid}: 发现 {n} 个重复 id")
                continue
            backup = sfile.with_suffix(f".json.bak-{int(time.time())}")
            backup.write_text(text, encoding="utf-8")
            atomic_write_text(sfile, new_text)
            print(f"[修复] {pid}: 重分配 {n} 个重复 id（备份: {backup.name}）")

    # ===== SQLite 后端 =====
    db_file = workspace / "state.sqlite3"
    if db_file.exists():
        conn = sqlite3.connect(db_file)
        try:
            rows = conn.execute("SELECT id, state FROM projects").fetchall()
            for pid, state_text in rows:
                try:
                    new_text, n = _process_state_text(pid, state_text, dry_run)
                except Exception as e:
                    print(f"[跳过] sqlite:{pid}: 解析失败 {e}")
                    continue
                if n == 0:
                    print(f"[正常] sqlite:{pid}: 无重复 id")
                    continue
                total_fixed += n
                if dry_run:
                    print(f"[DRY]  sqlite:{pid}: 发现 {n} 个重复 id")
                    continue
                conn.execute(
                    "UPDATE projects SET state=? WHERE id=?", (new_text, pid)
                )
            if not dry_run:
                conn.commit()
        finally:
            conn.close()

    print(f"\n完成：共修复 {total_fixed} 个重复 id" + ("（dry-run，未写盘）" if dry_run else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="存量项目 draft id 去重")
    ap.add_argument("--workspace", type=Path, default=WORKSPACE_DIR)
    ap.add_argument("--dry-run", action="store_true", help="只报告不修改")
    args = ap.parse_args()
    return run(args.workspace, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
