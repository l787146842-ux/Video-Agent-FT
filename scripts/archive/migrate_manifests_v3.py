# -*- coding: utf-8 -*-
"""B5 预备：manifest v2→v3 幂等迁移脚本（任务#34 B1 交付；实际执行归 B5）。

机械翻译规则（只加不删，重复运行结果不变）：
- 补 schema_version: 3（缺省视为 v2 兼容 → 迁移后显式钉 3）；
- flow.script_required == true → requires_inputs 追加
  {"type": "script", "required": true}（已含 type=script 项则不重复追加）；
- pause.stage_pause == true → pause_points 追加两个锚点
  trigger=storyboard_structure_ready 与 trigger=first_generation_call
  （id 与 trigger 同名，幂等去重按 id）。
迁移产物经 manifest_schema.validate_manifest_data 复检（fail-closed 兜底；
复检前剔除已废除的 flow.steps/step_stages/dependencies 三键，与 frontmatter
合一后的 schema 口径一致）。

用法（已归档入 scripts/archive/，root = parents[2]；默认目录
data/skills_manifests 已随任务#5 frontmatter 合一删除，仅 --dir 演练可用）：
  python scripts/archive/migrate_manifests_v3.py             # 执行迁移（默认 data/skills_manifests）
  python scripts/archive/migrate_manifests_v3.py --dry-run   # 只报告将变更的文件，不落盘
  python scripts/archive/migrate_manifests_v3.py --check     # 校验是否已全部迁移（未迁完退出码 1）
  --dir <路径>                                        # 指定 manifest 目录（测试/演练用）
"""
import argparse
import copy
import json
import sys
from pathlib import Path

# 归档后脚本位于 scripts/archive/，仓库 root = parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.video_agent.skill_runtime.manifest_schema import (
    DEPRECATED_FLOW_KEYS,
    validate_manifest_data,
)

# stage_pause 机械翻译的两个锚点（id 与 trigger 同名，幂等去重键 = id）
V3_ANCHOR_PAUSE_POINTS = (
    {"id": "storyboard_structure_ready", "trigger": "storyboard_structure_ready"},
    {"id": "first_generation_call", "trigger": "first_generation_call"},
)


def migrate_data(data: dict) -> "dict | None":
    """机械翻译单个 manifest（只加不删）；已迁移/无翻译点返回 None。"""
    out = copy.deepcopy(data)
    changed = False
    if out.get("schema_version") != 3:
        out["schema_version"] = 3
        changed = True
    flow = out.get("flow") or {}
    if isinstance(flow, dict) and flow.get("script_required") is True:
        ri = out.setdefault("requires_inputs", [])
        if isinstance(ri, list) and not any(
            isinstance(x, dict) and x.get("type") == "script" for x in ri
        ):
            ri.append({"type": "script", "required": True})
            changed = True
    pause = out.get("pause") or {}
    if isinstance(pause, dict) and pause.get("stage_pause") is True:
        pps = out.setdefault("pause_points", [])
        if isinstance(pps, list):
            ids = {x.get("id") for x in pps if isinstance(x, dict)}
            for anchor in V3_ANCHOR_PAUSE_POINTS:
                if anchor["id"] not in ids:
                    pps.append(dict(anchor))
                    changed = True
    return out if changed else None


def _dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _strip_deprecated_flow(data: dict) -> dict:
    """复检用副本：剔除已废除的流程抄本键（历史 JSON 仍含这三键，
    声明即 fail-hard；本脚本产物归 JSON 时代，复检口径对齐 frontmatter）。"""
    out = copy.deepcopy(data)
    flow = out.get("flow")
    if isinstance(flow, dict):
        for k in DEPRECATED_FLOW_KEYS:
            flow.pop(k, None)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="manifest v2→v3 幂等迁移")
    ap.add_argument("--dry-run", action="store_true", help="只报告不落盘")
    ap.add_argument("--check", action="store_true", help="校验是否已迁移（未迁完退出码 1）")
    ap.add_argument("--dir", default=None, help="manifest 目录（默认 data/skills_manifests）")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    target = Path(args.dir) if args.dir else root / "data" / "skills_manifests"
    if not target.is_dir():
        # 默认目录已随任务#5 frontmatter 合一删除：视为迁移已完成
        print(f"[migrate_manifests_v3] 目录不存在（{target}）——视为迁移已完成")
        return 0 if args.check else 2

    pending, skipped, invalid = [], [], []
    for f in sorted(target.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            invalid.append(f"{f.name}: 解析失败 {e}")
            continue
        if not isinstance(data, dict):
            invalid.append(f"{f.name}: 根节点不是 JSON 对象，跳过")
            continue
        migrated = migrate_data(data)
        if migrated is None:
            skipped.append(f.name)
            continue
        issues = validate_manifest_data(_strip_deprecated_flow(migrated))
        if issues:
            invalid.append(f"{f.name}: 迁移产物 schema 复检失败 {'; '.join(issues)}")
            continue
        pending.append((f, migrated))

    if args.check:
        for name in skipped:
            print(f"[check] OK      {name}")
        for f, _ in pending:
            print(f"[check] PENDING {f.name}")
        for msg in invalid:
            print(f"[check] SKIP    {msg}")
        if pending or invalid:
            print(f"[migrate_manifests_v3 --check] FAIL - 未迁完："
                  f"{len(pending)} 待迁移, {len(invalid)} 跳过")
            return 1
        print(f"[migrate_manifests_v3 --check] PASS - {len(skipped)} 个 manifest 均已迁移")
        return 0

    tag = "[dry-run] " if args.dry_run else ""
    for f, _ in pending:
        print(f"{tag}WILL MIGRATE {f.name}")
    for name in skipped:
        print(f"{tag}UNCHANGED    {name}")
    for msg in invalid:
        print(f"{tag}SKIP         {msg}")
    if not args.dry_run:
        for f, migrated in pending:
            f.write_text(_dump(migrated), encoding="utf-8")
    print(f"[migrate_manifests_v3] {tag}migrated={len(pending)} "
          f"unchanged={len(skipped)} skipped={len(invalid)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
