"""
集中配置 — 消除散落在各模块中的魔法数字。

所有可调参数统一从此处读取：
    from src.video_agent.config import settings
    timeout = settings.llm_timeout

环境变量覆盖：设置对应的大写环境变量即可（如 PORT=9000）。
"""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

from src.video_agent.utils.paths import PROJECT_ROOT

# .env 必须在 Settings 实例化之前加载（frozen dataclass 导入即定型，
# 否则 .env 中的 PORT/API_KEY/AGENT_MAX_STEPS 等对 settings 不生效）
load_dotenv(PROJECT_ROOT / ".env")


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

    # 安全
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", ""))
    # 日志文件落盘开关：服务进程默认开；测试/验收子进程经
    # conftest / scripts/acceptance.py 置 false，避免多进程争用同一日志文件
    # 触发 loguru rotation rename 失败（WinError 32）
    log_file_enabled: bool = field(default_factory=lambda: _env_bool("LOG_FILE_ENABLED", True))

    # Agent 多步循环
    max_steps: int = field(default_factory=lambda: _env_int("AGENT_MAX_STEPS", 6))

    # LLM 超时（秒）
    llm_timeout: int = field(default_factory=lambda: _env_int("LLM_TIMEOUT", 120))
    llm_stream_timeout: int = field(default_factory=lambda: _env_int("LLM_STREAM_TIMEOUT", 180))
    # LLM 生成参数（adapter 未显式传参时的回落值）
    llm_max_tokens: int = field(default_factory=lambda: _env_int("LLM_MAX_TOKENS", 8192))
    llm_temperature: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.7")))
    # 单次输出 token 上限（执行器/工具 LLM 调用查表回落值）
    llm_output_limit: int = field(default_factory=lambda: _env_int("LLM_OUTPUT_LIMIT", 8192))
    # 执行器 LLM JSON 调用超时（秒）
    llm_json_timeout: float = field(default_factory=lambda: float(os.getenv("LLM_JSON_TIMEOUT", "120")))
    # LLM 思考（thinking/reasoning）档位：low/medium/high = 按 OpenAI 兼容
    # reasoning_effort 透传；空 = 不下发该字段（模型原生能力，默认）。
    # 主模型档位改由对话栏「推理等级」选择器按会话下发（默认=原生），
    # 本全局值仅作未携带会话档位时的回落（env 可覆写）。
    # 注意：对字段严格的端点会自动去掉该字段重试一次（400 优雅降级）。
    llm_thinking_level: str = field(default_factory=lambda: os.getenv("LLM_THINKING_LEVEL", ""))
    # 辅助摘要调用档位（记忆摘要/会话压缩； 全局设置页可调，默认=原生）
    aux_thinking_level: str = field(default_factory=lambda: os.getenv("AUX_THINKING_LEVEL", ""))
    # trace 持久化的 reasoning 尾部保留字符数（·：头部截断，仅展示用）
    trace_reasoning_max_chars: int = field(default_factory=lambda: _env_int("TRACE_REASONING_MAX_CHARS", 2000))
    # CLI 协议（如 gemini-cli/Antigravity CLI）路由到 custom-api 反代时 auto 的回退模型：
    # 聊天已对齐画布行为改走本机 agy CLI，此值仅影响带参考图的生图编辑等
    # 必须走反代的残留路径；反代报 model not register 时用 CLI_AUTO_CHAT_MODEL 覆盖
    cli_auto_chat_model: str = field(default_factory=lambda: os.getenv("CLI_AUTO_CHAT_MODEL", "gemini-3.1-flash-image"))

    # Token 预算管理
    context_window_size: int = field(default_factory=lambda: _env_int("CONTEXT_WINDOW_SIZE", 128000))
    token_budget_ratio: float = field(default_factory=lambda: float(os.getenv("TOKEN_BUDGET_RATIO", "0.8")))
    # 单张图片的 vision token 固定估算（此前多模态消息的 image_url
    # 部分不计入预算，截断决策对带图历史失真）；取常见高分辨率档保守值
    image_token_estimate: int = field(default_factory=lambda: _env_int("IMAGE_TOKEN_ESTIMATE", 1200))
    # 旧轮 read_* 回喂全文的惰性压缩阈值：消息总量达到预算的该比例才压缩，
    # 短对话保留全文保质量，长对话才省 token（0 = 始终压缩，1 = 永不压缩）；
    # 收紧 0.5→0.35（历史是上下文膨胀大头，提早压缩）
    feedback_compress_ratio: float = field(default_factory=lambda: float(os.getenv("FEEDBACK_COMPRESS_RATIO", "0.35")))
    # 会话级 compaction（恢复、 默认开）：history 条数达该阈值时用
    # 便宜模型把较早对话压成摘要+最近几条（0 = 关闭，仅靠 truncate_history 头尾截断）
    history_compact_threshold: int = field(default_factory=lambda: _env_int("HISTORY_COMPACT_THRESHOLD", 12))
    # 工作台状态 JSON 紧凑序列化（模型读紧凑 JSON 无损，约省 20-30% token）；
    # 置 false 回退 indent=2 便于人工排查日志
    context_json_compact: bool = field(default_factory=lambda: _env_bool("CONTEXT_JSON_COMPACT", True))
    # 提示词结构闸机（Skill 流程激活时生效）：
    # strict = 不合格直接拒绝写入，模型自行补齐重写（默认）；
    # warn = 照存但把警告带回给模型；off = 关闭
    prompt_gate_mode: str = field(default_factory=lambda: os.getenv("PROMPT_GATE_MODE", "strict"))
    # 注入 LLM 的图片长边上限（px）：vision 模型内部会重采样，原图内联纯浪费 token；
    # 注入前用 Pillow 缩放到此长边（0 = 不缩放）
    llm_image_max_edge: int = field(default_factory=lambda: _env_int("LLM_IMAGE_MAX_EDGE", 1024))
    # 记忆摘要专用模型（格式 "provider:model"，仅 provider 则用其默认模型）：
    # 摘要无需主模型能力，固定走便宜模型省 token；空 = 走 fallback 链末位（无链则主模型）
    memory_summary_model: str = field(default_factory=lambda: os.getenv("MEMORY_SUMMARY_MODEL", ""))

    # 图片生成超时（秒）
    image_gen_timeout: int = field(default_factory=lambda: _env_int("IMAGE_GEN_TIMEOUT", 180))

    # 附件限制
    max_doc_chars: int = field(default_factory=lambda: _env_int("MAX_DOC_CHARS", 30000))
    max_attachments: int = field(default_factory=lambda: _env_int("MAX_ATTACHMENTS", 5))

    # 多模态模型单次请求可注入的图片上限（多数 vision 模型限制 4~10 张，
    # 超限会直接报错；超出部分降级为文本清单，LLM 仍可知晓其存在）
    max_llm_images: int = field(default_factory=lambda: _env_int("MAX_LLM_IMAGES", 9))
    # 生成参考素材数量上限（图片/视频/音频参考注入）：
    # 并发过高会撞供应商 429（现场），参考过多会撑爆请求体
    image_ref_limit: int = field(default_factory=lambda: _env_int("IMAGE_REF_LIMIT", 10))
    image_gen_concurrency: int = field(default_factory=lambda: _env_int("IMAGE_GEN_CONCURRENCY", 4))
    # 媒体生成族有界并发（P3-13）：生视频单发成本高、供应商并发配额小，保守起步 2；
    # 音频当前版本无真实文件生成调用，通道预留同口径配置
    video_gen_concurrency: int = field(default_factory=lambda: _env_int("VIDEO_GEN_CONCURRENCY", 2))
    audio_gen_concurrency: int = field(default_factory=lambda: _env_int("AUDIO_GEN_CONCURRENCY", 2))
    video_ref_limit_image: int = field(default_factory=lambda: _env_int("VIDEO_REF_LIMIT_IMAGE", 30))
    video_ref_limit_video: int = field(default_factory=lambda: _env_int("VIDEO_REF_LIMIT_VIDEO", 10))
    video_ref_limit_audio: int = field(default_factory=lambda: _env_int("VIDEO_REF_LIMIT_AUDIO", 10))
    video_ref_limit_total: int = field(default_factory=lambda: _env_int("VIDEO_REF_LIMIT_TOTAL", 50))
    # Agent 单次回复可插入对话输入框的故事板媒体数量上限（防止一次灌满输入框）
    max_chat_inserts: int = field(default_factory=lambda: _env_int("MAX_CHAT_INSERTS", 8))
    # 模型 fallback 链：主模型遇 5xx/超时等瞬时故障且尚未执行任何操作时，
    # 自动切换备用 chat 模型重试（同供应商其他模型 → 其他启用供应商）
    model_fallback_enabled: bool = field(default_factory=lambda: _env_bool("MODEL_FALLBACK_ENABLED", True))
    # fallback 候选链总长度（含主模型）
    model_fallback_max_candidates: int = field(default_factory=lambda: _env_int("MODEL_FALLBACK_MAX_CANDIDATES", 3))

    # 全局生成默认（前端「全局设置」页经 /api/settings/runtime 热更新并持久化）：
    # 出图/出视频渠道与分辨率默认值，新建草稿与 Agent 生成回退链共用
    default_image_provider_id: str = ""
    default_image_model: str = ""
    default_video_provider_id: str = ""
    default_video_model: str = ""
    # 聊天框出图开关：关 = Agent 在对话中不主动触发生图
    chat_image_enabled: bool = True
    default_image_resolution: str = "1K"
    default_video_resolution: str = "1080p"
    # 分镜最大时长（秒）：Agent 自拆分镜单镜时长上限与新建分镜默认时长
    max_shot_duration: int = 5

    # Skill 执行器运行时模式：auto = 按 Skill 能否解析出执行器章节自动选择；
    # executors = 全部走执行器；legacy = 全部走全文+阶段聚焦
    skill_runtime: str = field(default_factory=lambda: os.getenv("SKILL_RUNTIME", "auto"))
    # 模型分层策略表（编排/生成/摘要/执行器四角色，热更新于 runtime_settings.json；
    # 字段语义见 core/model_policy.py；空 = 跟随主模型/既有回落链）
    model_policy: dict = field(default_factory=dict)
    # 执行器誊写批的快模型（"provider" 或 "provider:model"）；空 = 回落主模型
    executor_fast_model: str = field(default_factory=lambda: os.getenv("EXECUTOR_FAST_MODEL", ""))
    # 执行器机械调用的思考档位（low/medium/high）；空 = 沿用全局 llm_thinking_level
    # （用户裁决）：默认空（不硬编码降档）；要降档由全局设置配置
    # 全局设置「推理档位」卡退役，UI 语义归模型分层策略
    # executor/summary 行（通用搭配默认 low）；本字段仅保留作 env 覆写回落。
    executor_thinking_level: str = field(default_factory=lambda: os.getenv("EXECUTOR_THINKING_LEVEL", ""))
    # 剧本正文注入上限（合一，原 10000/12000 分阶段硬编码废除）；
    # 仅超模型上下文硬窗时才截断，截断附可见警告
    script_inject_limit: int = field(default_factory=lambda: _env_int("SCRIPT_INJECT_LIMIT", 20000))
    # 状态驱动管线开关（阶段表/闸预检/账本同步总闸；默认开）
    pipeline_orchestrator_enabled: bool = field(
        default_factory=lambda: _env_bool("PIPELINE_ORCHESTRATOR_ENABLED", True))
    # node_attempts 消费阈值（P3-16）：同一节点执行器失败累计达该次数时，
    # gate_precheck 派生「重试/换渠道」引导卡数据交回模型决策
    # （ADR-0004：runtime 只产出引导数据，不发起行动）
    node_retry_guidance_threshold: int = field(
        default_factory=lambda: _env_int("NODE_RETRY_GUIDANCE_THRESHOLD", 2))
    # （Workflow Runtime 驱动器开关已随 ADR-0004 主体回归退役：runtime 不再有
    # 驱动/直跑能力，账本与闸预检由 pipeline_orchestrator_enabled 统一管辖）

    # 任务管理
    task_ttl_seconds: int = field(default_factory=lambda: _env_int("TASK_TTL_SECONDS", 86400))
    task_max: int = field(default_factory=lambda: _env_int("TASK_MAX", 500))
    # Agent trace JSONL 体积轮转（.1）
    trace_file_max_bytes: int = field(default_factory=lambda: _env_int("TRACE_FILE_MAX_BYTES", 2_000_000))
    trace_rotation_keep: int = field(default_factory=lambda: _env_int("TRACE_ROTATION_KEEP", 3))
    # （审核）：trace 总容量上限（主文件+.N 合计，超则从最旧丢弃）
    trace_total_max_bytes: int = field(default_factory=lambda: _env_int("TRACE_TOTAL_MAX_BYTES", 20_000_000))

    # 上传限制
    max_upload_size_mb: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_SIZE_MB", 50))

    # 请求限流（每分钟每 IP 最大请求数，0 = 不限流）
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 10))
    # 生成类端点（/api/generate*）单独配额：批量生图/生视频会连续提交多个任务，
    # 与聊天共用低配额会误伤正常批量操作（-3）
    rate_limit_generate_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_GENERATE_PER_MINUTE", 60))
    # 是否信任 X-Forwarded-For 头提取客户端 IP（仅在可信反向代理后置 true；
    # 本机直连部署下该头可被伪造，用于绕过 IP 级限流）
    trust_proxy: bool = field(default_factory=lambda: _env_bool("TRUST_PROXY", False))

    # 存储后端（"local" | "s3"）
    storage_backend: str = field(default_factory=lambda: os.getenv("STORAGE_BACKEND", "local"))

    # 项目状态持久化后端（"json" | "sqlite"）： 起默认 sqlite（事务原子性
    # 与并发安全，多用户基础）；首次启用自动从 JSON 迁移，STATE_BACKEND=json 可随时回退
    state_backend: str = field(default_factory=lambda: os.getenv("STATE_BACKEND", "sqlite"))

    # 画布画布集成
    canvas_base_url: str = field(default_factory=lambda: os.getenv("CANVAS_BASE_URL", "http://127.0.0.1:3000"))
    canvas_timeout: int = field(default_factory=lambda: _env_int("CANVAS_TIMEOUT", 30))
    canvas_enabled: bool = field(default_factory=lambda: _env_bool("CANVAS_ENABLED", True))

    # Agent 混合记忆系统
    memory_enabled: bool = field(default_factory=lambda: _env_bool("MEMORY_ENABLED", True))
    memory_vector_backend: str = field(default_factory=lambda: os.getenv("MEMORY_VECTOR_BACKEND", "chromadb"))
    memory_max_results: int = field(default_factory=lambda: _env_int("MEMORY_MAX_RESULTS", 5))
    memory_summary_interval: int = field(default_factory=lambda: _env_int("MEMORY_SUMMARY_INTERVAL", 10))
    memory_time_decay_days: int = field(default_factory=lambda: _env_int("MEMORY_TIME_DECAY_DAYS", 30))

    # 画布 Provider 配置共享（HTTP 优先，文件兜底）
    # 注意：canvas_providers_file / canvas_env_file 默认为空，需通过环境变量配置；
    # 为空时画布配置共享功能自动降级（仅通过 HTTP 接口获取）。
    canvas_providers_url: str = field(default_factory=lambda: os.getenv(
        "CANVAS_PROVIDERS_URL", "http://127.0.0.1:3000/api/providers"))
    canvas_providers_file: str = field(default_factory=lambda: os.getenv(
        "CANVAS_PROVIDERS_FILE", ""))
    canvas_env_file: str = field(default_factory=lambda: os.getenv(
        "CANVAS_ENV_FILE", ""))
    canvas_health_cache_seconds: int = field(default_factory=lambda: _env_int(
        "CANVAS_HEALTH_CACHE_SECONDS", 30))
    # 画布外壳 UI 在画布 iframe 内的偏移估计（侧栏宽 + stage 边距），用于拖放落点换算；
    # 画布独立迭代若改了外壳布局，可通过环境变量调整，不影响功能（结果会被夹取到可视区内）
    canvas_shell_offset_x: int = field(default_factory=lambda: _env_int("CANVAS_SHELL_OFFSET_X", 96))
    canvas_shell_offset_y: int = field(default_factory=lambda: _env_int("CANVAS_SHELL_OFFSET_Y", 16))


# 全局单例（启动时加载一次）
settings = Settings()
