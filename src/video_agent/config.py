"""
集中配置 — 消除散落在各模块中的魔法数字。

所有可调参数统一从此处读取：
    from src.video_agent.config import settings
    timeout = settings.llm_timeout

环境变量覆盖：设置对应的大写环境变量即可（如 PORT=9000）。
"""
import os
from dataclasses import dataclass, field


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key, "").strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


@dataclass(frozen=True)
class Settings:
    """全局可调参数（只读，启动时从环境变量加载）"""

    # 服务
    port: int = field(default_factory=lambda: _env_int("PORT", 8080))
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))

    # Agent 多步循环
    max_steps: int = field(default_factory=lambda: _env_int("AGENT_MAX_STEPS", 6))

    # LLM 超时（秒）
    llm_timeout: int = field(default_factory=lambda: _env_int("LLM_TIMEOUT", 120))
    llm_stream_timeout: int = field(default_factory=lambda: _env_int("LLM_STREAM_TIMEOUT", 180))

    # 图片生成超时（秒）
    image_gen_timeout: int = field(default_factory=lambda: _env_int("IMAGE_GEN_TIMEOUT", 180))

    # 附件限制
    max_doc_chars: int = field(default_factory=lambda: _env_int("MAX_DOC_CHARS", 30000))
    max_attachments: int = field(default_factory=lambda: _env_int("MAX_ATTACHMENTS", 5))

    # 任务管理
    task_ttl_seconds: int = field(default_factory=lambda: _env_int("TASK_TTL_SECONDS", 86400))
    task_max: int = field(default_factory=lambda: _env_int("TASK_MAX", 500))

    # 上传限制
    max_upload_size_mb: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_SIZE_MB", 50))

    # 熊布画布集成
    canvas_base_url: str = field(default_factory=lambda: os.getenv("CANVAS_BASE_URL", "http://127.0.0.1:3000"))
    canvas_timeout: int = field(default_factory=lambda: _env_int("CANVAS_TIMEOUT", 30))
    canvas_enabled: bool = field(default_factory=lambda: _env_bool("CANVAS_ENABLED", True))

    # 熊布 Provider 配置共享（HTTP 优先，文件兜底）
    canvas_providers_url: str = field(default_factory=lambda: os.getenv(
        "CANVAS_PROVIDERS_URL", "http://127.0.0.1:3000/api/providers"))
    canvas_providers_file: str = field(default_factory=lambda: os.getenv(
        "CANVAS_PROVIDERS_FILE", r"E:\07 天问\熊布\data\api_providers.json"))
    canvas_env_file: str = field(default_factory=lambda: os.getenv(
        "CANVAS_ENV_FILE", r"E:\07 天问\熊布\API\.env"))
    canvas_health_cache_seconds: int = field(default_factory=lambda: _env_int(
        "CANVAS_HEALTH_CACHE_SECONDS", 30))


# 全局单例（启动时加载一次）
settings = Settings()
