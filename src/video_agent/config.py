"""
集中配置 — 消除散落在各模块中的魔法数字。

所有可调参数统一从此处读取：
    from src.video_agent.config import settings
    timeout = settings.llm_timeout

环境变量覆盖：设置对应的大写环境变量即可（如 PORT=9000）。
"""
import logging
import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

from src.video_agent.utils.paths import PROJECT_ROOT

# .env 必须在 Settings 实例化之前加载（frozen dataclass 导入即定型，
# 否则 .env 中的 PORT/API_KEY/AGENT_MAX_STEPS 等对 settings 不生效）
load_dotenv(PROJECT_ROOT / ".env")


# 执行偏好三档白名单枚举（2026-08-30 用户裁决，Skill 系统修复批 B）：
# 单一事实源——路由层清洗/下发、core 确认闸分流、sidecar 契约导出同引用。
# auto_decide = 有活跃 Skill 指导的常规生成流免逐次确认（代发同意留痕）；
# confirm_before_gen = 每次生成前确认（默认档，行为与现状一致）；
# generate_directly = 免确认直接执行（留痕）。
EXECUTION_PREFERENCE_VALUES = ("auto_decide", "confirm_before_gen", "generate_directly")
EXECUTION_PREFERENCE_DEFAULT = "confirm_before_gen"


def normalize_exec_pref(value) -> str:
    """执行偏好白名单清洗（唯一规整口）：命中枚举原样返回，
    其余（非法/空/脏值）回落默认档。"""
    v = str(value or "").strip().lower()
    return v if v in EXECUTION_PREFERENCE_VALUES else EXECUTION_PREFERENCE_DEFAULT


# Agent 多步上限钳制区间（Q3 裁决 2026-09-01：运行时可热调）：
# 单一事实源——运行时设置热更新通道与 agent_loop 实时读取同引用。
MAX_STEPS_RANGE = (1, 30)


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

    # Agent 多步循环（Q3：运行时热更新经 web/runtime_settings 通道，
    # agent_loop 每步实时读取，不再 import 期冻结）
    max_steps: int = field(default_factory=lambda: _env_int("AGENT_MAX_STEPS", 6))
    # 只读受限并行（批 7 · L3，默认开）：仅连续 risk=low 只读工具段在闸机链
    # 按序裁决全部放行后于窗口内并行执行，结果按原序回填；写类/中高危仍串行。
    # 默认开启，env 可关回串行（READONLY_PARALLEL_ENABLED=0）。
    readonly_parallel_enabled: bool = field(
        default_factory=lambda: _env_bool("READONLY_PARALLEL_ENABLED", True))

    # LLM 超时（秒）
    llm_timeout: int = field(default_factory=lambda: _env_int("LLM_TIMEOUT", 120))
    llm_stream_timeout: int = field(default_factory=lambda: _env_int("LLM_STREAM_TIMEOUT", 180))
    # Adapter 瞬时故障重试：仅 transient（429/5xx/超时/连接错误）
    # 走指数退避重试，上限与退避基准统一走 config；permanent 不重试立即上抛
    adapter_retry_max: int = field(default_factory=lambda: _env_int("ADAPTER_RETRY_MAX", 2))
    adapter_retry_base_delay: float = field(
        default_factory=lambda: float(os.getenv("ADAPTER_RETRY_BASE_DELAY", "1.0"))
    )
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
    # trace 持久化的 reasoning 尾部保留字符数（头部截断，仅展示用）
    trace_reasoning_max_chars: int = field(default_factory=lambda: _env_int("TRACE_REASONING_MAX_CHARS", 2000))
    # CLI 协议（如 gemini-cli/Antigravity CLI）路由到 custom-api 反代时 auto 的回退模型：
    # 聊天已对齐画布行为改走本机 agy CLI，此值仅影响带参考图的生图编辑等
    # 必须走反代的残留路径；反代报 model not register 时用 CLI_AUTO_CHAT_MODEL 覆盖
    cli_auto_chat_model: str = field(default_factory=lambda: os.getenv("CLI_AUTO_CHAT_MODEL", "gemini-3.1-flash-image"))

    # Token 预算管理
    context_window_size: int = field(default_factory=lambda: _env_int("CONTEXT_WINDOW_SIZE", 128000))
    token_budget_ratio: float = field(default_factory=lambda: float(os.getenv("TOKEN_BUDGET_RATIO", "0.8")))
    # 单张图片的 vision token 固定估算；取常见高分辨率档保守值
    image_token_estimate: int = field(default_factory=lambda: _env_int("IMAGE_TOKEN_ESTIMATE", 1200))
    # 旧轮 read_* 回喂全文的惰性压缩阈值：消息总量达到预算的该比例才压缩，
    # 短对话保留全文保质量，长对话才省 token（0 = 始终压缩，1 = 永不压缩）
    feedback_compress_ratio: float = field(default_factory=lambda: float(os.getenv("FEEDBACK_COMPRESS_RATIO", "0.35")))
    # tool-result 消化（默认开）：历史中已投影进状态 JSON 的写类工具结果回喂行
    # 超过该字符数即替换为「摘要 + 状态已在工作台 JSON」指针；只消化已投影结果，
    # 最近 2 轮回喂保留原文；=0 一键关闭（对标 Anthropic tool-result 消化杠杆）
    tool_result_digest_chars: int = field(default_factory=lambda: _env_int("TOOL_RESULT_DIGEST_CHARS", 200))
    # 工具结果回喂剪枝（默认开）：白名单工具（read_*/生成类）的回喂副本
    # 超过该字符数即保留头尾、中段替换为 PRUNE 标记行（start= 续读兜底）；
    # 只剪回喂进 history 的副本，工具原始返回/state/产物文件不动；
    # =0 一键整体关闭（回滚开关）。与 digest 杠杆职责互补（写类结果归 digest 管）
    tool_result_prune_chars: int = field(default_factory=lambda: _env_int("TOOL_RESULT_PRUNE_CHARS", 6000))
    # 剪枝保留的头部字符数（头部含文档标题/流程开头，约束密度高）
    tool_result_prune_head: int = field(default_factory=lambda: _env_int("TOOL_RESULT_PRUNE_HEAD", 3000))
    # 剪枝保留的尾部字符数（尾部含收尾约束/最近编辑位置）
    tool_result_prune_tail: int = field(default_factory=lambda: _env_int("TOOL_RESULT_PRUNE_TAIL", 2000))
    # 会话级 compaction（默认开）：history 条数达该阈值时用
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

    # 图片生成超时（秒）
    image_gen_timeout: int = field(default_factory=lambda: _env_int("IMAGE_GEN_TIMEOUT", 180))

    # 附件限制
    max_doc_chars: int = field(default_factory=lambda: _env_int("MAX_DOC_CHARS", 30000))
    max_attachments: int = field(default_factory=lambda: _env_int("MAX_ATTACHMENTS", 5))

    # （B1 裁决 2026-08-31：skill_inject_max_tokens 预算式正文头部注入退役删除——
    # 默认注入收窄为 <planner> 段全文 + 章节目录，其余经 read_skill 按需取读。）
    # Skill 开关与目录规模化（批5/对齐 Flova 卡片开关）：
    # skills_disabled = 被停用 Skill 的 slug 列表（默认空 = 全启用，存量不受影响；
    # 写入点归 web/routes/runtime_settings 既有热更新通道）；
    # skill_catalog_max_entries = 目录段条目预算，超预算按最近使用序截断、
    # 尾部附指针行（目录段序 order=20 不动，保前缀缓存）
    skills_disabled: List[str] = field(default_factory=list)
    skill_catalog_max_entries: int = field(
        default_factory=lambda: _env_int("SKILL_CATALOG_MAX_ENTRIES", 30))
    # 执行偏好三档（2026-08-30 用户裁决，Skill 系统修复批 B）：管花钱生成动作
    # （生成图片/生成视频）要不要先弹确认卡——
    # auto_decide = 有活跃 Skill 指导的常规生成流免逐次确认（系统代发同意并留痕）；
    # confirm_before_gen = 每次生成前确认（默认档，行为与现状一致）；
    # generate_directly = 免确认直接执行（留痕）。
    # 枚举白名单清洗归路由层（web/routes/runtime_settings），
    # 写入点归既有热更新通道，未注册/非花钱高危工具的兜底拦截不受本档影响。
    execution_preference: str = "confirm_before_gen"

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

    def __post_init__(self) -> None:
        # SKILL_RUNTIME_MODE/SKILL_RUNTIME 已退役（fail-hard）：
        # 通用主路径（元数据头 + 全文分级注入）为唯一 Skill 注入路径，
        # 残留环境变量一律启动即拒——防"以为仍处回退闸保护中"的错觉。
        _stale = str(os.getenv("SKILL_RUNTIME_MODE")
                     or os.getenv("SKILL_RUNTIME") or "").strip()
        if _stale:
            raise ValueError(
                f"SKILL_RUNTIME_MODE/SKILL_RUNTIME={_stale!r} 已退役（整改批 3.5）："
                "通用主路径为唯一 Skill 注入路径，请移除该环境变量后重启")
        # 画布旧环境变量已退役（画布集成收敛到 canvas-agent 单后端）：
        # 检测到旧键只警告不 raise（仿 SKILL_RUNTIME 显式处置，旧键已无读取方，
        # 硬拒会阻断正常启动）；新键 = CANVAS_AGENT_URL / CANVAS_AGENT_TOKEN
        #（画布站点地址另见 INFINITE_CANVAS_URL）。
        for _stale_canvas_key in (
            "CANVAS_BASE_URL", "CANVAS_PROVIDERS_URL",
            "CANVAS_PROVIDERS_FILE", "CANVAS_ENV_FILE",
        ):
            if str(os.getenv(_stale_canvas_key) or "").strip():
                logging.getLogger(__name__).warning(
                    f"[Config] 环境变量 {_stale_canvas_key} 已退役（画布集成收敛到 "
                    "canvas-agent 单后端），不再被读取；新键为 CANVAS_AGENT_URL / "
                    "CANVAS_AGENT_TOKEN（画布站点地址用 INFINITE_CANVAS_URL），"
                    "请移除旧键以免误导")

    # 模型分层策略表（编排/生成/摘要/执行器四角色，热更新于 runtime_settings.json；
    # 字段语义见 core/model_policy.py；空 = 跟随主模型/既有回落链）
    model_policy: dict = field(default_factory=dict)
    # 执行器誊写批的快模型（"provider" 或 "provider:model"）；空 = 回落主模型
    executor_fast_model: str = field(default_factory=lambda: os.getenv("EXECUTOR_FAST_MODEL", ""))
    # 执行器机械调用的思考档位（low/medium/high）；空 = 沿用全局 llm_thinking_level；
    # 默认空（不硬编码降档）；要降档由模型分层策略
    # executor/summary 行配置（通用搭配默认 low）；本字段仅保留作 env 覆写回落。
    executor_thinking_level: str = field(default_factory=lambda: os.getenv("EXECUTOR_THINKING_LEVEL", ""))
    # 剧本正文注入上限；仅超模型上下文硬窗时才截断，截断附可见警告
    script_inject_limit: int = field(default_factory=lambda: _env_int("SCRIPT_INJECT_LIMIT", 20000))
    # 状态驱动管线开关（阶段表/闸预检/账本同步总闸；默认开）
    pipeline_orchestrator_enabled: bool = field(
        default_factory=lambda: _env_bool("PIPELINE_ORCHESTRATOR_ENABLED", True))

    # 任务管理
    task_ttl_seconds: int = field(default_factory=lambda: _env_int("TASK_TTL_SECONDS", 86400))
    task_max: int = field(default_factory=lambda: _env_int("TASK_MAX", 500))
    # 每项目快照数量上限（超限时创建后淘汰最旧；≤ 0 按 1 处理）
    snapshot_max_per_project: int = field(
        default_factory=lambda: _env_int("SNAPSHOT_MAX_PER_PROJECT", 20))
    # Agent trace JSONL 体积轮转
    trace_file_max_bytes: int = field(default_factory=lambda: _env_int("TRACE_FILE_MAX_BYTES", 2_000_000))
    # 轮转保留份数（trace 供近期审计，历史归档归文件备份）；
    # 可用 TRACE_ROTATION_KEEP 环境变量覆盖
    trace_rotation_keep: int = field(default_factory=lambda: _env_int("TRACE_ROTATION_KEEP", 2))
    # trace 总容量上限（主文件+.N 合计，超则从最旧丢弃）
    trace_total_max_bytes: int = field(default_factory=lambda: _env_int("TRACE_TOTAL_MAX_BYTES", 20_000_000))

    # 上传限制
    max_upload_size_mb: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_SIZE_MB", 50))

    # 请求限流（每分钟每 IP 最大请求数，0 = 不限流）
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 10))
    # 生成类端点（/api/generate*）单独配额：批量生图/生视频会连续提交多个任务，
    # 与聊天共用低配额会误伤正常批量操作
    rate_limit_generate_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_GENERATE_PER_MINUTE", 60))
    # 是否信任 X-Forwarded-For 头提取客户端 IP（仅在可信反向代理后置 true；
    # 本机直连部署下该头可被伪造，用于绕过 IP 级限流）
    trust_proxy: bool = field(default_factory=lambda: _env_bool("TRUST_PROXY", False))

    # 存储后端（"local" | "s3"）
    storage_backend: str = field(default_factory=lambda: os.getenv("STORAGE_BACKEND", "local"))

    # 项目状态持久化后端（"json" | "sqlite"）：默认 sqlite（事务原子性
    # 与并发安全）且为项目状态唯一事实源（首启自动从旧 JSON 文件一次性导入）；
    # STATE_BACKEND=json 仅保留为测试基线与旧 JSON 工作区回落路径，
    # sqlite 写入后回退不再无损
    state_backend: str = field(default_factory=lambda: os.getenv("STATE_BACKEND", "sqlite"))

    # 画布集成（infinite-canvas 单后端，经 canvas-agent HTTP 协议）
    canvas_timeout: int = field(default_factory=lambda: _env_int("CANVAS_TIMEOUT", 30))
    canvas_enabled: bool = field(default_factory=lambda: _env_bool("CANVAS_ENABLED", True))

    canvas_health_cache_seconds: int = field(default_factory=lambda: _env_int(
        "CANVAS_HEALTH_CACHE_SECONDS", 30))
    # infinite-canvas canvas-agent 通道：
    # agent HTTP 服务地址；token 默认空 = 自动回退读 ~/.infinite-canvas/canvas-agent.json
    #（canvas-agent 首次启动生成）；画布站点地址（前端 iframe 嵌入引导用）
    canvas_agent_url: str = field(default_factory=lambda: os.getenv(
        "CANVAS_AGENT_URL", "http://127.0.0.1:17371"))
    canvas_agent_token: str = field(default_factory=lambda: os.getenv("CANVAS_AGENT_TOKEN", ""))
    infinite_canvas_url: str = field(default_factory=lambda: os.getenv(
        "INFINITE_CANVAS_URL", "http://localhost:3000"))
    # canvas_get_state TTL 快照缓存（秒，1–2s 抗高频读）；写路径一律绕过缓存
    canvas_agent_state_cache_seconds: float = field(default_factory=lambda: float(
        os.getenv("CANVAS_AGENT_STATE_CACHE_SECONDS", "1.5")))
    # 画布外壳 UI 在画布 iframe 内的偏移估计（侧栏宽 + stage 边距），用于拖放落点换算；
    # 画布独立迭代若改了外壳布局，可通过环境变量调整，不影响功能（结果会被夹取到可视区内）
    canvas_shell_offset_x: int = field(default_factory=lambda: _env_int("CANVAS_SHELL_OFFSET_X", 96))
    canvas_shell_offset_y: int = field(default_factory=lambda: _env_int("CANVAS_SHELL_OFFSET_Y", 16))
    # 画布读工具输出预算（对齐输出预算哲学）：canvas_read_nodes 单节点 prompt 截断阈值；
    # canvas_list_assets 默认页大小（超限返回 has_more=True）
    canvas_read_prompt_max_chars: int = field(default_factory=lambda: _env_int(
        "CANVAS_READ_PROMPT_MAX_CHARS", 2000))
    canvas_asset_page_size: int = field(default_factory=lambda: _env_int("CANVAS_ASSET_PAGE_SIZE", 50))

    # MCP 外部工具接入层：总开关（无配置文件 = 零工具，
    # deny-first）；活动工具上限（mcp_tool_catalog enable 超限拒收）；
    # 单结果回喂字符上限（超限截断附警告，防外部结果撑爆上下文）
    mcp_enabled: bool = field(default_factory=lambda: _env_bool("MCP_ENABLED", True))
    mcp_max_active_tools: int = field(default_factory=lambda: _env_int("MCP_MAX_ACTIVE_TOOLS", 8))
    mcp_result_max_chars: int = field(default_factory=lambda: _env_int("MCP_RESULT_MAX_CHARS", 4000))


# 全局单例（启动时加载一次）
settings = Settings()
