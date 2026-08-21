# -*- coding: utf-8 -*-
"""skill 文档执行器名对齐迁移（执行器名对齐批，用户裁决：skill 文档只能改执行器名）。

把 data/skills/*.md 与 data/skills_manifests/*.json 中源平台遗留的虚构执行器名
（media_generator / storyboard_designer / text_editor / write_the_prompt /
multimodal_analyze_tool / resource_prepare_and_analyze）替换为本项目真实
执行器/工具名（EXECUTOR_TOOL_CLASSES + image_generate / generate_video /
document_write）。散文一字不改：章节拆分只动 tag 行，流程清单只换执行器名。

拆分策略（按子标题关键字分类，非位置硬编码）：
- <storyboard_designer> → 按标题归 storyboard_key_elements / storyboard_shots /
  storyboard_audio 三节；全局规范类标题归入首个分类段（前导）；
- <media_generator> → 按标题归 image_generate / generate_video / audio_generate；
- 任一节无法全覆盖分类 → 该文档中止迁移并报告（保守，不误伤）。

用法：python scripts/migrate_skill_executor_names.py [--check]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "data" / "skills"
MANIFEST_DIR = ROOT / "data" / "skills_manifests"

TRIO = "storyboard_key_elements / storyboard_shots / storyboard_audio"

# 章节拆分豁免：散文墙章节（无标题结构），不重构内容就无法拆分；
# 保留注册别名 tag（SECTION_TAG_STAGES 兼容层承重，注入语义不变），
# 行级改名照常执行。例外登记见事故台账 L-0821C。
EXEMPT_SPLIT = {"宣言式概念短片.md"}

# ---------- 名称映射 ----------

TAG_RENAME = {
    "multimodal_analyze_tool": "script_analyze",
    "resource_prepare_and_analyze": "script_analyze",
    "write_the_prompt": "write_media_prompt",
}

BOLD_RENAME = {
    "resource_prepare_and_analyze": "script_analyze",
    "multimodal_analyze_tool": "script_analyze",
    "text_editor": "document_write",
    "storyboard_designer": TRIO,
    "write_the_prompt": "write_media_prompt",
    "video_assembler": "video_assembler",
}

PROSE_RENAME = {
    "multimodal_analyze_tool": "script_analyze",
    "resource_prepare_and_analyze": "script_analyze",
    "write_the_prompt": "write_media_prompt",
    "text_editor": "document_write",
    "storyboard_designer": TRIO,
    # 源平台展示名（大小写混用形态）
    "Resource Prepare and Analyze": "script_analyze",
    "Media Generator": "媒体生成工具（image_generate / generate_video / audio_generate）",
}

LEGACY = re.compile(
    r"\b(media_generator|Media Generator|storyboard_designer|text_editor|write_the_prompt"
    r"|multimodal_analyze_tool|resource_prepare_and_analyze"
    r"|Resource Prepare and Analyze)\b", re.I)


def media_ref_for(line: str) -> str:
    """media_generator 按行上下文判定真实工具（优先级：音频 > 特指图像 >
    动宾强规则 > 泛视频 > 泛称图像 > 素材绑定 > 兜底出图）。"""
    if re.search(r"音频|BGM|旁白|台词|配乐|语音|音色", line):
        return "audio_generate"
    if re.search(r"设定图|三视图|四视图|概念图|表格图|运镜轨迹|草稿图|参考图"
                 r"|首帧|关键帧|帧图|场景图|形象", line):
        return "write_media_prompt、image_generate"
    # 动宾强规则：「生成视频/逐 shot 生成视频」主谓结构（图像特指词未命中时）
    if re.search(r"生成视频|生成.*视频|逐 ?shot 生成|出视频", line):
        return "write_media_prompt、generate_video"
    if re.search(r"视频|shot|镜头|参考帧", line):
        return "write_media_prompt、generate_video"
    if re.search(r"图像|图片", line):
        return "write_media_prompt、image_generate"
    if re.search(r"绑定|分配|注册|素材|媒体|资产", line):
        # 用户上传素材的登记绑定（本项目由 image_generate 工具面承接）
        return "image_generate"
    # 兜底：源平台 media_generator 的通用职责 = 出图（视频/音频行必带对应关键词）
    return "write_media_prompt、image_generate"


# ---------- storyboard_designer 三拆（顺序边界式） ----------

_SB_AUDIO = re.compile(r"音频|BGM|旁白|配乐|audio", re.I)
_SB_SHOT = re.compile(r"分镜|镜头|shot|运镜|机位", re.I)


def _split_by_heading_class(body: str, classify, report, name: str, which: str):
    """按标题关键字把章节正文切成 [(tag, 原文行区间文本), ...]。

    零空白损失：按原始行区间切分（未分类块归入下一个分类段的前导，
    尾部未分类块并入最后一个分类段）；全覆盖失败返回 None。"""
    lines = body.split("\n")
    head_idx = [i for i, ln in enumerate(lines)
                if ln.strip().startswith("**") or ln.strip().startswith("#")]
    if not head_idx:
        report.append(f"[中止] {name}: {which} 无标题结构")
        return None
    # 每个标题块的行区间 [start, end)
    blocks = [(head_idx[k], head_idx[k + 1] if k + 1 < len(head_idx) else len(lines))
              for k in range(len(head_idx))]
    parts = []      # [(tag, start, end)]，end 开区间
    pending_start = None  # 未分类块区间起点（含首标题前的前导文字）
    cur_start = 0 if lines[:head_idx[0]] and "".join(lines[:head_idx[0]]).strip() else head_idx[0]
    pending_start = cur_start
    for start, end in blocks:
        tag = classify(lines[start].strip())
        if tag:
            if parts and parts[-1][0] == tag:
                parts[-1][2] = end  # 相邻同 tag 合并
            else:
                parts.append([tag, pending_start, end])
            pending_start = end
        # 未分类块：区间自然并入下一个分类段的 pending_start
    if pending_start < len(lines) and "".join(lines[pending_start:]).strip():
        # 尾部未分类文字并入最后一段
        if not parts:
            report.append(f"[中止] {name}: {which} 全部标题不可分类")
            return None
        parts[-1][2] = len(lines)
    if not parts:
        report.append(f"[中止] {name}: {which} 不可分类")
        return None
    out = [(t, "\n".join(lines[s:e]).strip("\n")) for t, s, e in parts]
    if any(not x.strip() for _, x in out):
        report.append(f"[中止] {name}: {which} 切出空节")
        return None
    return out


def split_storyboard(body: str, report, name: str):
    """顺序边界式三拆：首个 shot 类标题 = shot 段起点，其后首个 audio 类标题
    = audio 段起点；自检清单等未分类标题自然归入 shot 段（位置在前）。"""
    lines = body.split("\n")
    heads = [i for i, ln in enumerate(lines)
             if ln.strip().startswith("**") or ln.strip().startswith("#")]
    shot_i = next((i for i in heads if _SB_SHOT.search(lines[i])), -1)
    audio_i = next((i for i in heads if i > shot_i and _SB_AUDIO.search(lines[i])), -1)
    if shot_i < 0 or audio_i < 0:
        report.append(f"[中止] {name}: storyboard_designer 边界不可识别"
                      f"(shot={shot_i}, audio={audio_i})")
        return None
    parts = [("storyboard_key_elements", lines[:shot_i]),
             ("storyboard_shots", lines[shot_i:audio_i]),
             ("storyboard_audio", lines[audio_i:])]
    out = [(t, "\n".join(ls).strip("\n")) for t, ls in parts]
    if any(not x.strip() for _, x in out):
        report.append(f"[中止] {name}: storyboard_designer 切出空节")
        return None
    return out


def split_media(body: str, report, name: str):
    return _split_by_heading_class(body, _classify_mg_heading, report, name,
                                   "media_generator")


# ---------- media_generator 分节（标题分类式） ----------

_MG_AUDIO = re.compile(r"音频|BGM|旁白|台词|配乐|语音|音色|instrumental|narration", re.I)
_MG_IMAGE_SPEC = re.compile(r"设定图|三视图|四视图|概念图|表格图|运镜轨迹|草稿图"
                            r"|参考图|首帧|关键帧|帧图|场景图|形象", re.I)
_MG_VIDEO = re.compile(r"视频|shot|镜头|video|参考帧", re.I)
_MG_IMAGE_GEN = re.compile(r"图像|图片|生成图", re.I)


def _classify_mg_heading(s: str) -> str:
    if _MG_AUDIO.search(s):
        return "audio_generate"
    if _MG_IMAGE_SPEC.search(s):
        return "image_generate"
    if _MG_VIDEO.search(s):
        return "generate_video"
    if _MG_IMAGE_GEN.search(s):
        return "image_generate"
    return ""


# ---------- 文档迁移 ----------

def migrate_doc(text: str, name: str, report):
    out = text

    m = re.search(r"<storyboard_designer>(.*?)</storyboard_designer>", out, re.S)
    if m and name not in EXEMPT_SPLIT:
        parts = split_storyboard(m.group(1).strip("\n"), report, name)
        if parts is None:
            return None
        body = "\n\n".join(f"<{t}>\n{x}\n</{t}>" for t, x in parts)
        out = out[:m.start()] + body + out[m.end():]

    m = re.search(r"<media_generator>(.*?)</media_generator>", out, re.S)
    if m and name not in EXEMPT_SPLIT:
        parts = split_media(m.group(1).strip("\n"), report, name)
        if parts is None:
            return None
        body = "\n\n".join(f"<{t}>\n{x}\n</{t}>" for t, x in parts)
        out = out[:m.start()] + body + out[m.end():]

    for old, new in TAG_RENAME.items():
        out = out.replace(f"<{old}>", f"<{new}>").replace(f"</{old}>", f"</{new}>")

    # 逐行：加粗引用 + 散文遗留名（纯 tag 行不进入替换，防章节锚点被拆散）
    new_lines = []
    for ln in out.split("\n"):
        if re.match(r"^\s*</?[a-z_]+>\s*$", ln):
            new_lines.append(ln)
            continue
        def bold_sub(mm):
            nm = mm.group(1).strip()
            if nm == "media_generator":
                sentence = re.split(r"[。；;\n]", ln[:mm.start()])[-1]
                return f"**{media_ref_for(sentence) or media_ref_for(ln)}**"
            if nm in BOLD_RENAME:
                return f"**{BOLD_RENAME[nm]}**"
            return mm.group(0)

        ln = re.sub(r"\*\*([A-Za-z_ ]+)\*\*", bold_sub, ln)
        for old, new in PROSE_RENAME.items():
            ln = re.sub(rf"\b{old}\b", new, ln)

        def media_prose_sub(mm):
            # 判定按标注所在分句切（防跨句关键词误判）
            sentence = re.split(r"[。；;\n]", ln[:mm.start()])[-1]
            return media_ref_for(sentence) or media_ref_for(ln)

        ln = re.sub(r"\bmedia_generator\b", media_prose_sub, ln)
        new_lines.append(ln)
    return "\n".join(new_lines)


def migrate_steps_text(v: str, report, where: str) -> str:
    for old, new in BOLD_RENAME.items():
        v = v.replace(f"**{old}**", f"**{new}**").replace(old, new)
    # 判定按「标注所在分句」切（同一 step 多个 media_generator 分属不同语义；
    # 保留原有粗体包裹，维持与文档流程行的镜像一致）
    def _media(mm):
        sentence = re.split(r"[。；;\n]", v[:mm.start()])[-1]
        rep = media_ref_for(sentence) or media_ref_for(v)
        return f"{mm.group(1) or ''}{rep}{mm.group(2) or ''}"

    v = re.sub(r"(\*\*)?media_generator(\*\*)?", _media, v)
    return v


def main():
    check_only = "--check" in sys.argv
    report = []
    migrated_docs = []
    for md in sorted(SKILLS_DIR.glob("*.md")):
        original = md.read_text(encoding="utf-8")
        migrated = migrate_doc(original, md.name, report)
        if migrated is None:
            continue
        migrated_docs.append(md.name)
        if not check_only:
            md.write_text(migrated, encoding="utf-8")
        if md.name in EXEMPT_SPLIT:
            continue  # 豁免文档：章节 tag 合法保留，不算残留
        left = sorted(set(LEGACY.findall(migrated)))
        if left:
            report.append(f"[残留] {md.name}: {left}")
    for js in sorted(MANIFEST_DIR.glob("*.json")):
        try:
            data = json.loads(js.read_text(encoding="utf-8"))
        except Exception as e:
            report.append(f"[错误] {js.name}: {e}")
            continue
        steps = (data.get("flow") or {}).get("steps") or {}
        changed = False
        for k, v in list(steps.items()):
            new_v = migrate_steps_text(v, report, f"{js.name} step{k}")
            if new_v != v:
                steps[k] = new_v
                changed = True
        left = sorted(set(LEGACY.findall(json.dumps(data, ensure_ascii=False))))
        if left:
            report.append(f"[残留] {js.name}: {left}")
        if changed and not check_only:
            js.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(f"迁移文档数: {len(migrated_docs)}")
    print("\n".join(report) if report else "无残留无人工项")
    if any(r.startswith("[中止]") or r.startswith("[人工]") or r.startswith("[残留]")
           for r in report):
        sys.exit(1)


if __name__ == "__main__":
    main()
