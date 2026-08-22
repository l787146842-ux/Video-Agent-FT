# -*- coding: utf-8 -*-
"""任务#5：外置 JSON sidecar → Skill 文档头部 frontmatter 一次性迁移脚本。

机械迁移规则（忠实搬运，不做内容修改）：
- data/skills_manifests/<slug>.json 的全部声明原样迁入
  data/skills/<slug>.md 头部 YAML frontmatter（`---` 包裹块）；
- 流程步骤抄本通道废除（用户裁决）：flow.steps / flow.step_stages /
  flow.dependencies 三键一律不迁移——正文 planner 是唯一流程源；
  flow 其余键（spec_wizard/spec_gate/stage_executors/stages 等）保留；
  flow 剔空后整键移除；
- 插件包约定新增键：补 version: "1.0"（tools_required 不写，
  具体声明值由后续任务按平台工具注册表填写）。
迁移产物双重复检：回读 frontmatter 与预期声明全等 + schema 体检零问题。

用法（已归档入 scripts/archive/，root = parents[2]）：
  python scripts/archive/migrate_manifests_to_frontmatter.py             # 执行迁移
  python scripts/archive/migrate_manifests_to_frontmatter.py --dry-run   # 只报告不落盘
  python scripts/archive/migrate_manifests_to_frontmatter.py --check     # 校验迁移完成度
  --force                                                         # 覆盖已有 frontmatter
"""
import argparse
import copy
import json
import sys
from pathlib import Path

# 归档后脚本位于 scripts/archive/，仓库 root = parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.video_agent.skill_runtime import frontmatter  # noqa: E402
from src.video_agent.skill_runtime.manifest_schema import (  # noqa: E402
    DEPRECATED_FLOW_KEYS,
    validate_manifest_data,
)


def migrate_data(data: dict) -> dict:
    """机械翻译单个 JSON 声明 → frontmatter 声明（剔除废除键，补 version）。"""
    out = copy.deepcopy(data)
    flow = out.get("flow")
    if isinstance(flow, dict):
        for k in DEPRECATED_FLOW_KEYS:
            flow.pop(k, None)
        if not flow:
            out.pop("flow", None)
    out.setdefault("version", "1.0")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="JSON sidecar → frontmatter 一次性迁移（任务#5）")
    ap.add_argument("--dry-run", action="store_true", help="只报告不落盘")
    ap.add_argument("--check", action="store_true",
                    help="校验是否已迁移完成（未完成退出码 1）")
    ap.add_argument("--force", action="store_true",
                    help="目标 md 已有 frontmatter 时覆盖（默认拒绝）")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    src_dir = root / "data" / "skills_manifests"
    dst_dir = root / "data" / "skills"
    if not src_dir.is_dir():
        print("[migrate_manifests_to_frontmatter] 源目录不存在"
              f"（{src_dir}）——视为迁移已完成并清理")
        return 0 if args.check else 2

    done, pending, invalid = [], [], []
    for f in sorted(src_dir.glob("*.json")):
        slug = f.stem
        md = frontmatter.resolve_doc_path(slug, directory=dst_dir)
        if md is None:
            invalid.append(f"{f.name}: 对应 Skill 文档不存在，跳过")
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            invalid.append(f"{f.name}: JSON 解析失败 {e}")
            continue
        if not isinstance(data, dict):
            invalid.append(f"{f.name}: 根节点不是 JSON 对象，跳过")
            continue
        expected = migrate_data(data)
        issues = validate_manifest_data(expected)
        if issues:
            invalid.append(f"{f.name}: 迁移产物 schema 复检失败 {'; '.join(issues)}")
            continue
        current, _body, _err = frontmatter.split_frontmatter(
            md.read_text(encoding="utf-8"))
        if args.check:
            if current == expected:
                done.append(f.name)
            else:
                pending.append(f.name)
            continue
        if current and not args.force:
            invalid.append(f"{f.name}: {md.name} 已有 frontmatter"
                           "（--force 覆盖）")
            continue
        if current != expected:
            pending.append((slug, expected, f.name))
        else:
            done.append(f.name)

    if args.check:
        for name in done:
            print(f"[check] OK      {name}")
        for name in pending:
            print(f"[check] PENDING {name}")
        for msg in invalid:
            print(f"[check] SKIP    {msg}")
        if pending or invalid:
            print(f"[migrate_manifests_to_frontmatter --check] FAIL - 未迁完："
                  f"{len(pending)} 待迁移, {len(invalid)} 跳过")
            return 1
        print(f"[migrate_manifests_to_frontmatter --check] PASS - "
              f"{len(done)} 个声明均已迁入 frontmatter")
        return 0

    tag = "[dry-run] " if args.dry_run else ""
    for slug, expected, name in pending:
        print(f"{tag}WILL MIGRATE {name} → data/skills/{slug}.md frontmatter")
        if not args.dry_run:
            frontmatter.write_manifest(slug, expected, directory=dst_dir)
            # 双重复检：回读全等 + schema 体检零问题
            readback = frontmatter.load_manifest(slug, directory=dst_dir)
            assert readback == expected, f"{name}: 回读与预期不一致"
            assert not validate_manifest_data(readback), \
                f"{name}: 回读声明 schema 体检未过"
    for name in done:
        print(f"{tag}UNCHANGED    {name}")
    for msg in invalid:
        print(f"{tag}SKIP         {msg}")
    if invalid:
        return 1
    print(f"[migrate_manifests_to_frontmatter] {tag}migrated={len(pending)} "
          f"unchanged={len(done)} skipped={len(invalid)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
