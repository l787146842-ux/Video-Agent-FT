"""画布上游增量同步：只处理上游变化的文件，本地 patch 自动保留。

背景：画布源码 vendored 在 `vendors/infinite-canvas/web`，本地有登记 patch
（headless / basename / 配色 / BASE_URL）。整目录覆盖会冲掉这些改动，逐文件手抄又会漏。
本工具用「双侧 sha256 基线」判定每个文件的归属，只复制 / 删除判定为变化的文件。

用法：
    # 首次建立基线（用一份纯净上游源码，例如刚解压的新版本）
    python scripts/sync_canvas_upstream.py --init-baseline <上游目录> --version v0.20.0

    # 只看差异，不动文件
    python scripts/sync_canvas_upstream.py --check --upstream <新上游目录>

    # 增量应用（冲突时默认整体中止，不写任何文件）
    python scripts/sync_canvas_upstream.py --apply --upstream <新上游目录>

判定规则（base = 上次同步记录）：
    上游没变                  -> keep      保留本地（含 patch）
    本地没变 & 上游变了       -> update    覆盖为新上游
    两边都变                  -> conflict  不覆盖，输出 diff，退出码 1
    上游新增 & 本地不存在     -> add       复制
    上游删除 & 本地没变       -> delete    删除
    excluded（登记有意不搬）  -> skip      永远跳过
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VENDOR = ROOT / "vendors" / "infinite-canvas"
DEFAULT_STATE = DEFAULT_VENDOR / ".canvas-sync.json"

EXCLUDE_DIRS = {"node_modules", "dist", ".git"}
# 锁文件与构建缓存属本地生成物：不参与上游同步（package.json 变了会提示重装依赖）
SKIP_NAMES = {"tsconfig.tsbuildinfo", ".DS_Store",
              "package-lock.json", "pnpm-lock.yaml", "bun.lock"}

Walk = Dict[str, str]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_web(root: Path) -> Path:
    """接受「画布仓库根目录」或「web 目录」两种入参。"""
    if (root / "web" / "package.json").is_file():
        return root / "web"
    if (root / "package.json").is_file() and (root / "index.html").is_file():
        return root
    raise SystemExit(f"[sync-canvas] 不是画布源码目录（找不到 web/package.json）: {root}")


def walk(web: Path) -> Walk:
    result: Walk = {}
    for path in web.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(web)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if path.name in SKIP_NAMES:
            continue
        result[rel.as_posix()] = sha256(path)
    return result


def resolve_state_path(args: argparse.Namespace) -> Path:
    """状态/冲突目录默认跟随 --vendor：换目录演练不会污染真实基线。"""
    return Path(args.state) if args.state else Path(args.vendor) / ".canvas-sync.json"


def resolve_conflict_dir(args: argparse.Namespace) -> Path:
    return Path(args.conflict_dir) if args.conflict_dir else Path(args.vendor) / ".sync-conflicts"


def load_state(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(
            f"[sync-canvas] 缺少同步基线 {path}；先执行 --init-baseline <纯净上游目录>")
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def classify(rel: str, up_sha: str, loc_sha: Optional[str], base: Optional[dict],
             excluded: set, patches: set) -> str:
    """单文件判定。patches 优先于 sha 比较：登记 patch 文件永不被自动覆盖。"""
    if rel in excluded:
        return "excluded"
    if base is None:
        if loc_sha is None:
            return "add"
        return "same" if loc_sha == up_sha else "conflict"
    if up_sha == base.get("upstream"):
        return "keep"
    if loc_sha is None:
        return "conflict"
    if loc_sha == up_sha:
        return "same"
    # 登记 patch 文件：上游同文件也改了 -> 必须人工重做，绝不自动覆盖
    if rel in patches:
        return "conflict"
    # 未登记本地改动（非 patch 文件被手改过）同样按冲突处理，保守不覆盖
    return "update" if loc_sha == base.get("local") else "conflict"


def dump_conflict(rel: str, vendor_web: Path, upstream_web: Path, out_dir: Path) -> Optional[Path]:
    local, upstream = vendor_web / rel, upstream_web / rel
    if not local.is_file() or not upstream.is_file():
        return None
    try:
        left = local.read_text(encoding="utf-8")
        right = upstream.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    diff = "".join(difflib.unified_diff(
        left.splitlines(True), right.splitlines(True),
        fromfile=f"local/{rel}", tofile=f"upstream/{rel}", n=3))
    if not diff:
        return None
    dest = out_dir / (rel.replace("/", "__") + ".diff")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(diff, encoding="utf-8")
    return dest


def cmd_init(args: argparse.Namespace) -> int:
    upstream_web = resolve_web(Path(args.init_baseline).resolve())
    vendor_web = Path(args.vendor).resolve() / "web"
    if not (vendor_web / "package.json").is_file():
        raise SystemExit(f"[sync-canvas] vendored 画布缺失: {vendor_web}")
    path = resolve_state_path(args)
    if path.is_file() and not args.force:
        raise SystemExit(f"[sync-canvas] 基线已存在（加 --force 覆盖）: {path}")

    upstream, local = walk(upstream_web), walk(vendor_web)
    baseline = {f"web/{rel}": {"upstream": sha} for rel, sha in upstream.items()}
    patches, excluded = [], []
    for rel, sha in upstream.items():
        loc = local.get(rel)
        key = f"web/{rel}"
        if loc is None:
            excluded.append(key)
        else:
            baseline[key]["local"] = loc
            if loc != sha:
                patches.append(key)
    state = {
        "schema": 1,
        "upstream": {"version": args.version or "unknown", "synced_at": date.today().isoformat()},
        "baseline": baseline,
        "local_patches": sorted(patches),
        "excluded": sorted(excluded),
    }
    save_state(path, state)
    print(f"[sync-canvas] 基线已建立: {path}")
    print(f"  上游文件 {len(upstream)}，本地 patch {len(patches)}，有意未搬入 {len(excluded)}")
    for rel in patches:
        print(f"    patch  {rel}")
    for rel in excluded:
        print(f"    skip   {rel}")
    return 0


def plan(args: argparse.Namespace) -> Tuple[dict, Dict[str, list]]:
    upstream_web = resolve_web(Path(args.upstream).resolve())
    vendor_web = Path(args.vendor).resolve() / "web"
    state_file = resolve_state_path(args)
    state = load_state(state_file)
    baseline = state.get("baseline", {})
    excluded = set(state.get("excluded", []))
    patches = set(state.get("local_patches", []))

    upstream, local = walk(upstream_web), walk(vendor_web)
    buckets: Dict[str, list] = {k: [] for k in
                                ("add", "update", "delete", "keep", "same", "conflict", "excluded")}

    for rel, up_sha in upstream.items():
        key = f"web/{rel}"
        action = classify(key, up_sha, local.get(rel), baseline.get(key), excluded, patches)
        buckets[action].append(key)

    for key, base in baseline.items():
        if key in excluded or not key.startswith("web/"):
            continue
        rel = key[len("web/"):]
        if rel in upstream:
            continue
        loc = local.get(rel)
        if loc is None:
            continue
        buckets["delete" if loc == base.get("local") else "conflict"].append(key)

    return {"upstream_web": upstream_web, "vendor_web": vendor_web,
            "state": state, "state_path": state_file}, buckets


def report(buckets: Dict[str, list], state_path: Path) -> None:
    labels = {
        "add": "新增（复制）", "update": "更新（本地未改）", "delete": "删除（本地未改）",
        "keep": "保留本地（含 patch）", "same": "内容已一致",
        "conflict": "冲突（未覆盖）", "excluded": "登记跳过",
    }
    print(f"[sync-canvas] 基线: {state_path}")
    for key in ("add", "update", "delete", "conflict", "keep", "same", "excluded"):
        items = buckets[key]
        if not items:
            continue
        print(f"  {labels[key]} {len(items)}")
        for rel in items[:40]:
            print(f"    {rel}")
        if len(items) > 40:
            print(f"    ... 其余 {len(items) - 40} 个省略")


def cmd_check(args: argparse.Namespace) -> int:
    context, buckets = plan(args)
    context["state_path"] = context["state_path"]
    report(buckets, context["state_path"])
    patches = set(context["state"].get("local_patches", []))
    hits = [rel for rel in buckets["conflict"] if rel in patches]
    if hits:
        print("  [注意] 以下登记 patch 与上游同文件都有改动，需人工重做：")
        for rel in hits:
            print(f"    {rel}")
    return 1 if buckets["conflict"] else 0


def cmd_apply(args: argparse.Namespace) -> int:
    context, buckets = plan(args)
    state, state_path = context["state"], context["state_path"]
    upstream_web, vendor_web = context["upstream_web"], context["vendor_web"]
    conflicts = buckets["conflict"]

    if conflicts and not args.keep_going:
        report(buckets, state_path)
        print("[sync-canvas] 存在冲突，已中止（未写入任何文件）。"
              "先 --check 查看，处理冲突后重试；或加 --keep-going 只应用无冲突部分。")
        return 1

    conflict_dir = resolve_conflict_dir(args)
    written = 0
    for key in buckets["add"] + buckets["update"]:
        rel = key[len("web/"):]
        dest = vendor_web / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(upstream_web / rel, dest)
        state["baseline"][key] = {"upstream": sha256(upstream_web / rel), "local": sha256(dest)}
        written += 1
    for key in buckets["delete"]:
        (vendor_web / key[len("web/"):]).unlink()
        state["baseline"].pop(key, None)
        written += 1
    for key in buckets["keep"]:
        loc = vendor_web / key[len("web/"):]
        if loc.is_file():
            state["baseline"].setdefault(key, {})["local"] = sha256(loc)
    for key in buckets["same"]:
        state["baseline"][key] = {"upstream": sha256(upstream_web / key[len("web/"):]),
                                  "local": sha256(vendor_web / key[len("web/"):])}

    if conflicts:
        conflict_dir.mkdir(parents=True, exist_ok=True)
        for key in conflicts:
            dump_conflict(key[len("web/"):], vendor_web, upstream_web, conflict_dir)

    state["upstream"] = {"version": args.version or state.get("upstream", {}).get("version", "unknown"),
                         "synced_at": date.today().isoformat()}
    save_state(state_path, state)

    report(buckets, state_path)
    print(f"[sync-canvas] 已写入 {written} 个文件")
    if "web/package.json" in buckets["add"] + buckets["update"]:
        print("[sync-canvas] 依赖清单有变：请执行 "
              "npm --prefix vendors/infinite-canvas/web install 更新锁文件")
    if conflicts:
        print(f"[sync-canvas] 冲突 diff 已输出到: {conflict_dir}")
        return 1
    print("[sync-canvas] 完成；建议接着执行 python scripts/build_canvas.py")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="画布上游增量同步（保留本地 patch）")
    parser.add_argument("--vendor", default=str(DEFAULT_VENDOR), help="vendored 画布根目录")
    parser.add_argument("--state", default="", help="同步基线文件（默认 <vendor>/.canvas-sync.json）")
    parser.add_argument("--version", default="", help="记录上游版本号（如 v0.21.0）")
    parser.add_argument("--conflict-dir", default="",
                        help="冲突 diff 输出目录（默认 <vendor>/.sync-conflicts，已 gitignore）")
    parser.add_argument("--keep-going", action="store_true", help="有冲突时仍应用无冲突部分")
    parser.add_argument("--force", action="store_true", help="--init-baseline 覆盖既有基线")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init-baseline", metavar="UPSTREAM_DIR", help="用纯净上游建立基线")
    group.add_argument("--check", action="store_true", help="只报告差异")
    group.add_argument("--apply", action="store_true", help="增量应用")
    parser.add_argument("--upstream", default="", help="新上游目录（--check / --apply 必填）")
    args = parser.parse_args()

    if args.init_baseline:
        return cmd_init(args)
    if not args.upstream:
        parser.error("--check / --apply 需要 --upstream <目录>")
    return cmd_check(args) if args.check else cmd_apply(args)


if __name__ == "__main__":
    sys.exit(main())
