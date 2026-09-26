# -*- coding: utf-8 -*-
"""一次性迁移：给 9999 项目的 11 张「分镜表格图」卡补**引用记号 + 参考素材**。

## 为什么需要（问题 4 的存量部分）

Skill 的分镜表格图模板末尾要求列参考图（`Image 1: Character sheet for …`），
而 9999 那批卡是在「**无参考图**」指令下写的（用户当时决定跳过设定图），
提示词里一个引用记号都没有；后续 5 张改成「参考图：以随图上传的…为准」，
仍只是**大白话**——平台认不出那是引用，图块渲染不出来。

写口（`prompt_refs` / `storyboard_ops`）本批已修，本脚本只清**存量**：
按各 shot 的 `shotRefs` 生成规范引用段，并把对应设定图写进 `refAssets`。

## 生成内容（尾部追加，替换既有「参考图/无参考图」收尾句）

    参考图（本卡引用，逐一严格复刻）：
    - 角色设定图：<<<image_程心>>>、<<<image_艾AA（AA）>>>
    - 场景设定图：<<<image_星环号球形舱（木星轨道）>>>
    - 道具设定图：<<<image_白色薄片>>>

元素种类取自各 keyElement 组的 `elementType`（character/scene/prop），
未声明者归入「其他设定图」不臆测。

## 状态：**未执行**（2026-09-26 用户裁决「只修代码，存量不管」）

11 张卡经 dry-run 验证为**全部可解析**（11/11、0 残留），但用户裁决存量不动：
这批旧卡的提示词里仍是「参考图：以随图上传的…为准」这类**平台认不出的大白话**，
故其参考素材栏不会出现图块。用户如需清偿，跑本脚本即可（幂等：已含 `<<<`
的卡自动跳过）。apply 前请先停服务（同 `migrate_ref_assets_to_urls.py` 的注意项）。

用法（默认 dry-run 只报告，不落盘）：

    python scripts/archive/migrate_9999_sheet_refs.py
    python scripts/archive/migrate_9999_sheet_refs.py --apply

退出码：0 = 处理完毕；1 = 落盘失败。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.video_agent.state import storyboard_ops as ops  # noqa: E402

DB_PATH = ROOT / "workspace" / "state.sqlite3"
TARGET_PROJECT = "proj-1790358500-25465d26"

# 既有收尾句（两种形态）：只匹配**字面**「参考图：」/「无参考图：」起头的那一行。
# 教训（本脚本 dry-run 实测）：前缀字符一律可选时，模式退化成「任意含冒号的行」，
# 会把「【页眉】：粗体…」这类正文行整段截掉。故前缀必须**逐字required**。
_TAIL_RE = re.compile(r"\n*(?:无)?参考图[：:][^\n]*$", re.M)

_KIND_LABEL = {
    "character": "角色设定图",
    "scene": "场景设定图",
    "prop": "道具设定图",
}


def build_ref_section(state: Dict[str, Any], shot_refs: List[str]) -> Tuple[str, List[str]]:
    """按 shotRefs 生成引用段与参考图 URL 列表（找不到组的引用跳过并告知）。"""
    groups: Dict[str, List[str]] = {}
    urls: List[str] = []
    for ref in shot_refs:
        ke = ops.find_ref_group(state, ref)
        if ke is None:
            continue
        title = str(ke.get("title") or "")
        kind = str(ke.get("elementType") or "").strip().lower()
        label = _KIND_LABEL.get(kind, "其他设定图")
        groups.setdefault(label, [])
        if title not in groups[label]:
            groups[label].append(title)
        # 该元素的首张图像类设定图
        for d in ke.get("drafts") or []:
            img = d.get("imgUrl") or ""
            if img and img not in urls:
                urls.append(img)
                break
    if not groups:
        return "", []
    lines = ["参考图（本卡引用，逐一严格复刻）："]
    for label in ("角色设定图", "场景设定图", "道具设定图", "其他设定图"):
        if label not in groups:
            continue
        # 记号写**元素名**（剥容器前缀）——与 Skill 模板 `<<<image_场景>>>` 同形；
        # 平台侧 media_map 现已登记全称/剥前缀/括注主名三形态，两种写法都命中，
        # 但给模型看的是人读的名，不留 `Element_` 容器前缀。
        marks = "、".join(f"<<<image_{ops.strip_type_prefix(t)}>>>" for t in groups[label])
        lines.append(f"- {label}：{marks}")
    return "\n".join(lines), urls


def migrate_state(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """就地改单个项目 state，返回变更明细。"""
    changes: List[Dict[str, Any]] = []
    for gi, g in enumerate(state.get("shots") or [], 1):
        shot_refs = [str(r) for r in (g.get("shotRefs") or []) if str(r).strip()]
        if not shot_refs:
            continue
        section, urls = build_ref_section(state, shot_refs)
        if not section:
            continue
        for d in g.get("drafts") or []:
            if "运镜轨迹" not in (d.get("label") or ""):
                continue
            old_prompt = d.get("prompt") or ""
            if "<<<" in old_prompt:
                continue  # 已有记号，跳过（幂等）
            new_prompt = (_TAIL_RE.sub("", old_prompt).rstrip()
                          + "\n\n" + section + "\n")
            changes.append({
                "shot_index": gi,
                "label": d.get("label"),
                "old_tail": old_prompt[-80:],
                "new_tail": new_prompt[-160:],
                "refs_before": len(d.get("refAssets") or []),
                "refs_after": len(urls),
            })
            d["prompt"] = new_prompt
            # refAssets 走写口同一归一入口（草稿 id → URL）
            d["refAssets"] = ops.normalize_ref_assets(state, urls)
    return changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真写回（默认 dry-run）")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--project", default=TARGET_PROJECT)
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT id, state FROM projects WHERE id=?", (args.project,)).fetchone()
    if row is None:
        print(f"[FAIL] 找不到项目 {args.project}")
        return 1

    state = json.loads(row["state"])
    changes = migrate_state(state)

    print(f"项目 {args.project}（{state.get('project_name')}）"
          f"：{len(changes)} 张分镜表格图卡待补引用"
          f"（{'APPLY' if args.apply else 'DRY-RUN'}）\n")
    for c in changes:
        print(f"  Shot{c['shot_index']:02d} [{c['label']}] "
              f"refAssets {c['refs_before']} → {c['refs_after']}")
        print(f"      新尾部：{c['new_tail']!r}")

    if args.apply and changes:
        con.execute("UPDATE projects SET state=? WHERE id=?",
                    (json.dumps(state, ensure_ascii=False), args.project))
        con.commit()
        print(f"\n已写回 {len(changes)} 张卡")
    elif changes:
        print("\n（dry-run：未写回）")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
