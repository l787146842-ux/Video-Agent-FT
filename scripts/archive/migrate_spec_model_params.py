"""B7 模型能力参数治理——旧规格文档迁移 + Skill 写死参数扫描。

用户裁决（2026-08-15）：模型能力参数（出图/出视频渠道、分辨率、时长）唯一
权威源 = 顶部「全局设置」；规格文档与 Skill 文档中的历史写死参数一律作废。

本脚本：
1. 扫描 workspace/*/state 中全部项目的规格文档（Final_Video_Spec.md 等），
   把「图像生成/视频生成/图片分辨率/视频分辨率/分镜最大时长」硬参数行
   替换为「见全局设置」引用行（幂等；--apply 落盘，默认 dry-run）；
2. 扫描 data/skills/*.md 的写死模型参数（厂商/模型/分辨率/时长模式），
   仅报告不修改（不改 Skill 文件业务内容；运行时已忽略）。

用法：
    python scripts/migrate_spec_model_params.py          # dry-run 报告
    python scripts/migrate_spec_model_params.py --apply  # 迁移规格文档
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_SPEC_NAMES = ("Final_Video_Spec.md", "制片规格.md", "成片规格.md")
_HARD_LINE_RE = re.compile(
    r"(?im)^(\s*(?:[-*]\s*)?(?:图像生成|视频生成|图片分辨率|图像分辨率|视频分辨率|"
    r"分镜最大时长|单镜头最大时长|shotmaxduration|imageresolution|videoresolution)"
    r"\s*[:：])(.*)$"
)
_SKILL_PARAM_RE = re.compile(
    r"(Seedance|GPT\s*Image|Kling|可灵|即梦|Midjourney|Flux|SDXL|"
    r"Runway|Vidu|Sora|Veo|Pika|Hailuo|海螺|万相|通义|1K|2K|4K|"
    r"480p|720p|1080p|60fps|24fps)"
)


def scan_spec_docs(apply: bool):
    """扫描项目规格文档并（可选）迁移硬参数行。返回 (文档数, 迁移行数)。"""
    n_docs = n_lines = 0
    ws = ROOT / "workspace"
    if not ws.exists():
        print("[migrate] workspace 不存在，跳过规格文档扫描")
        return 0, 0
    for state_file in ws.glob("**/state.json"):
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        for proj in (data.get("projects") or []) if isinstance(data, dict) else []:
            docs = (proj.get("documents") or []) if isinstance(proj, dict) else []
            for d in docs:
                if not isinstance(d, dict) or str(d.get("name") or "") not in _SPEC_NAMES:
                    continue
                content = str(d.get("content") or "")
                hits = _HARD_LINE_RE.findall(content)
                if not hits:
                    continue
                n_docs += 1
                n_lines += len(hits)
                print(f"[migrate] 规格文档 {d.get('name')}（项目 {proj.get('id', '?')}）：{len(hits)} 行硬参数")
                for key, _v in hits:
                    print(f"    - {key.strip()}")
                if apply:
                    d["content"] = _HARD_LINE_RE.sub(
                        lambda m: f"{m.group(1)}（见顶部「全局设置」，本行参数已作废）",
                        content,
                    )
                    state_file.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    print(f"    → 已迁移落盘 {state_file.relative_to(ROOT)}")
    return n_docs, n_lines


def scan_skills():
    """扫描 data/skills 写死模型参数（仅报告）。"""
    skills_dir = ROOT / "data" / "skills"
    if not skills_dir.exists():
        return
    for f in sorted(skills_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        hits = sorted(set(_SKILL_PARAM_RE.findall(text)))
        if hits:
            print(f"[migrate] Skill《{f.stem}》写死参数（已作废，运行时忽略）：{hits}")


def main() -> int:
    apply = "--apply" in sys.argv
    print(f"[migrate] 模式：{'APPLY（落盘）' if apply else 'DRY-RUN（仅报告）'}")
    n_docs, n_lines = scan_spec_docs(apply)
    scan_skills()
    print(f"[migrate] 规格文档 {n_docs} 份 / {n_lines} 行硬参数" + (" 已迁移" if apply else "（--apply 落盘）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
