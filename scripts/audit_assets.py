"""资产只读盘点（任务 #9 E-3：workspace/assets/ 生命周期治理观察项）。

用途：
- 扫描 workspace/assets/，对每个文件统计引用来源数：
  * 项目状态：workspace/projects/*/state.json 与 workspace/state.sqlite3
    projects.state（任务 #24 后项目状态唯一事实源为 sqlite，旧 JSON 镜像
    仅回落路径保留，两者都扫以免漏判）；
  * 生成任务表：workspace/state.sqlite3 kv['generation_tasks'] 与停写保留
    的 data/generation_tasks.json（result_url / result.images / video_url
    等字段的落盘 URL）；
  * 快照：workspace/snapshots/**/*.json（快照内嵌完整 state 与消息）。
- 输出报表：总数、按项目引用数、孤儿清单（无任何引用的文件）。

口径：
- dry-run 唯一模式：只读报告，绝不删除任何文件（删除能力本期不做）。
- 引用判定 = 资产文件名以 /workspace/assets/<文件名> 形式出现在来源文本中；
  来源按「文档」计数（每个 state/快照/任务表文档最多记 1 次引用）。
- 引用来源分类仅按文档所在路径划分：projects 目录或 projects.state 行记
  「项目状态」；snapshots 目录记「快照」；任务表文档记「任务表」。

退役条件（治理要求）：
- 本脚本为观察项（报表命令），不挂 acceptance 硬门禁，避免孤儿误报阻塞；
- 当资产 TTL/引用计数自动清理机制上线，且孤儿清理有独立决策与执行通道后，
  本脚本并入该机制或退役；连续两个版本周期无人使用亦可直接退役。

用法：
    python scripts/audit_assets.py            # 以仓库根为工作区根
    python scripts/audit_assets.py --root DIR # 指定工作区根（测试/演练用）
退出码恒为 0（只读观察项；目录缺失只告警不报错）。
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_ASSET_URL = "/workspace/assets/"


def _read_text_safe(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _collect_sources(root: Path):
    """收集引用来源文档：返回 (label, text) 列表。

    label 用于报表分类：「项目状态」/「任务表」/「快照:<项目目录名>」。
    """
    sources = []
    ws = root / "workspace"

    # 1) 项目状态：旧 JSON 镜像（回落路径）
    for p in sorted((ws / "projects").glob("*/state.json")):
        sources.append(("项目状态", _read_text_safe(p)))

    # 2) 项目状态 + 生成任务表：sqlite kv/projects 表（唯一事实源）
    db = ws / "state.sqlite3"
    if db.exists():
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if "projects" in tables:
                    for pid, state in conn.execute("SELECT id, state FROM projects"):
                        if isinstance(state, str) and state:
                            sources.append((f"项目状态:{pid}", state))
                if "kv" in tables:
                    row = conn.execute(
                        "SELECT value FROM kv WHERE key='generation_tasks'").fetchone()
                    if row and row[0]:
                        sources.append(("任务表", row[0]))
            finally:
                conn.close()
        except sqlite3.Error as e:
            print(f"[audit_assets] sqlite 读取失败（跳过）: {e}")

    # 3) 停写保留的旧任务表文件（只读兜底口径，存在即扫）
    legacy = root / "data" / "generation_tasks.json"
    if legacy.exists():
        sources.append(("任务表", _read_text_safe(legacy)))

    # 4) 快照（按项目目录归类）
    snap_root = ws / "snapshots"
    if snap_root.exists():
        for p in sorted(snap_root.rglob("*.json")):
            try:
                proj = p.relative_to(snap_root).parts[0]
            except (ValueError, IndexError):
                proj = "_"
            sources.append((f"快照:{proj}", _read_text_safe(p)))
    return sources


def audit(root: Path) -> dict:
    """盘点入口：返回报表结构（纯只读）。"""
    assets_dir = root / "workspace" / "assets"
    files = sorted(
        (p for p in assets_dir.iterdir() if p.is_file()),
        key=lambda p: p.name.lower(),
    ) if assets_dir.exists() else []

    sources = _collect_sources(root)

    ref_count: Counter = Counter()          # 文件名 -> 引用文档数
    ref_labels: dict = {}                   # 文件名 -> 引用来源 label 列表
    proj_refs: Counter = Counter()          # 项目目录名 -> 引用的资产数（文档去重内不去重，按命中计）
    for f in files:
        needle = _ASSET_URL + f.name
        labels = []
        for label, text in sources:
            if not text or needle not in text:
                continue
            labels.append(label)
            if label.startswith("快照:"):
                proj_refs[label.split(":", 1)[1]] += 1
        ref_count[f.name] = len(labels)
        ref_labels[f.name] = labels

    orphans = [f.name for f in files if ref_count[f.name] == 0]
    return {
        "root": str(root),
        "total": len(files),
        "orphan_count": len(orphans),
        "orphans": orphans,
        "proj_refs": dict(proj_refs),
        "ref_labels": ref_labels,
        "files": [(f.name, f.stat().st_size) for f in files],
    }


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def render(report: dict) -> str:
    lines = []
    lines.append("=" * 62)
    lines.append("[audit_assets] workspace/assets/ 资产盘点（只读 dry-run，不删除）")
    lines.append(f"工作区根: {report['root']}")
    lines.append(f"资产总数: {report['total']}")
    lines.append(f"孤儿资产（无任何引用）: {report['orphan_count']}")
    lines.append("-" * 62)
    lines.append("按快照项目引用数（快照文档内命中的资产计数）:")
    if report["proj_refs"]:
        for proj, n in sorted(report["proj_refs"].items(), key=lambda kv: -kv[1]):
            lines.append(f"  {proj}: {n}")
    else:
        lines.append("  （无）")
    lines.append("-" * 62)
    lines.append("被引用资产（引用来源）:")
    referenced = [
        (name, labels) for name, labels in report["ref_labels"].items() if labels
    ]
    if referenced:
        for name, labels in referenced:
            uniq = sorted(set(labels))
            lines.append(f"  {name}  x{len(labels)}  <- {'; '.join(uniq)}")
    else:
        lines.append("  （无）")
    lines.append("-" * 62)
    lines.append(f"孤儿清单（{report['orphan_count']} 个）:")
    size_map = dict(report["files"])
    if report["orphans"]:
        for name in report["orphans"]:
            size = size_map.get(name, 0)
            lines.append(f"  {name}  ({_fmt_size(size)})")
    else:
        lines.append("  （无）")
    lines.append("=" * 62)
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="workspace/assets/ 只读盘点")
    parser.add_argument("--root", default=str(ROOT), help="工作区根目录（默认仓库根）")
    args = parser.parse_args(argv)
    report = audit(Path(args.root).resolve())
    print(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
