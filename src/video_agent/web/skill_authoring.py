"""Skill 创作助手的「项目规范」层：真实工具目录、创作契约、草稿自检与修复消息。

背景（2026-10-20 用户裁决）：Skill 创作门槛高，希望用户在新建 Skill 时直接让
优化助手生成一版满足本项目要求的草稿。模型只靠「保留结构 + 用真实工具名」的
软约束不够——本模块把要求变成**可机械校验的契约**：

1. `build_create_system`：六章节创作提示词 + 平台真实工具目录（带一句话说明）；
2. `validate_skill_draft`：frontmatter / 标题 / 调用规则 / 六章节齐全非空 /
   模板占位符残留 / 描述长度 / lint（硬编码参数、能力章节、外来标签等）；
3. `repair_messages`：把自检问题回喂模型，路由在创作模式下最多自修复一次。

只做「提示 + 校验 + 回喂」，不替模型写正文，也不绕过保存前的人工确认。
"""
import re
from typing import Dict, List, Sequence

from loguru import logger

from src.video_agent.skill_runtime import frontmatter
from src.video_agent.tools import ToolManager
from src.video_agent.tools.canvas_tools import register_canvas_tools
from src.video_agent.utils.prompts import render_prompt_section
from src.video_agent.web.skill_docs import lint_skill_content, list_skill_sections

# 新建 Skill 的六章节（顺序即模板顺序；与前端 skill-template.ts 同口径）
REQUIRED_SECTIONS: Sequence[str] = (
    "流程规划", "素材分析", "故事板设计", "媒体生成", "提示词写法", "组装导出",
)

_PROMPT_FILE = "shared/skill_authoring.md"
_DESC_LIMIT = 200
_MAX_ISSUES = 12


def _one_line(text: str, limit: int = 150) -> str:
    """压成单行并截断（工具目录用；不改变工具名）。"""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def build_tool_catalog() -> str:
    """平台真实注册工具目录（名称 + 一句话说明）。

    名单唯一源 = ToolManager（画布工具补注册后取全集，register 幂等），
    与助手白名单同源，防编造工具名。
    """
    register_canvas_tools()
    lines = []
    for name in sorted(ToolManager._tools):
        tool = ToolManager._tools[name]
        lines.append(f"- {name}：{_one_line(getattr(tool, 'description', ''))}")
    return "\n".join(lines)


def build_create_system() -> str:
    """创作模式 system prompt（prompts/ 外部化；工具目录活读，不硬编码名单）。"""
    text = render_prompt_section(_PROMPT_FILE, "CREATE_SYSTEM", tool_catalog=build_tool_catalog())
    if not text:
        # 外置文件缺失属部署错误：fail-loud 记录，路由层会以空 system 继续（模型可降级）
        logger.error(f"[SkillAuthoring] 创作提示词分节缺失: {_PROMPT_FILE} :: CREATE_SYSTEM")
    return text


def _normalize_title(title: str) -> str:
    """标题归一：去掉「一、」「1.」「1、」等序号前缀，便于匹配模板章节。"""
    return re.sub(r"^\s*(?:[\d一二三四五六七八九十]+[.、)）．]\s*)", "", title or "").strip()


def _section_bodies(
    content: str, sections: Sequence[Dict[str, object]] | None = None,
) -> Dict[str, str]:
    """标题式章节 → 正文（标题行之后到下一章节前）；同名取首个。"""
    secs = sections if sections is not None else list_skill_sections(content)
    bodies: Dict[str, str] = {}
    for sec in secs:
        title = _normalize_title(str(sec.get("title") or ""))
        start = int(sec.get("start") or 0)
        end = int(sec.get("end") or 0)
        line_end = content.find("\n", start)
        body = content[line_end + 1: end] if line_end != -1 else ""
        bodies.setdefault(title, body.strip())
    return bodies


def validate_skill_draft(content: str, *, create_mode: bool) -> List[str]:
    """机械自检 Skill 草稿，返回人话问题清单（空 = 通过）。

    create_mode：新建 Skill 的六章节契约；优化既有 Skill 时只查通用项，
    避免把 tag 式存量文档误判成缺章节。
    """
    content = content or ""
    if not content.strip():
        return ["未解析到 Skill 正文"]
    # 模板占位符（函数内常量：非提示词注入源，避免 prompt_literals 误判）
    placeholder_markers = (
        "第一步做什么",
        "一句话说明何时使用本 Skill",
        "看完素材要产出什么（例如",
        "关键元素、分镜、音频层怎么建",
        "出图/出视频/出音频时参考哪些素材",
        "提示词语言与内容规范（景别",
        "时间线怎么组装、导出前要确认哪些内容",
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

    if not re.search(r"(?m)^#\s+\S", body):
        issues.append("缺少 `# 名称` 一级标题")
    if not re.search(r"(?m)^>\s*调用规则\s*[:：]", body):
        issues.append("缺少 `> 调用规则：…` 行")

    if create_mode:
        sections = list_skill_sections(content)
        bodies = _section_bodies(content, sections)
        found: List[int] = []
        for title in REQUIRED_SECTIONS:
            hits = [i for i, sec in enumerate(sections)
                    if title in _normalize_title(str(sec.get("title") or ""))]
            if not hits:
                issues.append(f"缺少章节「{title}」（六个二级标题必须齐全）")
                continue
            found.append(hits[0])
            section_title = _normalize_title(str(sections[hits[0]].get("title") or ""))
            section_body = bodies.get(section_title, "")
            if len(section_body) < 8:
                issues.append(f"章节「{title}」没有实质内容")
            elif any(marker in section_body for marker in placeholder_markers):
                issues.append(f"章节「{title}」仍保留模板占位句，请改写成真实内容")
        if len(found) == len(REQUIRED_SECTIONS) and found != sorted(found):
            issues.append("六章节顺序不符：请按 " + " → ".join(REQUIRED_SECTIONS) + " 排列")

    # lint 复用保存前的同一套机械检查（硬编码参数/能力章节/外来标签/体量等）
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
