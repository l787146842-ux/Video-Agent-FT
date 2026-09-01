"""
/api/config — 全局配置端点
返回可用的模型列表（chat / image / video）及画布 URL，供前端渲染。
运行时开关（如模型降级）也在此读写，界面修改持久化到 data/runtime_settings.json。
"""
import json

from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel

from src.video_agent.adapters.infinite_canvas_backend import resolve_canvas_agent_token
from src.video_agent.config import settings
from src.video_agent.exceptions import VideoAgentError
from src.video_agent.utils.fileio import atomic_write_text
from src.video_agent.utils.paths import DATA_DIR

router = APIRouter()

# 默认模型列表（后续可从 AdapterFactory / .env 动态读取）
DEFAULT_CHAT_MODELS = ["gpt-5.5", "gpt-4o-mini", "gemini-3.1-flash-image-preview-2k"]
DEFAULT_IMAGE_MODELS = ["nano-banana-pro", "gpt-image-2"]
DEFAULT_VIDEO_MODELS = ["veo3-fast", "sora-2", "seedance2.0_vip"]

# ---------- 运行时开关（界面可改，持久化覆盖 env 默认值） ----------
_RUNTIME_SETTINGS_FILE = DATA_DIR / "runtime_settings.json"


def _load_runtime_overrides() -> dict:
    try:
        data = json.loads(_RUNTIME_SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_runtime_overrides(overrides: dict) -> None:
    """合并写入运行时覆盖（读-改-写，避免覆盖其他运行时设置字段）。"""
    merged = _load_runtime_overrides()
    merged.update(overrides)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        _RUNTIME_SETTINGS_FILE,
        json.dumps(merged, ensure_ascii=False, indent=2),
    )


def _apply_runtime_overrides() -> None:
    """启动/保存后把持久化覆盖值应用到 settings（目前仅模型降级开关）。"""
    ov = _load_runtime_overrides()
    if isinstance(ov.get("model_fallback_enabled"), bool):
        object.__setattr__(settings, "model_fallback_enabled", ov["model_fallback_enabled"])


_apply_runtime_overrides()


def _bound_to_loopback() -> bool:
    """服务是否仅回环绑定（决定 agent_token 可否下发前端）；
    0.0.0.0/其他地址绑定局域网可达，下发真实 token 会泄漏画布写入口"""
    return (settings.host or "").strip().lower() in ("127.0.0.1", "localhost", "::1")


@router.get("/config")
async def get_config():
    """前端 loadCanvasApiConfig() 调用"""
    resp = {
        "chat_models": DEFAULT_CHAT_MODELS,
        "image_models": DEFAULT_IMAGE_MODELS,
        "video_models": DEFAULT_VIDEO_MODELS,
        "canvas_url": settings.infinite_canvas_url,
        "model_fallback_enabled": bool(settings.model_fallback_enabled),
        # 附件数量上限（二期子对话批 3：浮窗上传入口提示用，唯一事实源 config）
        "max_attachments": int(settings.max_attachments),
    }
    # 嵌入引导参数（画布站点 / canvas-agent 地址 / token，仅本机回环使用）：
    # 前端据此拼 iframe src {站点}/#agentUrl=...&agentToken=...
    # 安全闸：非回环绑定时不下发真实 token（返回空串），回环时行为不变；
    # 下发范围说明见 docs/配置说明.md 画布集成迁移说明段。
    resp["infinite_canvas_embed"] = {
        "canvas_url": settings.infinite_canvas_url,
        "agent_url": settings.canvas_agent_url,
        "agent_token": resolve_canvas_agent_token() if _bound_to_loopback() else "",
    }
    return resp


class ModelFallbackPatch(BaseModel):
    enabled: bool


@router.post("/config/model-fallback")
async def set_model_fallback(body: ModelFallbackPatch):
    """模型降级开关：开 = 主模型打不通自动切 API 配置里的其他模型；
    关 = 不降级，打不通直接报错停止。修改持久化，重启后仍生效。"""
    object.__setattr__(settings, "model_fallback_enabled", body.enabled)
    try:
        _save_runtime_overrides({"model_fallback_enabled": body.enabled})
    except Exception as e:
        logger.warning(f"[Config] 运行时开关持久化失败（本次会话内仍生效）: {e}")
        # P9：未预期异常——友好文案进 message，技术细节进 raw
        raise VideoAgentError("开关保存失败", status_code=500, raw=str(e)) from e
    logger.info(f"[Config] 模型降级开关已{'开启' if body.enabled else '关闭'}")
    return {"ok": True, "model_fallback_enabled": body.enabled}
