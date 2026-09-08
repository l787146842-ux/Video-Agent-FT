# -*- coding: utf-8 -*-
"""判官层对照包生成器（Skill 流程跑通修复批 4 · 观察层，不进门禁）。

两层形态之「判官观察层」（V3-2/V3-3）：同一套标准输入挂真模型跑，
判官（人，LLM 判官缓议）拿 skill 原文对照聊天记录按 §五 判据 1-7 打分。
真模型不确定 → 不进机器门禁、不设阈值，只建基线看趋势。

触发时机（V5-2）：每批末一次 + 每次 skill 正文变更后一次。

用法：
    python scripts/judge_replay.py --slug <slug>     # 打包单份 skill 对照包
    python scripts/judge_replay.py --all             # 打包全部存量 skill

产物：judge_baselines/<日期>/<slug>.md —— 含 skill 原文全文、标准输入、
判据 1-7 打分表模板。真模型跑法（本脚本不代替）：启动服务后新建项目、
选中该 skill、发送标准输入，把对话记录粘贴进对照包的「聊天记录」节，
人工逐判据打分并留一句证据引用。

§五 判官判据（打分口径，16→15 份通用）：
  1 首步正确（按各自 skill 原文的尺子）；
  2 四类停点规矩 × execution_preference 档位（V4-1 两层语义）；
  3 A 类成熟剧本跳过分析并说明理由（V3-5）；
  4 启动协议条件式（缺项必问、不缺可跳且说明理由）；
  5 提示词草案独立确认（write_media_prompt 中间态，V4-6）；
  6 流程外动作不被误伤；
  7 能走到最后一步（能力缺口按逃生口处理，转录三 L461 姿势）。
观察指标（只记录不断言）：进入各阶段前是否 read_skill 取读对应章节。
"""
import argparse
import datetime
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "data" / "skills"
OUT_DIR = ROOT / "judge_baselines"

STANDARD_INPUT = "请按这个 Skill 的流程，把我上传的剧本做成成片。"

JUDGE_TEMPLATE = """# 判官层对照包 · {slug}

- 生成日期：{date}
- 标准输入：{standard_input}
- 执行偏好档位：____________（confirm_before_gen / auto_decide / generate_directly）

## 判据打分（§五，1-7；每项 通过 / 不通过 / 不适用 + 一句证据引用）

| # | 判据 | 结论 | 证据（引用聊天记录原句） |
|---|------|------|--------------------------|
| 1 | 首步正确 | | |
| 2 | 四类停点 × 档位 | | |
| 3 | A 类剧本跳分析并说明理由 | | |
| 4 | 启动协议条件式 | | |
| 5 | 提示词草案独立确认 | | |
| 6 | 流程外动作不误伤 | | |
| 7 | 走到最后一步（缺口按逃生口） | | |

观察指标（只记录）：read_skill 调用次数与时机：____________

## 聊天记录

（真模型跑完后把对话记录粘贴于此）

## skill 原文（判官对照的唯一尺子）

```markdown
{skill_text}
```
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="判官层对照包生成器（不进门禁）")
    ap.add_argument("--slug", help="单份 skill 的目录名")
    ap.add_argument("--all", action="store_true", help="打包全部存量 skill")
    args = ap.parse_args()
    if not args.slug and not args.all:
        ap.error("需要 --slug <slug> 或 --all")
    slugs = ([args.slug] if args.slug
             else sorted(p.name for p in SKILLS_DIR.iterdir()
                         if p.is_dir() and (p / "SKILL.md").exists()))
    out_dir = OUT_DIR / datetime.date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for slug in slugs:
        doc = SKILLS_DIR / slug / "SKILL.md"
        if not doc.exists():
            print(f"[judge_replay] SKIP (no doc): {slug.encode('ascii', 'backslashreplace').decode()}")
            continue
        text = doc.read_text(encoding="utf-8")
        out = out_dir / f"{slug}.md"
        out.write_text(JUDGE_TEMPLATE.format(
            slug=slug, date=datetime.date.today().isoformat(),
            standard_input=STANDARD_INPUT, skill_text=text), encoding="utf-8")
        written += 1
        print(f"[judge_replay] packaged: {out.name.encode('ascii', 'backslashreplace').decode()}")
    print(f"[judge_replay] {written} package(s) -> {out_dir} "
          "(fill chat transcript after a real-model run; human judge scores 1-7)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
