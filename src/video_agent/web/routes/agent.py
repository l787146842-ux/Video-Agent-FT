"""
/api/agent — Agent 聊天端点

流程：服务端构建上下文 → 多步 LLM 循环（≤3 轮）→ 解析并执行 studio-actions → 持久化 → 返回。

- 上下文注入在服务端完成（前端只发消息本体 + 选中态），服务端是唯一事实源；
- 仅当 provider 为空/mock 时走 mock；真实供应商失败返回 502 + 真实错误。
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from loguru import logger

from src.video_agent.web.actions import StudioActionExecutor
from src.video_agent.web.agent_loop import run_agent_loop
from src.video_agent.web.generation import GenerationError, call_chat_completion
from src.video_agent.web.provider_config import is_mock_provider
from src.video_agent.web.state_service import StudioStateService

router = APIRouter()

# Studio Actions Protocol 系统提示词（服务端唯一权威版本）
STUDIO_ACTION_PROTOCOL_PROMPT = """
你正在驱动影视 Agent 工作台。用户在右侧 Agent 对话框里确认或修改的事项，如果会影响左侧故事板、中间预览提示词、草稿确认状态或资产绑定，必须在回复末尾追加一个 studio-actions JSON 块。给用户看的文字保持自然简短，JSON 块只给前端读取。

可用 action:
- add_group: 新建故事板分组（关键元素/分镜/音频）。字段：group_type(keyElement/shot/audio), title, desc, 可选 draft(单个草稿) 或 drafts(草稿数组)。
- update_draft: 修改草稿。字段：draft_type(keyElement/shot/audio), draft_id/current, patch。
- update_group: 修改故事板分组。字段：group_type(keyElement/shot/audio), group_id/current, patch。
- add_draft: 给某个分组新增草稿。字段：group_type, group_id/current, draft。若分组不存在会自动创建。
- confirm_draft: 确认草稿。字段：draft_type, draft_id/current。
- bind_asset: 绑定资产。字段：asset_id 或 name/url/type，可选 draft_type/draft_id。
- select_draft: 选中草稿。字段：draft_type, draft_id。
- continue: 请求系统再调用你一轮（用于分多步完成的复杂任务，最多 3 轮）。放在 actions 数组末尾，字段：reason（说明下一轮要做什么）。系统执行完本轮操作后，会带着刷新后的最新状态再次调用你。

patch/draft 可包含：title, desc, roughDesc, timeRange, duration, label, tag, prompt, imgUrl, videoUrl, mode, model, resolution, aspectRatio, size, timbre, refAssets。

重要规则：
- draft_id/group_id 写 "current" 时，系统会解析为用户当前选中的草稿/分组，所以「确认这个」「修改当前提示词」直接用 current 即可。
- 当用户要求从文档/素材中拆解关键元素或分镜时，必须使用 add_group 创建新分组，并在其中携带 draft。
- 不要只说"已创建"而不输出 studio-actions 块，否则前端不会有任何变化。
- 每个关键元素/分镜都应该有具体的 prompt（可执行的图片/视频生成提示词）。
- 任务量大时（例如拆解整个剧本），先创建分组骨架，再用 continue 分轮补全每个分组的提示词。

格式示例：
```studio-actions
[
  {"action":"add_group","group_type":"keyElement","title":"特效设定：太阳系二维化","desc":"太阳系逐渐被二维化的视觉特效设定","draft":{"label":"概念图","tag":"Agent","mediaType":"image","prompt":"太阳系行星逐渐被压平为二维平面，宇宙背景，科幻特效，8K"}},
  {"action":"continue","reason":"下一轮为每个分镜补充详细提示词"}
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
    state: Optional[Dict[str, Any]] = None


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
    if not user_text:
        raise HTTPException(status_code=400, detail="消息不能为空")

    use_studio_context = body.context_mode != "none"

    # ---------- mock 路径（仅显式选择 mock / 未配置供应商） ----------
    if is_mock_provider(body.provider, body.model):
        async with svc.lock:
            if use_studio_context:
                svc.add_chat_message("user", user_text)
            raw_reply = _mock_llm_reply(user_text, svc.build_agent_context(body.asset_mode))
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
            svc.add_chat_message("user", user_text)
        try:
            result = await run_agent_loop(
                user_text,
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
        state=svc.get_full_snapshot() if use_studio_context else None,
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
