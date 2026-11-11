"""
/api/plugins + /api/skills — 技能配置端点

Skill 下拉数据 = 仅文档 Skill（data/skills/<slug>/SKILL.md 单一包形态）。
代码内置 Skill（编剧/分镜师/制片）已按用户要求彻底移除，不得再回到下拉框。
文档 Skill 的 system_prompt 即磁盘全文（含 frontmatter 声明头）——对话栏详情弹窗
以它为源编辑保存整文件覆盖，含声明头才不会抹掉必填键导致拒注册；用户改文档就是改流程。
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from loguru import logger

import json
from typing import Dict, List, Literal, Optional

from src.video_agent.core.sse_events import (
    SSE_DELTA,
    SSE_DONE,
    SSE_ERROR,
    SSE_REASONING_DELTA,
    SSE_STATUS,
)
from src.video_agent.exceptions import VideoAgentError
from src.video_agent.core.token_budget import window_recent_turns
from src.video_agent.web.chat_opening import _create_chat_adapter
from src.video_agent.web.error_payload import LEGACY_NOT_FOUND, LEGACY_VALIDATION_ERROR
from src.video_agent.core.provider_config import (
    exclude_retired_mock_providers,
    load_merged_providers,
)
from src.video_agent.state.manager import StateManager
from src.video_agent.skill_runtime import frontmatter, registry as skill_registry
from src.video_agent.web.skill_authoring import (
    build_create_system,
    repair_messages,
    validate_skill_draft,
)
from src.video_agent.web.skill_doc_stream import (
    DocStreamSplitter,
    SSE_DOC_DELTA,
    extract_skill_doc,
)
from src.video_agent.web.skill_docs import (
    get_skill_doc,
    list_skill_docs,
    list_skill_doc_history,
    list_skill_sections,
    save_skill_doc,
    delete_skill_doc,
    lint_skill_content,
)

router = APIRouter()


# ---------- Skill 文档响应模型 ----------

class SkillDoc(BaseModel):
    """Skill 文档（列表/单读同形；_parse_doc 恒下发 slug/name，多余键静默过滤）"""
    slug: str
    name: str
    description: str = ""
    content: str = ""


class SkillLoadFailure(BaseModel):
    """坏包失败项（注册 fail-closed，但界面要看见原因）。"""
    slug: str
    error: str


class SkillDocsResponse(BaseModel):
    docs: List[SkillDoc] = []
    failed: List[SkillLoadFailure] = []


class SkillDocVersion(BaseModel):
    """Skill 文档历史版本（保存前自动备份，新→旧；两键恒下发）"""
    version: str
    content: str


class SkillDocHistoryResponse(BaseModel):
    versions: List[SkillDocVersion] = []


@router.get("/plugins/ftdyb-agent/config")
async def get_agent_config():
    """前端 agentSkillSelect 下拉框数据源：仅文档 Skill（用户可见可编辑）。

    代码形态 Skill（内置类注册器）不进下拉（注册器整包已移除），
    防用户删过的「编剧/分镜师/制片 Agent」复活。

    M3 批2（2026-08-30 裁决：注册表=加载唯一门户）：对话栏从注册条目派生，
    与 AI 可用性对齐——被拒注册包（坏 frontmatter/版本锁不符）不出现在对话栏；
    修复入口留在工作台 /api/skills/docs（磁盘全量，不动）。
    """
    doc_skills = []
    for e in skill_registry.loadable_entries():
        doc_skills.append({
            "id": f"doc:{e.slug}",
            "name": e.name,
            "description": str((e.manifest or {}).get("description") or "").strip(),
            # 磁盘全文含 frontmatter 下发（对话栏弹窗编辑保存整文件覆盖不丢声明头；
            # 注册派生只影响「哪些包出现」，不改变内容形状；磁盘读取失败兜底注册解析正文）
            "system_prompt": (get_skill_doc(e.slug) or {}).get("content") or e.content,
            "source": "doc",
            "slug": e.slug,
            # 欠账显性化——规划级执行器名单随契约下发，
            # 前端据实标注（不硬编码工具名）
            "planning_executors": _planning_executors_of(e.name),
        })
    return {"skills": doc_skills}


def _planning_executors_of(skill_name: str):
    """规划级执行器名单（前端契约字段保留）：执行器已退役，
    永远返回空名单（前端据实标注，空 = 无规划级欠账）。"""
    return []


@router.get("/skills/docs", response_model=SkillDocsResponse)
async def get_skill_docs():
    """文档面板：Skill 文档列表（含全文）+ 坏包失败清单（只读旁路）。"""
    failed = [
        {"slug": slug, "error": err}
        for slug, err in sorted(skill_registry.scan_failures().items())
    ]
    return {"docs": list_skill_docs(), "failed": failed}


class ActiveSkillRequest(BaseModel):
    slug: str
    source: str = "user"


@router.post("/skills/active")
async def set_active_skill(body: ActiveSkillRequest):
    """项目态 Skill 显式绑定（激活事实归项目态）。

    slug 非空 = 显式绑定（校验文档存在 + usedSkills 留账）；
    slug 空 = **清除显式偏好**（不再是「关闭技能」——2026-10-16 用户裁决：
    文档区 Skill 是唯一权威，项目登记过的 Skill 一律生效；空值由
    registry.fallback_skill_from_state 回落 usedSkills，与该字段缺失同义）。
    界面侧已无任何入口写空值（芯片 ✕ / 「不使用技能」卡 / 删除顺带摘除均已移除），
    本形参保留仅为向后兼容存量调用方。状态写入唯一走 StateManager。
    """
    svc = StateManager.get_instance()
    slug = str(body.slug or "").strip()
    source = "suggested" if body.source == "suggested" else "user"
    if slug:
        if not get_skill_doc(slug):
            raise VideoAgentError(
                f"Skill '{slug}' 不存在", status_code=404,
                error_code=LEGACY_NOT_FOUND,
            )
        svc.record_used_skill(slug)
    svc.set_active_skill(slug, source)
    svc.record_flow_event(
        "skill_active",
        f"{'清除显式 Skill 偏好（回落文档区登记）' if not slug else '显式绑定 ' + slug}"
        f"（来源：{'建议采纳' if source == 'suggested' else '用户选择'}）",
    )
    logger.info(f"[Skills] 活跃 Skill 绑定更新: slug={slug or '（清除偏好）'} source={source}")
    return {"ok": True, "active_skill": svc.state_dict.get("activeSkill")}


class SkillDocSave(BaseModel):
    content: str


@router.put("/skills/docs/{slug}")
async def put_skill_doc(slug: str, body: SkillDocSave):
    """保存 Skill 文档（新建或覆盖）；lint 结果随响应下发（只告警不阻断，
    前端 toast 回显——体量/外部标杆 组成/frontmatter 声明体检等编辑期可见）"""
    try:
        doc = save_skill_doc(slug, body.content)
    except ValueError as e:
        raise VideoAgentError(
            str(e), status_code=400, error_code=LEGACY_VALIDATION_ERROR
        ) from e
    lint = lint_skill_content(body.content, slug=slug)
    return {"ok": True, "doc": doc, "lint": lint}


@router.get("/skills/docs/{slug}", response_model=SkillDoc)
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


@router.get("/skills/docs/{slug}/history", response_model=SkillDocHistoryResponse)
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
请将其整理为通用 Agent Skills 的 Markdown 格式：

---
name: Skill 名称
description: 一句话说明何时使用本 Skill
---

# Skill 名称

## 一、这个 Skill 做什么
目标、用户给什么、最后交付什么。

## 二、开工前先确认
启动前必须问清的信息。

## 三、制作流程
步骤、依赖关系、关键暂停点。

## 四、专业方法
分类、拆解、提示词写法、自检清单等。

## 五、参考资料
需要时读取 references/… 分册。

要求：
- 保留原文的核心内容和逻辑，不要编造新内容
- 用中文输出
- 只用 Markdown 标题分节，不要使用平台私有标签（planner 等尖括号章节名）
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
        if adapter is None:
            return {"content": body.content}
        messages = [
            {"role": "system", "content": _FORMAT_SYSTEM},
            {"role": "user", "content": body.content},
        ]
        # 统一走 BaseChatAdapter.chat（generate 是媒体适配器接口，chat 适配器没有）
        result = await adapter.chat(messages, temperature=0.3)
        formatted = (result.content or "").strip()
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
    provider/model 与主对话胶囊同源（前端 agent-prefs），缺省回落首个可聊天供应商。
    mode=create：新建 Skill 的创作模式（通用标题式契约 + 服务端自检/一次自修复）；
    mode=optimize：改写既有 Skill（保留原结构）。"""
    content: str
    messages: List[SkillAssistantMessage] = []
    provider: str = ""
    model: str = ""
    mode: Literal["optimize", "create"] = "optimize"


def _resolve_chat_adapter(provider: str, model: str):
    """助手/整理通道适配器解析：复用 chat_opening 的建适配套餐
    （CLI 通道拒绝 + OpenAI 端点解析 + 连接池复用）。
    依赖已在顶层导入（无循环依赖，方法内 import 为宪法第六章所禁）。"""
    if not provider:
        # mock 退役过滤经唯一收口点（provider_config.exclude_retired_mock_providers）
        for p in exclude_retired_mock_providers(load_merged_providers()):
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
2. 然后输出独占一行的 <<<SKILL_DOC>>>，紧跟更新后的 Skill 文档全文，最后以独占一行的 <<<END_SKILL_DOC>>> 结束；整篇文档不要再包一层代码围栏（文档内部示例代码块照常使用 ```）。
规则：
- 保留原文档头部 YAML frontmatter 声明（如有），不删除不改写；
- 保留原文档的标题式章节结构：用 Markdown 标题（# / ##）分节；不要引入平台私有标签（planner 等尖括号章节名），也不要中途换成标签格式；
- 用自然语言写清每一步做什么、产出什么、依赖什么；不要在文档里罗列具体工具名或工具清单（平台模型会按描述自行选择工具）；章节标题是文档结构，不是工具名；原文档已有工具清单/工具名时，改写时删除或改为自然语言；
- 文档用中文散文写，不要写成 API 字段说明；不要用平台内部字段名/字段表（如 shot_id、beat、duration、shot_size、camera、subject_action、expression、props、background、gag、transition、on_screen_text、audio_cue、character_id、scene_id、prop_id、assets、shots、music_id、sfx_id、vocal_id）；原有字段表改写成「第 1 镜：……」段落；
- 提示词示例用正文段落或 > 引用块，不要用 ``` 代码块，也不要「模板 A/B/C/D」这种代码卡片式标题；参考库里已有 Skill 的散文节奏：先讲原则，再讲具体做法；
- 不写死厂商/模型/分辨率/时长参数（以全局设置为唯一权威源）；
- 用户请求不明确时保持原文不变。
"""


def _assistant_system() -> str:
    """助手 system prompt：自然语言流程，不注入工具目录（2026-10-26 用户裁决）。"""
    return _ASSISTANT_SYSTEM_TMPL


def _extract_skill_block(text: str) -> Optional[str]:
    """从助手回复中提取 Skill 全文（哨兵/围栏/裸文档，口径见 skill_doc_stream）。"""
    _, content, _ = extract_skill_doc(text)
    return content


def _doc_name(doc: str) -> str:
    """frontmatter name（完成摘要用；解析失败返回空串）。"""
    declaration, _, err = frontmatter.split_frontmatter(doc or "")
    if err or not declaration:
        return ""
    return str(declaration.get("name") or "").strip()


def _completion_summary(
    doc: str, checks: Optional[Dict[str, object]], mode: str,
) -> str:
    """完成摘要（确定性文案）：章节数 + 自检结果 + 保存引导。"""
    sections = list_skill_sections(doc or "")
    name = _doc_name(doc)
    if name:
        head = f"已生成「{name}」草稿" if mode == "create" else f"已更新「{name}」"
    else:
        head = "已生成 Skill 草稿" if mode == "create" else "已更新 Skill 文档"
    parts = [f"{head}：{len(sections)} 个章节" if sections else head]
    if checks is not None:
        issues = checks.get("issues") or []
        parts.append(
            "自检通过"
            if checks.get("passed")
            else f"自检发现 {len(issues)} 项待补（见下方清单）"
        )
    parts.append("左侧预览已更新，确认后点「保存」落盘")
    return " · ".join(parts)


# 聊天区模型短说明的字数帽（用户裁决：说明只保留摘要级信息）
_REPLY_PREAMBLE_LIMIT = 200


def _display_reply(
    text: str, has_content: bool, doc: Optional[str] = None,
    *, mode: str = "optimize", checks: Optional[Dict[str, object]] = None,
) -> str:
    """聊天区展示文案：模型短说明 + 确定性完成摘要（文档正文只进预览）。"""
    preamble, extracted, _ = extract_skill_doc(text or "")
    cleaned = (preamble or "").strip()
    if len(cleaned) > _REPLY_PREAMBLE_LIMIT:
        cleaned = cleaned[:_REPLY_PREAMBLE_LIMIT - 1] + "…"
    if not has_content:
        return cleaned
    summary = _completion_summary(doc or extracted or "", checks, mode)
    return f"{cleaned}\n\n{summary}" if cleaned else summary


def _assistant_messages(
    body: "SkillAssistantRequest", system_prompt: str,
) -> List[Dict[str, str]]:
    """system + 当前全文 + 截尾历史：非流式/流式同一组装口径。

    会话历史截尾（统一口径）：真实用户轮组原子窗口，
    语义单一事实源 = token_budget.window_recent_turns（默认 10 轮）。
    """
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"当前 Skill 文档全文：\n\n{body.content}"},
    ]
    hist_dicts = [{"role": m.role, "content": m.content} for m in body.messages]
    for m in window_recent_turns(hist_dicts):
        role = m["role"] if m["role"] in ("user", "assistant") else "user"
        messages.append({"role": role, "content": m["content"]})
    return messages


_STYLE_ISSUE_MARKERS = ("平台内部字段", "代码块")


def _needs_style_repair(issues: List[str]) -> bool:
    """优化模式只在文风类问题上自修复一次（不因既有结构调整而重写）。"""
    return any(
        marker in issue for issue in issues for marker in _STYLE_ISSUE_MARKERS
    )


async def _maybe_repair_draft(
    adapter, messages, text, content, issues, *, create_mode: bool = True,
):
    """一次自修复：把机械自检问题回喂，整篇重写后取问题更少的一版。
    失败不阻断：保留首版草稿 + 问题清单，用户仍可手改/保存。"""
    try:
        fixed = await adapter.chat(
            repair_messages(messages, content, issues), temperature=0.2,
            thinking_level="",
        )
        fixed_text = (fixed.content or "").strip()
        fixed_content = _extract_skill_block(fixed_text)
        if fixed_content:
            fixed_issues = validate_skill_draft(
                fixed_content, create_mode=create_mode,
            )
            if len(fixed_issues) < len(issues):
                logger.info(
                    f"[SkillAssistant] 草稿自修复：{len(issues)} → "
                    f"{len(fixed_issues)} 项问题"
                )
                return fixed_text, fixed_content, fixed_issues
    except Exception as e:
        logger.warning(f"[SkillAssistant] 创作草稿自修复失败: {e}")
    return text, content, issues


@router.post("/skills/assistant")
async def skill_assistant(body: SkillAssistantRequest):
    """Skill 优化/创作助手：单次 LLM 调用（创作模式最多一次自修复），
    返回 {reply, content, checks}。content 为解析出的全文（解析失败为 null）；
    前端覆盖预览草稿，落盘由用户点保存决定。"""
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
    # 创作模式：通用标题式契约 + 工具目录；优化模式：保留既有结构
    system_prompt = build_create_system() if body.mode == "create" else _assistant_system()
    messages = _assistant_messages(body, system_prompt)
    try:
        # 统一走 BaseChatAdapter.chat（generate 是媒体适配器接口，chat 适配器没有）；
        # thinking_level="" = 按模型编辑面板（chat_models_meta）的开关/档位注入
        result = await adapter.chat(
            messages, temperature=0.3, thinking_level="",
        )
        text = (result.content or "").strip()
    except Exception as e:
        logger.warning(f"[SkillAssistant] LLM 调用失败: {e}")
        return {"reply": f"LLM 调用失败：{e}", "content": None, "checks": None}

    _, content, source = extract_skill_doc(text)
    checks: Optional[Dict[str, object]] = None
    if content:
        issues = validate_skill_draft(content, create_mode=body.mode == "create")
        if issues and (body.mode == "create" or _needs_style_repair(issues)):
            text, content, issues = await _maybe_repair_draft(
                adapter, messages, text, content, issues,
                create_mode=body.mode == "create",
            )
        checks = {"passed": not issues, "issues": issues}
    logger.info(
        f"[SkillAssistant] 完成: {len(text)} 字, 提取来源={source}, "
        f"content={'有' if content else '无'}"
    )
    return {
        "reply": _display_reply(
            text, bool(content), content, mode=body.mode, checks=checks,
        ),
        "content": content,
        "checks": checks,
    }


# ---------- Skill 优化助手（SSE 流式 v2：思考与正文实时下发） ----------

# SSE 帧头：与主对话 event stream 同口径（禁缓存/禁代理缓冲）
_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse_frame(payload: Dict[str, object]) -> str:
    """SSE data 帧（中文直出，前端 JSON.parse 即读）。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/skills/assistant/stream")
async def skill_assistant_stream(body: SkillAssistantRequest):
    """Skill 优化/创作助手（SSE 流式）：思考/正文实时下发。

    事件名复用主链约定（reasoning_delta/delta/status/done/error），
    载荷为本端点专属形状；done 帧携带 {reply, content, checks}，
    与非流式 /skills/assistant 同一业务语义，前端据此收敛草稿与自检徽标。
    """
    if not body.content.strip() and not body.messages:
        raise VideoAgentError(
            "内容不能为空", status_code=400, error_code=LEGACY_VALIDATION_ERROR
        )
    try:
        adapter = _resolve_chat_adapter(body.provider, body.model)
    except Exception as e:
        raise VideoAgentError("chat 渠道不可用", status_code=503, raw=str(e)) from e
    if adapter is None:
        raise VideoAgentError(
            "无可用聊天供应商，请先在 API 配置中添加", status_code=503
        )
    system_prompt = build_create_system() if body.mode == "create" else _assistant_system()
    messages = _assistant_messages(body, system_prompt)

    async def event_stream():
        # 累积全文 → 每帧切分：聊天段发 delta，文档段发 doc_delta（预览实时跟进）
        buf = ""
        splitter = DocStreamSplitter()
        try:
            async for chunk in adapter.chat_stream(
                messages, temperature=0.3, thinking_level="",
            ):
                if chunk.type == "reasoning_delta" and chunk.text:
                    yield _sse_frame({"type": SSE_REASONING_DELTA, "text": chunk.text})
                elif chunk.type == "text_delta" and chunk.text:
                    buf += chunk.text
                    for channel, delta in splitter.feed(buf):
                        if not delta:
                            continue
                        event = SSE_DELTA if channel == "chat" else SSE_DOC_DELTA
                        yield _sse_frame({"type": event, "text": delta})
        except Exception as e:
            logger.warning(f"[SkillAssistant] 流式调用失败: {e}")
            yield _sse_frame({"type": SSE_ERROR, "message": f"LLM 调用失败：{e}"})
            return
        # 收尾：把 holdback 的聊天尾巴发完（文档尾巴由 done.content 权威覆盖）
        for channel, delta in splitter.flush(buf):
            if not delta:
                continue
            event = SSE_DELTA if channel == "chat" else SSE_DOC_DELTA
            yield _sse_frame({"type": event, "text": delta})
        text = buf.strip()
        _, content, source = extract_skill_doc(text)
        # 诊断可见：模型输出长度/提取来源/是否解析出全文（预览不动时先查这条日志）
        logger.info(
            f"[SkillAssistant] 流式完成: {len(text)} 字, 提取来源={source}, "
            f"content={'有' if content else '无'}"
        )
        checks: Optional[Dict[str, object]] = None
        if content:
            issues = validate_skill_draft(content, create_mode=body.mode == "create")
            if issues and (body.mode == "create" or _needs_style_repair(issues)):
                # 自修复为非流式补调：先下发状态帧，避免长时间静默
                yield _sse_frame({
                    "type": SSE_STATUS,
                    "text": "草稿自检发现待补项，正在自动修复…",
                })
                text, content, issues = await _maybe_repair_draft(
                    adapter, messages, text, content, issues,
                    create_mode=body.mode == "create",
                )
            checks = {"passed": not issues, "issues": issues}
        yield _sse_frame({
            "type": SSE_DONE,
            "reply": _display_reply(
                text, bool(content), content, mode=body.mode, checks=checks,
            ),
            "content": content,
            "checks": checks,
        })

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=_STREAM_HEADERS,
    )
