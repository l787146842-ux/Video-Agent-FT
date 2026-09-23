# -*- coding: utf-8 -*-
"""存量数据处置脚本（2026-09-23 批6，事故 2222/3333）。

## 安全纪律（必读）

**默认 dry-run**：不加 `--apply` 只读扫描并打印将要做的变更，**不写库**。
加 `--apply` 才真正落盘（落盘前自动整库备份到 `workspace/state.sqlite3.bak-<ts>`）。

**为什么必须人工确认**：这两个项目是用户真实工作台，
不是测试数据；错误迁移会毁掉已完成的设计工作。
故脚本只做**无损/可证明安全**的动作，有争议的一律只报告、不动手。

## 处置项（逐条给判据）

### A. 2222：删除 KE 组内 3 张重复音频卡（无损）
`Element_主要角色` 组里有 `BGM-深空主题`/`BGM-紧张脉冲`/`旁白-一年前时间提示`
三张 audio 卡，而这三张**在 `Audio_配乐轨` 组里各有一份同 label 同 tag 的副本**
（实跑：模型先误用 `group_id="current"` 落错到 KE 组，发现后重建了一份，
但平台当时**没有删单卡工具**故重复留存）。同一内容两份 ⇒ 删 KE 组那份是纯去重。

### B. 3333：补建 8 张角色音色卡到对应 KE 组（补建，非移动）
Skill 明文（`<storyboard_key_elements>`）：「角色的声音特征（音色/语气/情绪基调）
单独登记为 **key_element_audio**，与角色元素绑定」。现状：音色只写在
`Audio_声-<角色>` 组的 desc 里，**KE 组内 audio 卡 = 0**（全库 audio 卡 = 0）。
按 D-1/§3.6：**必须走补建**（无卡可移）。补建后：
- KE 角色组内出现 `mediaType=audio, audioType=voice` 的卡（与渲染层
  `isVoiceCard` 同口径，前端渲染成半尺寸音色小卡）；
- 原 `Audio_声-<角色>` 组保留（不删——删了会丢 desc 里的音色描述；
  是否清理属用户裁决，见报告 §存量处置选项）。

### C. 只报告、不动手的项（有争议，需用户裁决）
- **2222 的 10 张 video KE 卡**：D-1 说「KE 阶段只建分组不建卡」，
  但这 10 张卡的 `desc` 里存着角色/场景/道具的**设定描述**（模型当初把描述
  写在卡上而非组上）。直接删会丢内容 ⇒ 脚本只统计并打印，不删。
- **2222 的三个粗组**（主要角色/关键场景/关键道具）：Q1-B 要求一元素一组，
  但拆分需要把每个元素从组里「认领」出来，属重建设计，非机械迁移。
- **3333 的 15 张 shot 内 image 卡**（运镜轨迹示意图）：按批4 矩阵
  `shot` 类目只允许 video。但它是**用户已生成的提示词资产**，
  删除即丢内容 ⇒ 只报告。

用法：
    python scripts/migrate_storyboard_existing.py                # dry-run（默认）
    python scripts/migrate_storyboard_existing.py --apply        # 落盘（自动备份）
"""
import argparse
import datetime
import json
import pathlib
import shutil
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "workspace" / "state.sqlite3"

PROJ_2222 = "proj-1790091531-97d20b2d"
PROJ_3333 = "proj-1790092267-a9abcb25"
PROJ_NAMES = {PROJ_2222: "2222", PROJ_3333: "3333"}

# A 项：2222 KE 组内待去重的三张音频卡 label（在 Audio_配乐轨 有同 label 副本）
DUPLICATE_AUDIO_LABELS = {
    "BGM-深空主题", "BGM-紧张脉冲", "旁白-一年前时间提示",
}

# B 项：3333 角色音色卡的来源组标题前缀（Audio_声-<角色>）与目标 KE 组名映射
VOICE_GROUP_PREFIX = "声-"


def _load(conn, pid):
    row = conn.execute("select state from projects where id=?", (pid,)).fetchone()
    if not row:
        return None
    return json.loads(row[0])


def _ascii_safe(text):
    return "".join(c if c.isascii() else "?" for c in str(text))


def _group_title(g):
    return str(g.get("title") or "")


def plan_2222(state):
    """A 项：找出 KE 组内与 Audio_配乐轨 重复的音频卡。"""
    targets = []
    audio_labels = set()
    for g in (state.get("audioItems") or []):
        for d in (g.get("drafts") or []):
            lb = str(d.get("label") or "").strip()
            if lb:
                audio_labels.add(lb)
    for g in (state.get("keyElements") or []):
        for d in (g.get("drafts") or []):
            lb = str(d.get("label") or "").strip()
            mt = str(d.get("mediaType") or "").strip().lower()
            if mt != "audio":
                continue
            if lb in DUPLICATE_AUDIO_LABELS and lb in audio_labels:
                targets.append({
                    "group": _group_title(g),
                    "draft_id": d.get("id"),
                    "label": lb,
                    "reason": "与 audioItems 类目同 label 重复（纯去重，无损）",
                })
    return targets


def plan_3333(state):
    """B 项：为每个角色 KE 组补建音色卡（从 Audio_声-<角色> 的 desc 取音色描述）。"""
    targets = []
    # 先建「角色名 -> 音色 desc」表
    voice_by_name = {}
    for g in (state.get("audioItems") or []):
        title = _group_title(g)
        if VOICE_GROUP_PREFIX not in title:
            continue
        name = title.split(VOICE_GROUP_PREFIX, 1)[-1].strip()
        desc = str(g.get("desc") or "").strip()
        if name and desc:
            voice_by_name[name] = desc

    for g in (state.get("keyElements") or []):
        title = _group_title(g)
        # 组名形如 Element_<元素名>
        name = title.split("_", 1)[-1].strip() if "_" in title else title
        if name not in voice_by_name:
            continue
        has_voice = any(
            str(d.get("mediaType") or "").lower() == "audio"
            for d in (g.get("drafts") or []))
        if has_voice:
            continue          # 幂等：已有音色卡则不重复补建
        targets.append({
            "group": title,
            "group_id": g.get("id"),
            "label": f"{name} 音色",
            "mediaType": "audio",
            "audioType": "voice",
            "desc": voice_by_name[name],
            "reason": "Skill 明文 key_element_audio 与角色元素绑定（补建，非移动）",
        })
    return targets


def report_only_2222(state):
    """C 项：只统计不动手的项。"""
    out = []
    video_cards = []
    for g in (state.get("keyElements") or []):
        for d in (g.get("drafts") or []):
            if str(d.get("mediaType") or "").lower() == "video":
                video_cards.append((_group_title(g), str(d.get("label") or "")))
    out.append(("2222 video 型 KE 卡（D-1：KE 阶段只建分组不建卡）",
                len(video_cards),
                "卡上 desc 存着元素设定描述，删除会丢内容 → 需用户裁决",
                video_cards[:12]))
    ke_groups = [_group_title(g) for g in (state.get("keyElements") or [])]
    out.append(("2222 KE 粗组（Q1-B：应一元素一组）",
                len(ke_groups),
                "拆分为一元素一组属重建设计，非机械迁移 → 需用户裁决",
                ke_groups))
    return out


def report_only_3333(state):
    out = []
    shot_img = []
    for g in (state.get("shots") or []):
        for d in (g.get("drafts") or []):
            if str(d.get("mediaType") or "").lower() == "image":
                shot_img.append((_group_title(g)[:34], str(d.get("label") or "")))
    out.append(("3333 shot 组内 image 卡（批4 矩阵：shot 只允许 video）",
                len(shot_img),
                "是用户已生成的提示词资产，删除即丢内容 → 需用户裁决",
                shot_img[:12]))
    return out


def _new_draft_id(group_id, label, seq):
    return f"{group_id}-voice{seq}"


def apply_2222(state, targets):
    """执行 A 项：从 KE 组移除重复音频卡。返回实际删除数。"""
    want = {t["draft_id"] for t in targets if t.get("draft_id")}
    removed = 0
    for g in (state.get("keyElements") or []):
        drafts = g.get("drafts") or []
        kept = []
        for d in drafts:
            if d.get("id") in want:
                removed += 1
                continue
            kept.append(d)
        g["drafts"] = kept
    return removed


def apply_3333(state, targets):
    """执行 B 项：向 KE 组补建音色卡。返回实际补建数。"""
    added = 0
    seq = 0
    by_gid = {}
    for g in (state.get("keyElements") or []):
        by_gid[str(g.get("id") or "")] = g
    for t in targets:
        g = by_gid.get(str(t.get("group_id") or ""))
        if g is None:
            continue
        seq += 1
        g.setdefault("drafts", []).append({
            "id": _new_draft_id(g.get("id"), t["label"], seq),
            "label": t["label"],
            "tag": "Agent",
            "mediaType": "audio",
            "genType": "",
            "imgUrl": "",
            "videoUrl": "",
            "audioUrl": "",
            "prompt": "",
            "desc": t["desc"],
            "audioType": "voice",
            "providerId": "",
            "model": "",
            "mode": "",
            "aspectRatio": "16:9",
            "resolution": "",
            "imageResolution": "",
            "duration": "",
            "timbre": "",
            "refAssets": [],
        })
        added += 1
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description="存量故事板数据处置（默认 dry-run）")
    ap.add_argument("--apply", action="store_true",
                    help="真正落盘（默认只读扫描；落盘前自动整库备份）")
    args = ap.parse_args()

    if not DB.exists():
        print(f"[migrate] FAIL: 找不到状态库 {DB}")
        return 1

    conn = sqlite3.connect(str(DB))
    s2 = _load(conn, PROJ_2222)
    s3 = _load(conn, PROJ_3333)
    if s2 is None or s3 is None:
        print("[migrate] FAIL: 找不到 2222/3333 项目")
        return 1

    t2222 = plan_2222(s2)
    t3333 = plan_3333(s3)

    print("=" * 78)
    print("[migrate] 模式:", "APPLY（落盘）" if args.apply else "DRY-RUN（只读，不写库）")
    print("=" * 78)

    print(f"\n### A. 2222 删除重复音频卡（无损去重）：{len(t2222)} 张")
    for t in t2222:
        print(f"  - [{_ascii_safe(t['group'])}] {_ascii_safe(t['label'])}"
              f"  id={t['draft_id']}")

    print(f"\n### B. 3333 补建角色音色卡（补建非移动）：{len(t3333)} 张")
    for t in t3333:
        print(f"  - [{_ascii_safe(t['group'])}] {_ascii_safe(t['label'])}"
              f"  audioType=voice  desc={_ascii_safe(t['desc'][:40])}...")

    print("\n### C. 只报告、不动手（需用户裁决）")
    for title, n, why, sample in report_only_2222(s2) + report_only_3333(s3):
        print(f"  - {_ascii_safe(title)}：{n} 项")
        print(f"      原因：{_ascii_safe(why)}")
        if sample:
            print(f"      样例：{_ascii_safe(str(sample[:4]))}")

    if not args.apply:
        print("\n[migrate] DRY-RUN 结束，未改动任何数据。"
              "确认无误后加 --apply 落盘。")
        return 0

    # 落盘前整库备份（数据安全底线）
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = DB.with_suffix(f".sqlite3.bak-{ts}")
    shutil.copy2(str(DB), str(bak))
    print(f"\n[migrate] 已备份整库 → {bak.name}")

    rm = apply_2222(s2, t2222)
    ad = apply_3333(s3, t3333)
    conn.execute("update projects set state=? where id=?",
                 (json.dumps(s2, ensure_ascii=False), PROJ_2222))
    conn.execute("update projects set state=? where id=?",
                 (json.dumps(s3, ensure_ascii=False), PROJ_3333))
    conn.commit()
    conn.close()

    print(f"[migrate] APPLY 完成：2222 删除重复音频卡 {rm} 张；"
          f"3333 补建音色卡 {ad} 张")
    print("[migrate] 备份保留在同目录（如需回滚，覆盖回 state.sqlite3 即可）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
