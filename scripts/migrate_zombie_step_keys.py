# -*- coding: utf-8 -*-
"""一次性迁移：清除 data/skills/*.md frontmatter 中的三组僵尸键（B-4 补交）。

僵尸键 = flow 下步骤号键控声明 stage_executors / step_done_conditions /
step_short_titles：步骤号来源 flow.steps 通道已废除（声明即 fail-hard），
三键在生产链路无实际消费者（现存读取点均被 steps/dependencies 空声明闸住
= 死路径）。manifest_schema 对本版本声明输出 WARN 过渡告警，下一版本
升级为 fail-hard——本脚本负责存量清零。

默认 dry-run（只报告命中，不落盘）；--apply 真删。写入复用 frontmatter
render 链（yaml.safe_dump，与 migrate_manifests_to_frontmatter 同口径），
只动 frontmatter 块，正文逐字不动；flow 清空后整键移除。
--dir 指定目录（测试/演练用；默认 data/skills，兼容单文件与目录包形态）。

用法：
    python scripts/migrate_zombie_step_keys.py            # dry-run
    python scripts/migrate_zombie_step_keys.py --apply    # 执行迁移
"""
import argparse
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 与 manifest_schema.ZOMBIE_STEP_KEYS 同值复制（脚本不反向依赖运行时语义，
# 漂移由 tests/unit/test_zombie_step_keys.py 锁源断言钉死）
ZOMBIE_KEYS = ("stage_executors", "step_done_conditions", "step_short_titles")


def iter_skill_docs(d: Path) -> List[Path]:
    """单文件 <slug>.md 与目录包 <slug>/<slug>.md 双形态。"""
    files = sorted(d.glob("*.md"))
    for p in sorted(d.iterdir()):
        pkg = p / f"{p.name}.md"
        if p.is_dir() and pkg.exists():
            files.append(pkg)
    return files


def migrate_file(f: Path, apply: bool) -> Tuple[List[str], str]:
    """返回 (命中键清单, 跳过原因)。命中且 apply 时落盘。"""
    from src.video_agent.skill_runtime import frontmatter

    try:
        content = f.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        return [], f"读取失败: {e}"
    manifest, body, err = frontmatter.split_frontmatter(content)
    if err:
        return [], f"frontmatter 解析问题: {err}"
    if not isinstance(manifest, dict):
        return [], ""
    flow = manifest.get("flow")
    if not isinstance(flow, dict):
        return [], ""
    hit = [k for k in ZOMBIE_KEYS if k in flow]
    if not hit or not apply:
        return hit, ""
    new_flow = {k: v for k, v in flow.items() if k not in ZOMBIE_KEYS}
    new_manifest = {}
    for k, v in manifest.items():
        if k == "flow":
            if new_flow:  # flow 清空后整键移除
                new_manifest["flow"] = new_flow
        else:
            new_manifest[k] = v
    # 迁移后体检：错误级必须清零（WARN 级僵尸告警应随键移除消失）
    from src.video_agent.skill_runtime.manifest_schema import (
        split_issue_warnings, validate_manifest_data,
    )
    errors, _ = split_issue_warnings(validate_manifest_data(new_manifest))
    if errors:
        return hit, f"迁移后体检未过（未落盘）: {errors}"
    sep = "\n" if body and not body.startswith("\n") else ""
    text = frontmatter.render_frontmatter(new_manifest) + sep + body if new_manifest else body
    f.write_text(text, encoding="utf-8")
    return hit, ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="清除 Skill frontmatter 僵尸键（dry-run 默认，--apply 真删）")
    parser.add_argument("--apply", action="store_true",
                        help="真删（默认 dry-run 只报告）")
    parser.add_argument("--dir", default=str(ROOT / "data" / "skills"),
                        help="Skill 文档目录（默认 data/skills）")
    args = parser.parse_args()

    d = Path(args.dir)
    if not d.is_dir():
        print(f"[migrate_zombie_step_keys] FAIL: 目录不存在 {d}")
        return 1
    mode = "APPLY" if args.apply else "DRY-RUN"
    changed, clean = 0, 0
    for f in iter_skill_docs(d):
        hit, skip = migrate_file(f, args.apply)
        if skip:
            print(f"[migrate_zombie_step_keys] SKIP {f.name}: {skip}")
            continue
        if hit:
            changed += 1
            print(f"[migrate_zombie_step_keys] {mode} {f.name}: "
                  f"命中 {'/'.join(hit)}{'，已清除' if args.apply else '（dry-run 未落盘）'}")
        else:
            clean += 1
    print(f"[migrate_zombie_step_keys] done({mode}): {changed} hit, {clean} clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
