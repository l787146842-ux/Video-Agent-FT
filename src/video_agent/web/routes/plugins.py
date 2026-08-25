"""
/api/plugins + /api/skills — 技能配置端点

Skill 下拉数据 = 仅文档 Skill（data/skills/*.md）。
代码内置 Skill（编剧/分镜师/制片）已按用户要求彻底移除，不得再回到下拉框。
文档 Skill 的 system_prompt 即文档全文——用户改文档就是改流程。
"""
from fastapi import APIRouter
from pydantic import BaseModel
from loguru import logger

import re
from typing import Dict, List, Optional

from src.video_agent.exceptions import VideoAgentError
from src.video_agent.core.token_budget import window_recent_turns
from src.video_agent.tools import ToolManager
from src.video_agent.tools.canvas_tools import register_canvas_tools
from src.video_agent.web.chat_opening import _create_chat_adapter
from src.video_agent.web.error_payload import LEGACY_NOT_FOUND, LEGACY_VALIDATION_ERROR
from src.video_agent.web.provider_config import load_merged_providers
from src.video_agent.web.skill_docs import (
    get_skill_doc,
    list_skill_docs,
    list_skill_doc_history,
    save_skill_doc,
    delete_skill_doc,
    lint_skill_content,
)

router = APIRouter()


@router.get("/plugins/ftdyb-agent/config")
async def get_agent_config():
    """前端 agentSkillSelect 下拉框数据源：仅文档 Skill（用户可见可编辑）。

    代码形态 Skill（内置类注册器）不进下拉（注册器整包已移除），
    防用户删过的「编剧/分镜师/制片 Agent」复活。
    """
    doc_skills = [
        {
            "id": d["id"],
            "name": d["name"],
            "description": d["description"],
            "system_prompt": d["content"],
            "source": "doc",
            "slug": d["slug"],
            # 欠账显性化——规划级执行器名单随契约下发，
            # 前端据实标注（不硬编码工具名）
            "planning_executors": _planning_executors_of(d["name"]),
        }
        for d in list_skill_docs()
    ]
    return {"skills": doc_skills}


def _planning_executors_of(skill_name: str):
    """规划级执行器名单（前端契约字段保留）：执行器已退役，
    永远返回空名单（前端据实标注，空 = 无规划级欠账）。"""
    return []


@router.get("/skills/docs")
async def get_skill_docs():
    """文档面板：Skill 文档列表（含全文）"""
    return {"docs": list_skill_docs()}


class SkillDocSave(BaseModel):
    content: str


@router.put("/skills/docs/{slug}")
async def put_skill_doc(slug: str, body: SkillDocSave):
    """保存 Skill 文档（新建或覆盖）；lint 结果随响应下发（只告警不阻断，
    前端 toast 回显——体量/Flova 组成/frontmatter 声明体检等编辑期可见）"""
    try:
        doc = save_skill_doc(slug, body.content)
    except ValueError as e:
        raise VideoAgentError(
            str(e), status_code=400, error_code=LEGACY_VALIDATION_ERROR
        ) from e
    lint = lint_skill_content(body.content, slug=slug)
    return {"ok": True, "doc": doc, "lint": lint}


@router.get("/skills/docs/{slug}")
async def get_one_skill_doc(slug: str):
    try:
        doc = get_skill_doc(slug)
    except ValueError as e:
        raise VideoAgentError(
            str(e), status_code=400, error_code=LEGACY_VALIDATION_ERROR
        ) from e
    if not doc:
        raise VideoAgentError(
            f"Skill 文档 '{slug}' 不存在", status_code=404, error_code=LEGACY_NOT_FOUND
        )
    return doc


@router.get("/skills/docs/{slug}/history")
async def get_skill_doc_history(slug: str):
    """Skill 文档历史版本（新→旧，含全文；前端可查看/回滚）"""
    try:
        return {"versions": list_skill_doc_history(slug)}
    except ValueError as e:
        raise VideoAgentError(
            str(e), status_code=400, error_code=LEGACY_VALIDATION_ERROR
        ) from e


@router.delete("/skills/docs/{slug}")
async def delete_one_skill_doc(slug: str):
    """删除指定 Skill 文档"""
    try:
        delete_skill_doc(slug)
    except ValueError as e:
        raise VideoAgentError(
            str(e), status_code=400, error_code=LEGACY_VALIDATION_ERROR
        ) from e
    return {"ok": True}


class SkillFormatRequest(BaseModel):
    content: str


_FORMAT_SYSTEM = """你是一个 Skill 文档格式化专家。用户会给你一段文本（可能是任意格式的流程说明、提示词、规则等），
请将其整理为以下标准 Skill Markdown 格式：

# Skill 名称

> 调用规则：一句话说明何时使用本 Skill

## 流程规划

### 步骤一
...

### 步骤二
...

要求：
- 保留原文的核心内容和逻辑，不要编造新内容
- 用中文输出
- 只输出整理后的 Markdown，不要加任何解释
"""


@router.post("/skills/format")
async def format_skill_content(body: SkillFormatRequest):
    """用 LLM 将任意文本整理为标准 Skill markdown 格式（LLM 不可用时返回原文）"""
    if not body.content.strip():
        raise VideoAgentError(
            "内容不能为空", status_code=400, error_code=LEGACY_VALIDATION_ERROR
        )
    try:
        adapter = _resolve_chat_adapter("", "")
        messages = [
            {"role": "system", "content": _FORMAT_SYSTEM},
            {"role": "user", "content": body.content},
        ]
        result = await adapter.generate(messages, temperature=0.3)
        formatted = (result.text or "").strip()
        if formatted:
            return {"content": formatted}
    except Exception as e:
        logger.warning(f"[SkillFormat] LLM 整理失败，返回原文: {e}")
    return {"content": body.content}


# ---------- Skill 优化助手（Skill 工作台右栏，非流式 v1） ----------


class SkillAssistantMessage(BaseModel):
    role: str
    content: str


class SkillAssistantRequest(BaseModel):
    """当前 Skill 全文 + 会话历史（末条为本次用户请求）；
    provider/model 与主对话胶囊同源（前端 agent-prefs），缺省回落首个可聊天供应商。"""
    content: str
    messages: List[SkillAssistantMessage] = []
    provider: str = ""
    model: str = ""


def _resolve_chat_adapter(provider: str, model: str):
    """助手/整理通道适配器解析：复用 chat_opening 的建适配套餐
    （CLI 通道拒绝 + OpenAI 端点解析 + 连接池复用）。
    依赖已在顶层导入（无循环依赖，方法内 import 为宪法第六章所禁）。"""
    if not provider:
        for p in load_merged_providers():
            if (p.get("protocol") or "") not in ("gemini-cli", "codex", "jimeng"):
                provider = str(p.get("id") or "")
                if provider:
                    break
    if not provider:
        return None
    return _create_chat_adapter(provider, model)


_ASSISTANT_SYSTEM_TMPL = """你是 Skill 优化助手，帮助用户定制/优化影视创作 Agent 的 Skill 文档。
用户会给你当前 Skill 文档全文与优化请求。
输出要求：
1. 先给不超过 150 字的简短说明（说明改了什么、为什么）；
2. 然后必须用 ```markdown 代码块输出更新后的 Skill 文档全文。
规则：
- 保留原文档头部 YAML frontmatter 声明（如有），不删除不改写；
- 保留「# 标题」与「> 调用规则：」行结构；
- 工具名只允许使用平台真实注册清单：{tool_names}；文档中的章节标签是阶段标记而非工具名，把章节标签当工具名写进 tools_required 或流程指令都属编造；
- 不写死厂商/模型/分辨率/时长参数（以全局设置为唯一权威源）；
- 用户请求不明确时保持原文不变。
"""


def _assistant_system() -> str:
    """助手 system prompt（可用工具名单动态化）。

    名单唯一源 = 平台注册表（ToolManager，画布工具补注册后取全集，
    register 幂等），不硬编码名单（防幻影工具名误导助手）。
    """
    register_canvas_tools()
    names = "/".join(sorted(ToolManager._tools))
    return _ASSISTANT_SYSTEM_TMPL.format(tool_names=names)

_ASSISTANT_BLOCK_RE = re.compile(r"```(?:markdown|md)?\s*\n(.*?)```", re.S | re.I)


def _extract_skill_block(text: str) -> Optional[str]:
    """从助手回复中提取最后一个 markdown 代码块作为新 Skill 全文；
    无代码块或不含标题行（不像 Skill 文档）时返回 None（前端只展示回复不覆盖预览）。"""
    matches = list(_ASSISTANT_BLOCK_RE.finditer(text or ""))
    if not matches:
        return None
    content = matches[-1].group(1).strip()
    if not content or "# " not in content:
        return None
    return content


@router.post("/skills/assistant")
async def skill_assistant(body: SkillAssistantRequest):
    """Skill 优化助手：单次 LLM 调用，返回 {reply, content}。
    content 为解析出的更新后全文（解析失败为 null）；前端覆盖预览草稿，
    落盘由用户点保存决定。"""
    if not body.content.strip() and not body.messages:
        raise VideoAgentError(
            "内容不能为空", status_code=400, error_code=LEGACY_VALIDATION_ERROR
        )
    try:
        adapter = _resolve_chat_adapter(body.provider, body.model)
    except Exception as e:
        # P9：未预期异常——友好文案进 message，技术细节进 raw
        raise VideoAgentError("chat 渠道不可用", status_code=503, raw=str(e)) from e
    if adapter is None:
        raise VideoAgentError(
            "无可用聊天供应商，请先在 API 配置中添加", status_code=503
        )
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": _assistant_system()},
        {"role": "user", "content": f"当前 Skill 文档全文：\n\n{body.content}"},
    ]
    # 会话历史截尾（统一口径）：真实用户轮组原子窗口，
    # 语义单一事实源 = token_budget.window_recent_turns（默认 10 轮）
    hist_dicts = [{"role": m.role, "content": m.content} for m in body.messages]
    for m in window_recent_turns(hist_dicts):
        role = m["role"] if m["role"] in ("user", "assistant") else "user"
        messages.append({"role": role, "content": m["content"]})
    try:
        result = await adapter.generate(messages, temperature=0.3)
        text = (result.text or "").strip()
    except Exception as e:
        logger.warning(f"[SkillAssistant] LLM 调用失败: {e}")
        return {"reply": f"LLM 调用失败：{e}", "content": None}
    return {"reply": text, "content": _extract_skill_block(text)}
