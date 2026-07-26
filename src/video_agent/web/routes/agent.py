"""
/api/agent — Agent 聊天端点
完整流程：buildContext → LLM → parse studio-actions → execute → persist → 返回
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from loguru import logger

from src.video_agent.web.state_service import StudioStateService
from src.video_agent.web.actions import StudioActionExecutor

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent

# Studio Actions Protocol 系统提示词
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

patch/draft 可包含：title, desc, roughDesc, timeRange, duration, label, tag, prompt, imgUrl, videoUrl, mode, model, resolution, aspectRatio, size, timbre, refAssets。

重要规则：
- 当用户要求从文档/素材中拆解关键元素或分镜时，必须使用 add_group 创建新分组，并在其中携带 draft。
- 不要只说“已创建”而不输出 studio-actions 块，否则前端不会有任何变化。
- 每个关键元素/分镜都应该有具体的 prompt（可执行的图片/视频生成提示词）。

格式示例：
```studio-actions
[
  {"action":"add_group","group_type":"keyElement","title":"特效设定：太阳系二维化","desc":"太阳系逐渐被二维化的视觉特效设定","draft":{"label":"概念图","tag":"Agent","mediaType":"image","prompt":"太阳系行星逐渐被压平为二维平面，宇宙背景，科幻特效，8K"}},
  {"action":"add_group","group_type":"shot","title":"分镜1：全景—太阳系俯瞰","desc":"从远处俯瞰太阳系全貌","draft":{"label":"全景镜头","tag":"Agent","mediaType":"image","prompt":"宇宙深空俯瞰太阳系，行星轨道清晰可见，电影级采光"}}
]
```
"""


class ChatRequest(BaseModel):
    message: str
    system_prompt: str = ""
    provider: str = ""
    model: str = ""
    ms_model: str = ""
    messages: List[Dict[str, str]] = []
    images: List[str] = []
    videos: List[str] = []


class ChatResponse(BaseModel):
    text: str
    applied_actions: int = 0
    state: Optional[Dict[str, Any]] = None


@router.post("/agent/chat")
@router.post("/canvas-llm")
async def agent_chat(body: ChatRequest):
    """
    Agent 聊天入口 — 完整流程：
    1. 从 StudioStateService 构建上下文
    2. 调用 LLM（当前 mock，后续接 Planner / 直调）
    3. 解析回复中的 studio-actions
    4. 通过 StudioActionExecutor 执行 → 持久化
    5. 返回可见回复 + 执行数量 + 最新状态快照
    """
    svc = StudioStateService.get_instance()
    executor = StudioActionExecutor(svc)

    user_text = body.message.strip()

    # 记录用户消息
    svc.add_chat_message("user", user_text)

    # 构建 LLM 上下文（从 StateManager 读取）
    context = svc.build_agent_context(asset_mode="bound")

    # 调用 LLM（优先真实 API，回退 mock）
    raw_reply = await _call_llm(user_text, context, body)

    # 解析 studio-actions
    actions = executor.parse_actions_from_reply(raw_reply)
    visible_reply = executor.strip_action_blocks(raw_reply)
    if not visible_reply:
        visible_reply = "已更新故事板和当前预览。" if actions else raw_reply

    # 执行 actions → 持久化到 studio_state.json
    applied_count = executor.execute(actions)

    # 记录 Agent 回复
    svc.add_chat_message("agent", visible_reply)

    logger.info(f"[Agent] user='{user_text[:50]}...' actions={applied_count}")

    return ChatResponse(
        text=visible_reply,
        applied_actions=applied_count,
        state=svc.get_full_snapshot(),
    )


async def _call_llm(user_text: str, context: str, body: ChatRequest) -> str:
    """LLM 调用调度器：有可用供应商走真实 API，否则回退 mock"""
    provider_id = body.provider or ""
    model = body.model or ""

    # mock 供应商或空供应商 → 走 mock
    if not provider_id or provider_id == "mock" or not model or model.startswith("mock"):
        return await _call_llm_mock(user_text, context, body)

    try:
        return await _call_llm_real(user_text, context, body)
    except Exception as e:
        logger.warning(f"[Agent] 真实 LLM 调用失败: {e}，回退 mock")
        return await _call_llm_mock(user_text, context, body)


def _get_provider_config(provider_id: str) -> Optional[Dict[str, Any]]:
    """从 data/api_providers.json 读取供应商配置"""
    providers_file = PROJECT_ROOT / "data" / "api_providers.json"
    if not providers_file.exists():
        return None
    try:
        providers = json.loads(providers_file.read_text(encoding="utf-8"))
        for p in providers:
            if p.get("id") == provider_id:
                return p
    except Exception:
        pass
    return None


def _get_api_key(provider_id: str) -> str:
    """从 API/.env 或环境变量读取 API Key"""
    env_mapping = {
        "modelscope": "MODELSCOPE_API_KEY",
        "volcengine": "ARK_API_KEY",
        "gemini-cli": "GEMINI_API_KEY",
    }
    env_name = env_mapping.get(provider_id, f"API_PROVIDER_{provider_id.upper().replace('-', '_')}_KEY")

    # 先查环境变量
    val = os.getenv(env_name, "")
    if val:
        return val

    # 再查 API/.env 文件
    env_file = PROJECT_ROOT / "API" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{env_name}="):
                return line.split("=", 1)[1].strip()
    return ""


async def _call_llm_real(user_text: str, context: str, body: ChatRequest) -> str:
    """真实 LLM API 调用（OpenAI 兼容格式）"""
    provider_id = body.provider
    model = body.model

    # 获取供应商配置
    provider_cfg = _get_provider_config(provider_id)
    if not provider_cfg:
        raise ValueError(f"供应商 '{provider_id}' 未配置")

    base_url = provider_cfg.get("base_url", "").rstrip("/")
    if not base_url:
        raise ValueError(f"供应商 '{provider_id}' 缺少 base_url")

    api_key = _get_api_key(provider_id)

    # 构建消息列表
    system_prompt = body.system_prompt or ""
    if not system_prompt:
        system_prompt = STUDIO_ACTION_PROTOCOL_PROMPT

    messages = [{"role": "system", "content": system_prompt}]

    # 加入历史消息（最近 10 条）
    if body.messages:
        for msg in body.messages[-10:]:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    # 当前用户消息（前端已将工作台上下文拼入 message 字段）
    messages.append({"role": "user", "content": user_text})

    # 发起请求
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2000,
    }

    logger.info(f"[Agent] 调用 LLM: provider={provider_id}, model={model}, base_url={base_url}")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    # 解析响应
    choices = data.get("choices", [])
    if not choices:
        raise ValueError("LLM 返回空 choices")

    reply = choices[0].get("message", {}).get("content", "")
    if not reply:
        raise ValueError("LLM 返回空内容")

    logger.info(f"[Agent] LLM 回复: {reply[:100]}...")
    return reply


async def _call_llm_mock(user_text: str, context: str, body: ChatRequest) -> str:
    """
    Mock LLM 调用（回退用）。
    当供应商为 mock 或未配置真实 API 时使用。
    """
    if any(kw in user_text for kw in ["确认", "通过", "定稿", "锁定", "采用"]):
        reply = "好的，已将当前草稿标记为「已确认」。后续生成任务将优先使用已确认的版本。"
        actions_block = '```studio-actions\n[{"action":"confirm_draft","draft_type":"current","draft_id":"current"}]\n```'
    elif any(kw in user_text for kw in ["拆解", "解析", "拆分", "分镜", "上传", "文档", "已上传并绑定素材"]):
        reply = (
            "已根据你提供的素材拆解出关键元素和分镜，请查看左侧故事板。"
            "每个分组都带有可执行的生成提示词，你可以点击生成图片。"
        )
        actions_block = '```studio-actions\n[{"action":"add_group","group_type":"keyElement","title":"关键元素：核心视觉设定","desc":"从素材中提取的核心视觉元素","draft":{"label":"概念图","tag":"Agent","mediaType":"image","prompt":"电影级概念图，超高细节，8K 分辨率，体积光，景深虚化"}},{"action":"add_group","group_type":"shot","title":"分镜1：全景—建立镜头","desc":"开场全景建立镜头","draft":{"label":"全景镜头","tag":"Agent","mediaType":"image","prompt":"电影级全景建立镜头，宽银幕构图，自然光，8K"}}]\n```'
    elif any(kw in user_text for kw in ["修改", "调整", "优化", "改写", "提示词"]):
        reply = (
            "已根据你的意见优化了提示词，增强了画面细节和电影感。"
            "新版本强调了光影层次、材质纹理和镜头语言。"
        )
        actions_block = '```studio-actions\n[{"action":"update_draft","draft_type":"current","draft_id":"current","patch":{"tag":"已优化","prompt":"电影级光影，超高细节，8K 分辨率，赛博朋克现实主义，体积光，景深虚化"}}]\n```'
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
