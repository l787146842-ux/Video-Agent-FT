"""Skill 创作助手的「项目规范」层：创作契约、草稿自检与修复消息。

通用 Agent Skills 口径（2026-11-11 用户裁决）：
- 文档 = frontmatter（name/description）+ Markdown 标题式正文；
- 主文档写目标、流程、结构与方法；细节可拆 `references/` 分册，正文给路径；
- 不要求、不识别任何平台私有标签（`<planner>` 等只作普通文本）；
- 自检只查通用契约：frontmatter、标题与实质内容、模板占位、字段表/字段名、
  体量与 lint；不因“章节名不叫某个固定值”打回。

只做「提示 + 校验 + 回喂」，不替模型写正文，也不绕过保存前的人工确认。
"""
import re
from typing import Dict, List, Sequence

from loguru import logger

from src.video_agent.skill_runtime import frontmatter
from src.video_agent.utils.prompts import render_prompt_section
from src.video_agent.web.skill_docs import lint_skill_content, list_skill_sections

_PROMPT_FILE = "shared/skill_authoring.md"
_DESC_LIMIT = 200
_MAX_ISSUES = 12

# 平台内部 schema 字段/ID（AI 创作稿禁用；2026-10-26 用户裁决：写成中文散文）
_INTERNAL_ID_KEYS = (
    "shot_id", "character_id", "scene_id", "prop_id", "music_id",
    "sfx_id", "vocal_id", "subject_action", "shot_size",
    "on_screen_text", "audio_cue",
)
_FIELD_TABLE_KEYS = _INTERNAL_ID_KEYS + (
    "beat", "duration", "camera", "expression", "props", "background",
    "gag", "transition",
)
_INTERNAL_ID_RE = re.compile(r"\b(?:" + "|".join(_INTERNAL_ID_KEYS) + r")\b", re.I)
_FIELD_TABLE_RE = re.compile(
    r"(?m)^\|\s*(?:" + "|".join(_FIELD_TABLE_KEYS) + r")\s*\|", re.I,
)


def build_create_system() -> str:
    """创作模式 system prompt（prompts/ 外部化；不注入工具目录）。"""
    text = render_prompt_section(_PROMPT_FILE, "CREATE_SYSTEM")
    if not text:
        # 外置文件缺失属部署错误：fail-loud 记录，路由层会以空 system 继续（模型可降级）
        logger.error(f"[SkillAuthoring] 创作提示词分节缺失: {_PROMPT_FILE} :: CREATE_SYSTEM")
    return text


def _section_bodies(
    content: str, sections: Sequence[Dict[str, object]] | None = None,
) -> Dict[str, str]:
    """章节 → 正文（标题行之后到下一章节前）；同名取首个。

    章节标题的解析归 `list_skill_sections`（只认 Markdown 标题），
    本函数只负责从字符区间里切出正文。
    """
    secs = sections if sections is not None else list_skill_sections(content)
    bodies: Dict[str, str] = {}
    for sec in secs:
        title = str(sec.get("title") or "").strip()
        start = int(sec.get("start") or 0)
        end = int(sec.get("end") or 0)
        line_end = content.find("\n", start)
        body = content[line_end + 1: end] if line_end != -1 else ""
        bodies.setdefault(title, body.strip())
    return bodies


def _style_issues(
    content: str, bodies: Dict[str, str], create_mode: bool,
) -> List[str]:
    """文风/可读性机械检查：禁平台字段名/字段表，禁提示词代码块。

    2026-10-26 用户裁决：AI 产出要像库里已有 Skill 的散文，不要 API 字段说明，
    提示词示例用正文/引用块，不要整段包 ```。只告警并触发一次自修复。
    """
    issues: List[str] = []
    ids = sorted({m.group(0).lower() for m in _INTERNAL_ID_RE.finditer(content)})
    if ids:
        issues.append(
            "文档出现平台内部字段名（" + "、".join(ids[:6])
            + "）：请改用中文业务词写成散文"
        )
    table = sorted({
        m.group(0).split("|")[1].strip() for m in _FIELD_TABLE_RE.finditer(content)
    })
    if table:
        issues.append(
            "文档出现平台内部字段表（" + "、".join(table[:6])
            + "）：请把分镜/资产改写成「第 1 镜：……」段落"
        )
    # 提示词章节的代码块检查：Flova 六节骨架下提示词模板多在 Reference 路由
    # 指向的分册里，与之相关的章节标题可能是「Reference 路由」「专业创作方法」
    # 或旧的「提示词写法」，故对任一相关章节命中代码块即告警。
    prompt_related = [
        v for k, v in bodies.items()
        if ("提示词" in k or "参考" in k or "路由" in k or "方法" in k)
    ]
    if create_mode and any("```" in v for v in prompt_related):
        issues.append(
            "提示词章节出现代码块：请改为正文段落或 > 引用块，"
            "不要用 ``` 包住提示词"
        )
    return issues


def validate_skill_draft(content: str, *, create_mode: bool) -> List[str]:
    """机械自检 Skill 草稿，返回人话问题清单（空 = 通过）。

    create_mode：新建 Skill 的**通用骨架**检查（frontmatter + 至少两个
    二级标题 + 实质内容 + 含流程章节）；优化既有 Skill 时只查通用项
    （frontmatter / 描述长度 / lint），不因章节写法差异误判。
    """
    content = content or ""
    if not content.strip():
        return ["未解析到 Skill 正文"]
    # 模板占位符（函数内常量：非提示词注入源，避免 prompt_literals 误判）
    placeholder_markers = (
        "第一步做什么",
        "一句话说明何时使用本 Skill",
        "看完素材要产出什么（例如",
        "关键元素、分镜、音频怎么建",
        "出图/出视频/出音频时参考哪些素材",
        "提示词语言与内容规范（景别",
        "时间线怎么组装、导出前要确认哪些内容",
        "需要时读 references/",
    )
    issues: List[str] = []

    declaration, body, fm_err = frontmatter.split_frontmatter(content)
    if fm_err:
        issues.append(f"frontmatter 解析失败：{fm_err}")
    elif declaration is None:
        issues.append("缺少 frontmatter：文档开头需有 --- name/description --- 声明块")
    else:
        name = str(declaration.get("name") or "").strip()
        desc = str(declaration.get("description") or "").strip()
        if not name:
            issues.append("frontmatter 缺少 name")
        if not desc:
            issues.append("frontmatter 缺少 description")
        elif len(desc) > _DESC_LIMIT:
            issues.append(f"description 超长（{len(desc)}/{_DESC_LIMIT} 字），请压缩")
    if not content.lstrip("\ufeff").startswith("---"):
        issues.append("必须使用 `---` frontmatter 声明块（裸键 skill_name: 形态不算）")

    sections = list_skill_sections(content)
    bodies = _section_bodies(content, sections)
    issues.extend(_style_issues(content, bodies, create_mode))

    if create_mode:
        if len(sections) < 2:
            issues.append(
                "正文至少需要两个二级标题（六节骨架见合约：目标/结构/规格/流程/方法/路由）")
        if len(body.strip()) < 200:
            issues.append("正文过短（不足 200 字）：请写清流程、结构与可执行方法")
        if not any(("流程" in t or "步骤" in t) for t in bodies):
            issues.append("缺少「制作流程」类章节：请写清步骤、依赖与何时暂停")
        # Flova 六节骨架（2026-11-11 用户裁决）：只硬校验「流程」与「分册路由」
        # 两个不可省节点——其余四节允许按 Skill 性质调整标题措辞，避免误伤。
        # 分册路由的等价标题：参考 / 路由 / Reference。
        if not any(("参考" in t or "路由" in t or "reference" in t.lower())
                   for t in bodies):
            issues.append(
                "缺少「Reference 路由」章节：请列出什么时候读哪本分册"
                "（references/媒体生成.md、提示词写作.md、剪辑交付.md）")
        for title, section_body in bodies.items():
            if any(marker in section_body for marker in placeholder_markers):
                issues.append(f"章节「{title}」仍保留模板占位句，请改写成真实内容")

    # lint 复用保存前的同一套机械检查（硬编码参数/能力章节/体量等）
    issues.extend(lint_skill_content(content).get("warnings") or [])

    # 去重保序并限量（避免把整屏警告塞回模型/界面）
    seen = set()
    unique = []
    for issue in issues:
        if issue in seen:
            continue
        seen.add(issue)
        unique.append(issue)
    return unique[:_MAX_ISSUES]


def repair_messages(
    base_messages: List[dict], content: str, issues: List[str],
) -> List[dict]:
    """构造自修复消息：携带上一版全文 + 问题清单，让模型整篇重写一版。"""
    issue_text = "\n".join(f"- {issue}" for issue in issues)
    repair = render_prompt_section(_PROMPT_FILE, "REPAIR", issues=issue_text)
    if not repair:
        # ASCII 兜底（prompts/ 缺失也不阻断修复链）
        repair = (
            "Fix every issue below and output the full corrected Skill document "
            "in one ```markdown block:\n" + issue_text
        )
    return [
        *base_messages,
        {"role": "assistant", "content": f"```markdown\n{content}\n```"},
        {"role": "user", "content": repair},
    ]
