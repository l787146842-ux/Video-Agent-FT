"""
/api/agent — Agent 聊天端点

流程：服务端构建上下文 → 多步 LLM 循环（≤3 轮）→ 解析并执行 studio-actions → 持久化 → 返回。

- 上下文注入在服务端完成（前端只发消息本体 + 选中态），服务端是唯一事实源；
- 仅当 provider 为空/mock 时走 mock；真实供应商失败返回 502 + 真实错误。
"""
import asyncio
import json
import os
import time
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from loguru import logger

from src.video_agent.web.actions import StudioActionExecutor
from src.video_agent.web.generation import resolve_openai_endpoint
from src.video_agent.web.provider_config import is_mock_provider
from src.video_agent.state.manager import StateManager
from src.video_agent.utils.prompts import load_prompt
from src.video_agent.utils.paths import ASSETS_DIR
from src.video_agent.config import settings
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.exceptions import AdapterError, GenerationError
from src.video_agent.adapters.openai_compat import OpenAICompatChatAdapter
from src.video_agent.tools.manager import ToolManager

router = APIRouter()

UPLOAD_ASSETS_DIR = ASSETS_DIR

# 服务端基础 URL（用于将本地路径转为绝对 URL 供 LLM 访问）
_SERVER_BASE_URL = f"http://127.0.0.1:{os.getenv('PORT', '8000')}"

# 文本类素材直接把正文注入给 LLM；单文档上限防止把上下文撑爆
_TEXT_DOC_EXTS = {".md", ".txt"}
_MAX_DOC_CHARS = settings.max_doc_chars
_MAX_ATTACHMENTS = settings.max_attachments

## Studio Actions Protocol 系统提示词（Rule4: 从 prompts/ 目录加载，服务端唯一权威版本）
STUDIO_ACTION_PROTOCOL_PROMPT = load_prompt("planner/system.md")


class ChatRequest(BaseModel):
    message: str
    system_prompt: str = ""          # 前端 skill 的角色提示词（服务端会追加协议与上下文）
    provider: str = ""
    model: str = ""
    ms_model: str = ""
    messages: List[Dict[str, str]] = []
    images: List[str] = []
    videos: List[str] = []
    # 本次消息携带的上传素材（服务端负责绑定资产 + 读取文本正文注入 LLM）
    attachments: List[Dict[str, str]] = []
    # 前端选中态——"current" 的解析依据
    selected_draft_id: str = ""
    selected_type: str = ""
    # 上下文模式：studio=注入协议+工作台状态；none=纯文本调用（如音频规划）
    context_mode: str = "studio"
    asset_mode: str = "bound"


class ChatResponse(BaseModel):
    text: str
    applied_actions: int = 0
    steps: int = 1
    warnings: List[str] = []
    confirmation: str = ""            # 非空 = agent 暂停等待用户确认
    documents_written: List[str] = []  # 本轮写入/更新的文档名
    state: Optional[Dict[str, Any]] = None


def _bind_attachments(svc: StateManager, attachments: List[Dict[str, str]]) -> None:
    """把本次消息携带的上传素材登记进服务端资产列表（isBound=True）并持久化"""
    if not attachments:
        return
    assets = svc.state_dict.setdefault("assets", [])
    changed = False
    for att in attachments[:_MAX_ATTACHMENTS]:
        url = att.get("url", "")
        name = att.get("name") or url or "上传素材"
        if not url:
            continue
        existing = next((a for a in assets if a.get("url") == url), None)
        if existing:
            existing["isBound"] = True
        else:
            assets.insert(0, {
                "id": att.get("id") or f"ast-{int(time.time())}-{random.randint(100, 999)}",
                "name": name,
                "type": att.get("kind") or "file",
                "isBound": True,
                "url": url,
            })
        changed = True
    if changed:
        svc.save()


def _attachment_context(attachments: List[Dict[str, str]]) -> str:
    """
    为 LLM 构建素材说明：文本类文档（.md/.txt）直接读出正文注入；
    其他类型给出明确的能力说明，避免 LLM 瘘猜「我看不到素材」或假装看过。
    """
    parts: List[str] = []
    for att in attachments[:_MAX_ATTACHMENTS]:
        url = att.get("url", "")
        name = att.get("name") or url or "素材"
        if not url.startswith("/workspace/assets/"):
            parts.append(f"（用户提供了外部素材《{name}》，URL: {url}）")
            continue
        # 只取 basename，防止路径穿越
        fpath = UPLOAD_ASSETS_DIR / Path(url).name
        ext = fpath.suffix.lower()
        if ext in _TEXT_DOC_EXTS:
            if not fpath.exists():
                parts.append(f"（素材文档《{name}》未在服务器上找到，请让用户重新上传）")
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                parts.append(f"（素材文档《{name}》读取失败：{e}）")
                continue
            truncated = ""
            if len(content) > _MAX_DOC_CHARS:
                content = content[:_MAX_DOC_CHARS]
                truncated = f"\n……（正文超长，已截断为前 {_MAX_DOC_CHARS} 字）"
            parts.append(f"=== 用户上传的素材文档《{name}》全文 ===\n{content}{truncated}\n=== 文档结束 ===")
        elif ext in (".pdf", ".docx"):
            parts.append(
                f"（用户上传了 {ext} 文档《{name}》，服务端暂不支持解析该格式正文；"
                f"请告知用户粘贴关键内容，或改用 .md/.txt）"
            )
        else:
            kind = att.get("kind") or "文件"
            parts.append(f"（用户上传并绑定了{kind}素材《{name}》，URL: {url}，可作为参考图/引用资产使用）")
    return "\n\n".join(parts)


def _collect_image_urls_from_attachments(attachments: List[Dict[str, str]]) -> List[str]:
    """从附件中提取图片 URL（用于多模态 vision 注入）"""
    image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    urls: List[str] = []
    for att in attachments[:_MAX_ATTACHMENTS]:
        kind = att.get("kind") or ""
        url = att.get("url") or ""
        if not url:
            continue
        if kind == "image":
            urls.append(url)
        elif kind in ("file", ""):
            # 根据扩展名判断
            ext = Path(url).suffix.lower()
            if ext in image_exts:
                urls.append(url)
    return urls


@router.post("/agent/chat")
@router.post("/canvas-llm")
@router.post("/chat")              # 设计方案路径别名
async def agent_chat(body: ChatRequest):
    svc = StateManager.get_instance()
    executor = StudioActionExecutor(
        svc,
        selected_draft_id=body.selected_draft_id,
        selected_type=body.selected_type,
    )

    user_text = body.message.strip()
    if not user_text and not body.attachments:
        raise HTTPException(status_code=400, detail="消息不能为空")
    if not user_text:
        user_text = "请查看我上传的素材"

    use_studio_context = body.context_mode != "none"

    # 附件：登记进资产列表 + 把文本文档正文注入给 LLM
    attachment_note = _attachment_context(body.attachments) if body.attachments else ""
    llm_user_text = f"{user_text}\n\n{attachment_note}" if attachment_note else user_text

    # ---------- mock 路径（仅显式选择 mock / 未配置供应商） ----------
    if is_mock_provider(body.provider, body.model):
        async with svc.lock:
            if use_studio_context:
                _bind_attachments(svc, body.attachments)
                svc.add_chat_message("user", user_text)
            raw_reply = _mock_llm_reply(llm_user_text, svc.build_agent_context(body.asset_mode))
            actions = executor.parse_actions_from_reply(raw_reply)
            visible = executor.strip_action_blocks(raw_reply) or raw_reply
            applied = executor.execute(actions)
            if use_studio_context:
                svc.add_chat_message("agent", visible)
        return ChatResponse(
            text=visible,
            applied_actions=applied,
            steps=1,
            warnings=["当前为 mock 供应商，回复由本地规则生成，未调用真实 LLM"],
            state=svc.get_full_snapshot(),
        )

    # ---------- 真实供应商：通过 Planner 处理（Rule1: Planner 是唯一入口） ----------
    history = [
        {"role": m.get("role", "user"), "content": m.get("content", "")}
        for m in body.messages[-10:]
    ]

    # 构建 LLM Adapter（每次请求根据用户选择的供应商/模型动态创建）
    try:
        base_url, api_key, effective_model = resolve_openai_endpoint(body.provider, body.model)
    except GenerationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    llm_adapter = OpenAICompatChatAdapter(base_url=base_url, api_key=api_key, model=effective_model)
    planner = Planner(llm_adapter=llm_adapter, tool_manager=ToolManager)

    planner_ctx = PlannerContext(
        history=history,
        selected_draft_id=body.selected_draft_id,
        selected_type=body.selected_type,
        state_json=svc.build_agent_context(body.asset_mode) if use_studio_context else "",
        extra_system=body.system_prompt.strip(),
        use_studio_context=use_studio_context,
        asset_mode=body.asset_mode,
    )

    # 整个多步回合持锁：并发请求会排队而不是交叉改写共享状态
    async with svc.lock:
        if use_studio_context:
            _bind_attachments(svc, body.attachments)
            svc.add_chat_message("user", user_text)
        try:
            result = await planner.handle_message(llm_user_text, planner_ctx)
        except (GenerationError, AdapterError) as e:
            logger.warning(f"[Agent] LLM 调用失败: {e}")
            if use_studio_context:
                svc.add_chat_message("agent", f"[错误] {e}")
            raise HTTPException(status_code=502, detail=str(e))

        if use_studio_context:
            svc.add_chat_message("agent", result.text)

    logger.info(
        f"[Agent] user='{user_text[:50]}...' steps={result.steps} "
        f"actions={result.applied_actions} warnings={len(result.warnings)}"
    )

    return ChatResponse(
        text=result.text,
        applied_actions=result.applied_actions,
        steps=result.steps,
        warnings=result.warnings,
        confirmation=result.confirmation,
        documents_written=result.documents_written,
        state=svc.get_full_snapshot() if use_studio_context else None,
    )




@router.post("/agent/chat/stream")
@router.post("/canvas-llm/stream")
@router.post("/chat/stream")       # 设计方案路径别名
async def agent_chat_stream(body: ChatRequest):
    """
    流式聊天端点（SSE）。事件类型：
    - status: 阶段提示（连接/第 N 轮推理/执行操作/生成指令…）
    - delta:  可见回复的增量文本
    - done:   最终结果（与非流式 ChatResponse 字段一致 + elapsed_ms）
    - error:  失败信息
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: Dict[str, Any]) -> None:
        await queue.put(event)

    async def worker() -> None:
        t0 = time.monotonic()
        try:
            svc = StateManager.get_instance()
            executor = StudioActionExecutor(
                svc,
                selected_draft_id=body.selected_draft_id,
                selected_type=body.selected_type,
            )

            user_text = body.message.strip()
            if not user_text and not body.attachments:
                await emit({"type": "error", "detail": "消息不能为空"})
                return
            if not user_text:
                user_text = "请查看我上传的素材"

            use_studio_context = body.context_mode != "none"
            attachment_note = _attachment_context(body.attachments) if body.attachments else ""
            llm_user_text = f"{user_text}\n\n{attachment_note}" if attachment_note else user_text

            # 收集图片附件，构建多模态 content（让 LLM 能真正“看到”图片）
            image_urls = _collect_image_urls_from_attachments(body.attachments) if body.attachments else []
            # 也包含前端显式传入的 images 字段
            for img_url in (body.images or []):
                if img_url and img_url not in image_urls:
                    image_urls.append(img_url)

            if image_urls:
                # 多模态消息：文本 + 图片 parts
                content_parts: List[Dict[str, Any]] = [{"type": "text", "text": llm_user_text}]
                for img_url in image_urls[:4]:
                    # 本地路径转为绝对 URL
                    abs_url = img_url
                    if img_url.startswith("/workspace/"):
                        abs_url = f"{_SERVER_BASE_URL}{img_url}"
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": abs_url}
                    })
                llm_user_content: Any = content_parts
                logger.info(f"[Agent] 多模态消息：{len(image_urls)} 张图片已注入 LLM 上下文")
            else:
                llm_user_content = llm_user_text

            # ---------- mock：模拟流式，保持一致的交互体验 ----------
            if is_mock_provider(body.provider, body.model):
                async with svc.lock:
                    if use_studio_context:
                        _bind_attachments(svc, body.attachments)
                        svc.add_chat_message("user", user_text)
                    await emit({"type": "status", "text": "mock 模式：本地规则生成…"})
                    raw_reply = _mock_llm_reply(llm_user_text, svc.build_agent_context(body.asset_mode))
                    actions = executor.parse_actions_from_reply(raw_reply)
                    visible = executor.strip_action_blocks(raw_reply) or raw_reply
                    for i in range(0, len(visible), 8):
                        await emit({"type": "delta", "text": visible[i:i + 8]})
                        await asyncio.sleep(0.02)
                    applied = executor.execute(actions)
                    if use_studio_context:
                        svc.add_chat_message("agent", visible)
                await emit({"type": "done", "payload": {
                    "text": visible,
                    "applied_actions": applied,
                    "steps": 1,
                    "warnings": ["当前为 mock 供应商，回复由本地规则生成，未调用真实 LLM"],
                    "confirmation": "",
                    "documents_written": executor.documents_written,
                    "state": svc.get_full_snapshot(),
                    "elapsed_ms": int((time.monotonic() - t0) * 1000),
                }})
                return

            # ---------- 真实供应商：通过 Planner 流式处理（§5: AsyncGenerator 穿透 SSE） ----------
            history = [
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in body.messages[-10:]
            ]

            async with svc.lock:
                if use_studio_context:
                    _bind_attachments(svc, body.attachments)
                    svc.add_chat_message("user", user_text)

                try:
                    base_url, api_key, effective_model = resolve_openai_endpoint(body.provider, body.model)
                    llm_adapter = OpenAICompatChatAdapter(base_url=base_url, api_key=api_key, model=effective_model)
                    planner = Planner(llm_adapter=llm_adapter, tool_manager=ToolManager)

                    planner_ctx = PlannerContext(
                        history=history,
                        selected_draft_id=body.selected_draft_id,
                        selected_type=body.selected_type,
                        state_json=svc.build_agent_context(body.asset_mode) if use_studio_context else "",
                        extra_system=body.system_prompt.strip(),
                        use_studio_context=use_studio_context,
                        asset_mode=body.asset_mode,
                    )

                    final_text = ""
                    final_payload: Dict[str, Any] = {}

                    async for event in planner.handle_message_stream(llm_user_content, planner_ctx):
                        if event.type == "status":
                            await emit({"type": "status", "text": event.text})
                        elif event.type == "delta":
                            await emit({"type": "delta", "text": event.text})
                        elif event.type == "actions_applied":
                            await emit({"type": "status", "text": event.text})
                        elif event.type == "done":
                            final_payload = event.payload or {}
                            final_text = final_payload.get("text", "")
                        elif event.type == "error":
                            raise AdapterError(event.text)

                    if use_studio_context and final_text:
                        svc.add_chat_message("agent", final_text)

                    await emit({"type": "done", "payload": {
                        **final_payload,
                        "documents_written": [],
                        "state": svc.get_full_snapshot() if use_studio_context else None,
                        "elapsed_ms": int((time.monotonic() - t0) * 1000),
                    }})

                except (GenerationError, AdapterError) as e:
                    logger.warning(f"[Agent] LLM 流式调用失败: {e}")
                    if use_studio_context:
                        svc.add_chat_message("agent", f"[错误] {e}")
                    await emit({"type": "error", "detail": str(e)})
                    return
        except Exception as e:
            logger.exception(f"[Agent] 流式处理异常: {e}")
            await emit({"type": "error", "detail": f"服务端异常: {e}"})

    task = asyncio.create_task(worker())

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") in ("done", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def _mock_llm_reply(user_text: str, context: str) -> str:
    """
    Mock LLM（仅在用户显式选择 mock 供应商时使用）。
    分支顺序：修改/优化 先于 拆解，避免「修改分镜」被误路由到拆解分支。
    """
    if any(kw in user_text for kw in ["确认", "通过", "定稿", "锁定", "采用"]):
        reply = "好的，已将当前草稿标记为「已确认」。后续生成任务将优先使用已确认的版本。"
        actions_block = '```studio-actions\n[{"action":"confirm_draft","draft_type":"current","draft_id":"current"}]\n```'
    elif any(kw in user_text for kw in ["修改", "调整", "优化", "改写", "提示词"]):
        reply = (
            "已根据你的意见优化了提示词，增强了画面细节和电影感。"
            "新版本强调了光影层次、材质纹理和镜头语言。"
        )
        actions_block = '```studio-actions\n[{"action":"update_draft","draft_type":"current","draft_id":"current","patch":{"tag":"已优化","prompt":"电影级光影，超高细节，8K 分辨率，赛博朋克现实主义，体积光，景深虚化"}}]\n```'
    elif any(kw in user_text for kw in ["拆解", "解析", "拆分", "分镜", "上传", "文档", "已上传并绑定素材"]):
        reply = (
            "已根据你提供的素材拆解出关键元素和分镜，请查看左侧故事板。"
            "每个分组都带有可执行的生成提示词，你可以点击生成图片。"
        )
        actions_block = '```studio-actions\n[{"action":"add_group","group_type":"keyElement","title":"关键元素：核心视觉设定","desc":"从素材中提取的核心视觉元素","draft":{"label":"概念图","tag":"Agent","mediaType":"image","prompt":"电影级概念图，超高细节，8K 分辨率，体积光，景深虚化"}},{"action":"add_group","group_type":"shot","title":"分镜1：全景—建立镜头","desc":"开场全景建立镜头","draft":{"label":"全景镜头","tag":"Agent","mediaType":"image","prompt":"电影级全景建立镜头，宽银幕构图，自然光，8K"}}]\n```'
    elif any(kw in user_text for kw in ["新增", "添加", "加一个", "再来"]):
        reply = "已为当前分组新增了一个草稿卡片，你可以点击左侧查看。"
        actions_block = '```studio-actions\n[{"action":"add_draft","group_type":"keyElement","group_id":"current","draft":{"label":"Agent 新草稿","tag":"Agent","mediaType":"image","prompt":"新增概念图，电影级采光"}}]\n```'
    elif any(kw in user_text for kw in ["绑定", "素材", "参考图"]):
        reply = "已将素材绑定到当前草稿的参考输入。"
        actions_block = '```studio-actions\n[{"action":"bind_asset","name":"Agent 绑定素材","type":"image","url":"https://picsum.photos/id/1069/400/300"}]\n```'
    else:
        ke_count = context.count('"id": "ke-')
        shot_count = context.count('"id": "shot-')
        reply = (
            f"收到！我来分析一下你的需求：「{user_text}」\n\n"
            f"当前项目状态：{ke_count} 个关键元素、{shot_count} 个分镜。"
            f"你可以告诉我需要调整哪个部分，比如：\n"
            f"- 修改某个草稿的提示词\n"
            f"- 确认/通过某个草稿\n"
            f"- 新增一个分镜或关键元素\n"
            f"- 绑定参考素材"
        )
        actions_block = ""

    return f"{reply}\n\n{actions_block}".strip() if actions_block else reply
