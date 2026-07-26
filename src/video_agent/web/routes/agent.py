"""
/api/agent — Agent 聊天端点

流程：服务端构建上下文 → 多步 LLM 循环（≤3 轮）→ 解析并执行 studio-actions → 持久化 → 返回。

- 上下文注入在服务端完成（前端只发消息本体 + 选中态），服务端是唯一事实源；
- 仅当 provider 为空/mock 时走 mock；真实供应商失败返回 502 + 真实错误。
"""
import asyncio
import json
import time
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from loguru import logger

from src.video_agent.web.actions import StudioActionExecutor
from src.video_agent.web.agent_loop import run_agent_loop
from src.video_agent.web.generation import (
    GenerationError,
    call_chat_completion,
    call_chat_completion_stream,
)
from src.video_agent.web.provider_config import is_mock_provider
from src.video_agent.web.state_service import StudioStateService

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
UPLOAD_ASSETS_DIR = PROJECT_ROOT / "workspace" / "assets"

# 文本类素材直接把正文注入给 LLM；单文档上限防止把上下文撑爆
_TEXT_DOC_EXTS = {".md", ".txt"}
_MAX_DOC_CHARS = 30000
_MAX_ATTACHMENTS = 5

# Studio Actions Protocol 系统提示词（服务端唯一权威版本）
STUDIO_ACTION_PROTOCOL_PROMPT = """
你正在驱动影视 Agent 工作台，角色是专业的编剧 + 分镜师 + 视觉总监。用户确认或修改的事项，如果会影响左侧故事板、中间预览提示词、草稿确认状态或资产绑定，必须在回复末尾追加一个 studio-actions JSON 块。给用户看的文字保持自然简短，JSON 块只给前端读取。

可用 action:
- add_group: 新建故事板分组（关键元素/分镜/音频）。字段：group_type(keyElement/shot/audio), title, desc, 可选 shotType/sceneRefs/duration/timeRange, 可选 draft(单个草稿) 或 drafts(草稿数组)。
- update_draft: 修改草稿。字段：draft_type(keyElement/shot/audio), draft_id/current, patch。
- update_group: 修改故事板分组。字段：group_type(keyElement/shot/audio), group_id/current, patch。
- add_draft: 给某个分组新增草稿。字段：group_type, group_id/current, draft。若分组不存在会自动创建。
- confirm_draft: 确认草稿。字段：draft_type, draft_id/current。
- delete_draft: 删除草稿。字段：draft_type, draft_id。
- delete_group: 删除整个分组（含其全部草稿）。字段：group_type, group_id。
- bind_asset: 绑定资产。字段：asset_id 或 name/url/type，可选 draft_type/draft_id。
- select_draft: 选中草稿。字段：draft_type, draft_id。
- request_confirmation: 暂停并请求用户确认。字段：message（向用户说明已完成什么、接下来要做什么）。用于拆解完成后请用户过目再继续的场景。不要与 continue 同时使用。
- continue: 请求系统再调用你一轮（分阶段完成复杂任务，最多 3 轮）。放在 actions 数组末尾，字段：reason。系统执行完本轮操作后会带着刷新后的最新状态再次调用你。

patch/draft 可包含：title, desc, roughDesc, timeRange, duration, label, tag, prompt, imgUrl, videoUrl, mode, model, resolution, aspectRatio, size, timbre, refAssets。
分组（group）级还可包含：shotType（镜头语言，如"长镜头/特写/缓推全景横移/含内部剪辑"）, sceneRefs（本分镜引用的关键元素 title 数组）。

== 拆解质量规范（必须遵守） ==
1. 命名规范：关键元素 title 用 "Element_中文短名"（如 Element_二维空间平面），分镜 title 用 "Shot_中文短名"（如 Shot_太空艇与宇航员坍缩）。
2. 关键元素：每个元素 desc 写清视觉本质（材质/形态/物理特性），3-6 个为宜，覆盖主角/载具/场景/核心特效。
3. 分镜必须包含：
   - shotType：镜头语言标签（长镜头/特写/中景/远景/全景横移/缓推/含内部剪辑…）
   - sceneRefs：引用的关键元素 title 数组（如 ["Element_监视太空艇","Element_二维空间平面"]），分镜画面里出现哪个元素就引用哪个
   - roughDesc：按时间轴分段描述，格式如 "起初(0-4s)：中景，太空艇底部接触二维平面，瞬间失去厚度…然后切至(4-7s)：特写，宇航员双脚触碰平面…最后切至(7-10s)：远景，只剩失谐的太空艇与人体平面图案。"
   - duration：总时长（如 "10s"）
4. 提示词（prompt）电影级质量规范：
   - 结构：先用中文分层描述画面空间与叙事（构图/主体/光源/动态），再以英文风格标签收尾
   - 英文标签示例：Hard sci-fi realism, inspired by Interstellar and 2001: A Space Odyssey visual language, ultra-precise technical illustration quality, strong chiaroscuro contrast, fine rendering with rich intricate detail, awe-inspiring cosmic scale, no text, no labels, no watermarks
   - 禁止一句话糊弄；关键元素概念图 prompt 不少于 100 字
5. 推荐工作流（大任务分轮执行）：
   - 第 1 轮：拆解关键元素（add_group × N，每个带概念图 draft），末尾 continue
   - 第 2 轮：拆解分镜（add_group × N，带 shotType/sceneRefs/时间轴 roughDesc 与 draft），末尾 continue
   - 第 3 轮：审美自检——复读全部 prompt，用 update_draft 优化不合规范的弱提示词，然后 request_confirmation 请用户确认后再生成图片

== 重要规则 ==
- 用户上传的 .md/.txt 素材正文会由系统直接附在用户消息里（"=== 用户上传的素材文档 === ... === 文档结束 ==="段落）。看到该段落就说明你已经拿到了全文，直接依据它拆解，不要说"我无法读取文件"或要求用户粘贴内容。
- draft_id/group_id 写 "current" 时，系统会解析为用户当前选中的草稿/分组，所以「确认这个」「修改当前提示词」直接用 current 即可。
- 当用户要求从文档/素材中拆解关键元素或分镜时，必须使用 add_group 创建新分组，并在其中携带 draft。
- 不要只说"已创建"而不输出 studio-actions 块，否则前端不会有任何变化。

格式示例：
```studio-actions
[
  {"action":"add_group","group_type":"keyElement","title":"Element_二维空间平面","desc":"绝对无厚度、极其锋利的无形平面，任何三维物质与之接触均瞬间被平摊展开","draft":{"label":"概念图","tag":"Agent","mediaType":"image","prompt":"深空黑背景中，一条绝对水平的冷蓝白色荧光细线横贯画面中央……（分层描述画面空间与叙事）Hard sci-fi realism, ultra-precise technical illustration, strong chiaroscuro contrast, no text, no labels, no watermarks"}},
  {"action":"add_group","group_type":"shot","title":"Shot_太空艇与宇航员坍缩","shotType":"长镜头","sceneRefs":["Element_监视太空艇","Element_二维空间平面"],"duration":"10s","desc":"太空艇触碰二维平面后逐层坍缩","roughDesc":"起初(0-4s)：中景，太空艇底部接触二维平面，瞬间失去厚度…然后切至(4-7s)：特写，宇航员双脚触碰平面…最后切至(7-10s)：远景，只剩太空艇与人体的平面图案。","draft":{"label":"分镜卡片","tag":"Agent","mediaType":"image","prompt":"……"}},
  {"action":"continue","reason":"下一轮进行审美自检并优化弱提示词"}
]
```
"""


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
    confirmation: str = ""    # 非空 = agent 暂停等待用户确认
    state: Optional[Dict[str, Any]] = None


def _bind_attachments(svc: StudioStateService, attachments: List[Dict[str, str]]) -> None:
    """把本次消息携带的上传素材登记进服务端资产列表（isBound=True）并持久化"""
    if not attachments:
        return
    assets = svc.state.setdefault("assets", [])
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
    其他类型给出明确的能力说明，避免 LLM 瞎猜「我看不到素材」或假装看过。
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


@router.post("/agent/chat")
@router.post("/canvas-llm")
async def agent_chat(body: ChatRequest):
    svc = StudioStateService.get_instance()
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

    # ---------- 真实供应商：多步循环 ----------
    def build_system_prompt() -> str:
        parts = [body.system_prompt.strip()] if body.system_prompt.strip() else []
        if use_studio_context:
            parts.append(STUDIO_ACTION_PROTOCOL_PROMPT.strip())
            selected_note = ""
            if body.selected_draft_id:
                selected_note = (
                    f"\n用户当前选中的草稿：draft_id={body.selected_draft_id}"
                    f"（类型 {body.selected_type or '未知'}）。studio-actions 里的 \"current\" 指向它。"
                )
            parts.append(
                "当前工作台状态 JSON 如下（每轮自动刷新）：" + selected_note + "\n\n"
                + svc.build_agent_context(body.asset_mode)
            )
        return "\n\n".join(parts)

    async def llm_call(system_prompt: str, messages: List[Dict[str, Any]]):
        full = [{"role": "system", "content": system_prompt}] + messages
        return await call_chat_completion(
            body.provider, body.model, full, max_tokens=8192, timeout=120,
        )

    history = [
        {"role": m.get("role", "user"), "content": m.get("content", "")}
        for m in body.messages[-10:]
    ]

    # 整个多步回合持锁：并发请求会排队而不是交叉改写共享状态（本地单用户场景可接受）
    async with svc.lock:
        if use_studio_context:
            _bind_attachments(svc, body.attachments)
            svc.add_chat_message("user", user_text)
        try:
            result = await run_agent_loop(
                llm_user_text,
                llm_call=llm_call,
                context_builder=build_system_prompt,
                executor=executor,
                history=history,
            )
        except GenerationError as e:
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
        state=svc.get_full_snapshot() if use_studio_context else None,
    )


class _DeltaGate:
    """
    流式增量过滤器：可见文本实时转发给前端；
    一旦出现代码围栏（studio-actions JSON 块开头），停止转发并切换状态提示，
    避免把大段 JSON 流式喷到聊天气泡里。
    尾部保留 HOLD 个字符缓冲，防止围栏标记被切在两个 chunk 之间漏出去。
    """
    HOLD = 20

    def __init__(self, emit):
        self._emit = emit
        self._buf = ""
        self._stopped = False

    async def feed(self, piece: str) -> None:
        if self._stopped:
            return
        self._buf += piece
        fence = self._buf.find("```")
        if fence != -1:
            visible = self._buf[:fence].rstrip()
            if visible:
                await self._emit({"type": "delta", "text": visible})
            self._stopped = True
            self._buf = ""
            await self._emit({"type": "status", "text": "正在生成操作指令…"})
            return
        if len(self._buf) > self.HOLD:
            out, self._buf = self._buf[:-self.HOLD], self._buf[-self.HOLD:]
            await self._emit({"type": "delta", "text": out})

    async def flush(self) -> None:
        if not self._stopped and self._buf:
            await self._emit({"type": "delta", "text": self._buf})
            self._buf = ""


@router.post("/agent/chat/stream")
@router.post("/canvas-llm/stream")
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
            svc = StudioStateService.get_instance()
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
                    "state": svc.get_full_snapshot(),
                    "elapsed_ms": int((time.monotonic() - t0) * 1000),
                }})
                return

            # ---------- 真实供应商：流式多步循环 ----------
            def build_system_prompt() -> str:
                parts = [body.system_prompt.strip()] if body.system_prompt.strip() else []
                if use_studio_context:
                    parts.append(STUDIO_ACTION_PROTOCOL_PROMPT.strip())
                    selected_note = ""
                    if body.selected_draft_id:
                        selected_note = (
                            f"\n用户当前选中的草稿：draft_id={body.selected_draft_id}"
                            f"（类型 {body.selected_type or '未知'}）。studio-actions 里的 \"current\" 指向它。"
                        )
                    parts.append(
                        "当前工作台状态 JSON 如下（每轮自动刷新）：" + selected_note + "\n\n"
                        + svc.build_agent_context(body.asset_mode)
                    )
                return "\n\n".join(parts)

            async def llm_call(system_prompt: str, messages: List[Dict[str, Any]]):
                gate = _DeltaGate(emit)
                full = [{"role": "system", "content": system_prompt}] + messages
                try:
                    content, finish = await call_chat_completion_stream(
                        body.provider, body.model, full,
                        max_tokens=8192, timeout=180, on_delta=gate.feed,
                    )
                    await gate.flush()
                    return content, finish
                except GenerationError as e:
                    # 个别供应商不支持流式：回退普通调用（真实错误会在这里再次抛出）
                    logger.warning(f"[Agent] 流式调用失败({e})，回退非流式")
                    await emit({"type": "status", "text": "流式不可用，改用普通模式…"})
                    return await call_chat_completion(
                        body.provider, body.model, full, max_tokens=8192, timeout=120,
                    )

            async def on_loop_event(event: Dict[str, Any]) -> None:
                if event["type"] == "step_started":
                    label = "正在推理…" if event["step"] == 1 else f"第 {event['step']} 轮推理中…"
                    await emit({"type": "status", "text": label, "step": event["step"]})
                elif event["type"] == "executing_actions":
                    await emit({"type": "status", "text": f"正在执行 {event['count']} 个操作…"})
                elif event["type"] == "actions_applied":
                    await emit({"type": "status", "text": f"已应用 {event['count']} 个操作"})

            history = [
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in body.messages[-10:]
            ]

            async with svc.lock:
                if use_studio_context:
                    _bind_attachments(svc, body.attachments)
                    svc.add_chat_message("user", user_text)
                try:
                    result = await run_agent_loop(
                        llm_user_text,
                        llm_call=llm_call,
                        context_builder=build_system_prompt,
                        executor=executor,
                        history=history,
                        on_event=on_loop_event,
                    )
                except GenerationError as e:
                    logger.warning(f"[Agent] LLM 调用失败: {e}")
                    if use_studio_context:
                        svc.add_chat_message("agent", f"[错误] {e}")
                    await emit({"type": "error", "detail": str(e)})
                    return
                if use_studio_context:
                    svc.add_chat_message("agent", result.text)

            await emit({"type": "done", "payload": {
                "text": result.text,
                "applied_actions": result.applied_actions,
                "steps": result.steps,
                "warnings": result.warnings,
                "confirmation": result.confirmation,
                "state": svc.get_full_snapshot() if use_studio_context else None,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            }})
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
