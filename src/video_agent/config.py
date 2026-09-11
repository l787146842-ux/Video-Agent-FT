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


# 执行模式四档白名单枚举（2026-09-06 用户裁决，对齐批）：
# 单一事实源——路由层清洗/下发、core 引导注入与阶段闸分流、sidecar 契约导出同引用。
# 与 execution_preference（素材生成档，管花钱生成的确认）正交：
# ai_decide = 停不停由模型按 Skill 散文与当场情况判断（默认档，行为与现状一致，
#             不注入任何引导）；
# auto_full = 全流程直通，压制阶段暂停确认（信息缺口必答除外）；
# key_steps_confirm = 关键里程碑（规格/故事板/关键元素/镜头视频/音频/成片）平台机械拦停，
#             档位 > Skill 散文；
# pause_all = 每个阶段完成后平台机械拦停。
EXECUTION_MODE_VALUES = ("ai_decide", "auto_full", "key_steps_confirm", "pause_all")
EXECUTION_MODE_DEFAULT = "ai_decide"
# 机械闸激活档（仅这两档轮末阶段闸签发暂停卡）；单一事实源，core 阶段闸同引用。
EXECUTION_MODE_GATE_MODES = ("key_steps_confirm", "pause_all")


def normalize_exec_mode(value) -> str:
    """执行模式白名单清洗（唯一规整口）：命中枚举原样返回，
    其余（非法/空/脏值）回落默认档。"""
    v = str(value or "").strip().lower()
    return v if v in EXECUTION_MODE_VALUES else EXECUTION_MODE_DEFAULT



# 输出 token 上限默认值（对齐 dsh DEFAULT_MAX_TOKENS=256_000）
LLM_MAX_TOKENS_ENV = "LLM_MAX_TOKENS"


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
    # 优雅关停宽限（秒）：uvicorn timeout_graceful_shutdown。关停时先向在途 SSE
    # 投递终态帧，再等待任务收尾；默认 10s——够投递终态帧 + 冲刷防抖落盘，
    # 又不至于让无在途任务的正常关停白等（原 30s 偏长，交互式重启体感卡顿）
    shutdown_grace_seconds: int = field(default_factory=lambda: _env_int("SHUTDOWN_GRACE_SECONDS", 10))

    # 安全
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", ""))
    # 日志文件落盘开关：服务进程默认开；测试/验收子进程经
    # conftest / scripts/acceptance.py 置 false，避免多进程争用同一日志文件
    # 触发 loguru rotation rename 失败（WinError 32）
    log_file_enabled: bool = field(default_factory=lambda: _env_bool("LOG_FILE_ENABLED", True))

    # 子代理 run_subagent 总开关（关=不下发 run_subagent 工具，一键回滚）
    subagent_enabled: bool = field(default_factory=lambda: _env_bool("SUBAGENT_ENABLED", True))



    # LLM 超时（秒）
    llm_timeout: int = field(default_factory=lambda: _env_int("LLM_TIMEOUT", 120))
    llm_stream_timeout: int = field(default_factory=lambda: _env_int("LLM_STREAM_TIMEOUT", 180))
    # Adapter 瞬时故障重试：仅 transient（429/5xx/超时/连接错误）
    # 走指数退避重试，上限与退避基准统一走 config；permanent 不重试立即上抛
    adapter_retry_max: int = field(default_factory=lambda: _env_int("ADAPTER_RETRY_MAX", 2))
    adapter_retry_base_delay: float = field(
        default_factory=lambda: float(os.getenv("ADAPTER_RETRY_BASE_DELAY", "1.0"))
    )
    # LLM 生成参数（adapter 未显式传参时的回落值）。
    # 默认对齐 dsh（DeepSeek 官方 harness）DEFAULT_MAX_TOKENS=256_000：
    # max_tokens 是上限不是目标，不产生额外费用；推理模型思考 token 计入该
    # 额度，小帽子会把思考耗尽返回空响应（4444 项目事故）。端点拒收大值时
    # 由 adapter 400 钳制分支回落到模型安全帽（token_budget.output_limit_for_model）。
    llm_max_tokens: int = field(default_factory=lambda: _env_int("LLM_MAX_TOKENS", 256_000))
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
    # 思考内容回传（五项修法批 4，default-off）：开 = assistant 历史消息
    # 携带 reasoning_content 原样回传端点（GLM 4.5+ 交错思考/工具循环官方
    # 要求回传以保持推理连续性；DeepSeek 同语义）。关（默认）= 不回传且
    # 请求侧剥离该字段（防历史残留字段外泄拒收端点）。仅 OpenAI 兼容层生效。
    llm_reasoning_passthrough: bool = field(
        default_factory=lambda: _env_bool("LLM_REASONING_PASSTHROUGH", False))
    # trace 持久化的 reasoning 尾部保留字符数（头部截断，仅展示用）
    trace_reasoning_max_chars: int = field(default_factory=lambda: _env_int("TRACE_REASONING_MAX_CHARS", 2000))
    # CLI 协议（如 gemini-cli/Antigravity CLI）路由到 custom-api 反代时 auto 的回退模型：
    # 聊天已对齐画布行为改走本机 agy CLI，此值仅影响带参考图的生图编辑等
    # 必须走反代的残留路径；反代报 model not register 时用 CLI_AUTO_CHAT_MODEL 覆盖
    cli_auto_chat_model: str = field(default_factory=lambda: os.getenv("CLI_AUTO_CHAT_MODEL", "gemini-3.1-flash-image"))

    # Token 预算管理
    # 未配置窗口的模型回落值（用户三挡裁决 2026-09-08：200K 默认挡）；
    # 已配置模型走 chat_models_meta / model_context_windows.json 精确查表
    context_window_size: int = field(default_factory=lambda: _env_int("CONTEXT_WINDOW_SIZE", 200000))
    token_budget_ratio: float = field(default_factory=lambda: float(os.getenv("TOKEN_BUDGET_RATIO", "0.8")))
    # 单张图片的 vision token 固定估算；取常见高分辨率档保守值
    image_token_estimate: int = field(default_factory=lambda: _env_int("IMAGE_TOKEN_ESTIMATE", 1200))
    # tool-result 消化（用户裁决 2026-09-08 默认关）：窗口放大后历史只追加
    # 保前缀缓存连续命中（缓存命中价 1/30 全价，省消化那点 token 不值当）；
    # 逼近预算时由会话层阈值压缩兜底（v4 批 E3，session_log.compact_pass）。
    # 仍可 env 设阈值开启（最近 2 轮回喂保留原文；=0 关闭）
    tool_result_digest_chars: int = field(default_factory=lambda: _env_int("TOOL_RESULT_DIGEST_CHARS", 0))
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
    # 第 5 批上下文治理（Q6 裁决 2026-09-01）：状态注入字符预算。
    # 状态 JSON 组装后超该字符数自动降 B 档（组级正文截断+指针，
    # 全文经 read_state_group 按需读回）；未超保持 A 档全量（小项目零行为变化）；
    # 0 = 永远 A 档全量注入（一键回滚开关）
    state_context_budget_chars: int = field(
        default_factory=lambda: _env_int("STATE_CONTEXT_BUDGET_CHARS", 20000))
    # B 档组级正文（desc/roughDesc）截断字符数
    state_group_body_chars: int = field(
        default_factory=lambda: _env_int("STATE_GROUP_BODY_CHARS", 120))
    # 微调真子对话（对齐外部标杆）：总开关。关闭时后端忽略请求携带的
    # adjust_scope，回落旧行为（一键回滚）
    adjust_subdialog_enabled: bool = field(
        default_factory=lambda: _env_bool("ADJUST_SUBDIALOG_ENABLED", True))
    # 项目级微调（scope）任务并发上限：运行中 scope 任务达上限时
    # 新提交返回结构化提示（防线程膨胀）
    adjust_task_concurrency: int = field(
        default_factory=lambda: _env_int("ADJUST_TASK_CONCURRENCY", 4))
    # 第 5 批（Q7）/ 用户裁决 2026-09-01：上下文不设上限，超预算不拦发。
    # warn（默认）= 四级保险丝用尽仍超窗口时记 warning 后照发，
    # 上游报上下文超长经 AdapterError 通道原样透传；
    # error = 回拨开关（四级用尽仍超窗口时报错不发请求）
    context_overflow_policy: str = field(
        default_factory=lambda: os.getenv("CONTEXT_OVERFLOW_POLICY", "warn"))
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
    # Skill 开关与目录规模化（批5/对齐外部标杆 卡片开关）：
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

    # 执行模式四档（2026-09-06 用户裁决，对齐批）：管流程推进的暂停策略——
    # ai_decide = 停不停由模型按 Skill 散文与当场情况判断（默认档，行为与现状一致，
    #             不注入引导）；
    # auto_full = 全流程直通（注入抑制暂停引导，信息缺口必答除外）；
    # key_steps_confirm = 关键里程碑平台机械拦停（档位 > Skill 散文）；
    # pause_all = 每阶段完成后平台机械拦停。
    # 与 execution_preference（素材生成档）正交；枚举白名单清洗归路由层，
    # 机械闸激活档见 EXECUTION_MODE_GATE_MODES（core 阶段闸同引用）。
    execution_mode: str = "ai_decide"

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
    # trace 分级留存（utils/trace_retention.py 经 getattr 防御读取，缺省即下列默认）：
    # hot 窗口内保留全量字段；hot~warm 压缩为摘要（reasoning 截断到 reasoning_max）；
    # 超 warm 窗口丢弃。默认 24h / 7d / 120 字符（与 trace_retention 默认一致）
    trace_hot_window_s: int = field(default_factory=lambda: _env_int("TRACE_HOT_WINDOW_S", 86400))
    trace_warm_window_s: int = field(default_factory=lambda: _env_int("TRACE_WARM_WINDOW_S", 604800))
    trace_warm_reasoning_max: int = field(default_factory=lambda: _env_int("TRACE_WARM_REASONING_MAX", 120))
    # trace 分级留存总开关（默认关）：轮转产物 .jsonl.N 的 hot/warm/cold 压缩
    # 与 log_file_enabled 同守卫——测试/验收子进程置 false 时不改写磁盘 trace，
    # 避免多进程争用；生产按需开启（首次压缩前原文件另存 .pre-compact 备份）
    trace_retention_enabled: bool = field(default_factory=lambda: _env_bool("TRACE_RETENTION_ENABLED", False))

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

    # 缓存命中遥测落盘开关：record_cache_usage 除内存滚动窗口外，追加写
    # cache_metrics.jsonl（路径归 utils/paths）供离线分析前缀缓存命中率。
    # 与 log_file_enabled 同守卫（测试/验收进程置 false，防多进程争用同一文件）
    cache_metrics_enabled: bool = field(default_factory=lambda: _env_bool("CACHE_METRICS_ENABLED", True))
    # cache_metrics.jsonl 字节上限（超限截断重开，防只增不轮转无界膨胀）：
    # 默认 2MB——命中率是滚动窗口口径，历史样本离线分析够用即可，不必长留
    cache_metrics_max_bytes: int = field(default_factory=lambda: _env_int("CACHE_METRICS_MAX_BYTES", 2_000_000))


# ====== 嵌套分组视图（宪法 §四：Settings 只读；此处分组仅为读取便利，
# 不改扁平字段本体——旧扁平属性名（settings.port 等）与 env 键名保持不变，
# 运行时热更新（object.__setattr__ 改扁平字段）经委托视图即时可见）======

# 组名 → 该组包含的扁平字段名（组名与任一扁平字段名无碰撞）。
# 单一事实源仍是上方 dataclass 字段；本表只做「聚合读取视图」编排。
SETTINGS_GROUPS: dict = {
    "server": ("port", "host", "shutdown_grace_seconds"),
    "security": ("environment", "api_key", "log_file_enabled", "trust_proxy",
                 "rate_limit_per_minute", "rate_limit_generate_per_minute"),
    "agent": ("adjust_subdialog_enabled", "adjust_task_concurrency",
              "execution_preference", "execution_mode", "pipeline_orchestrator_enabled",
              "script_inject_limit"),
    "llm": ("llm_timeout", "llm_stream_timeout", "adapter_retry_max",
            "adapter_retry_base_delay", "llm_max_tokens", "llm_temperature",
            "llm_output_limit", "llm_json_timeout", "llm_thinking_level",
            "aux_thinking_level", "llm_reasoning_passthrough",
            "cli_auto_chat_model", "model_fallback_enabled",
            "model_fallback_max_candidates", "executor_fast_model",
            "executor_thinking_level", "model_policy"),
    "context": ("context_window_size", "token_budget_ratio", "image_token_estimate",
                "tool_result_digest_chars",
                "tool_result_prune_chars", "tool_result_prune_head",
                "tool_result_prune_tail", "history_compact_threshold",
                "context_json_compact", "state_context_budget_chars",
                "state_group_body_chars", "context_overflow_policy", "prompt_gate_mode",
                "llm_image_max_edge", "max_doc_chars", "max_attachments",
                "max_llm_images", "trace_reasoning_max_chars"),
    "media": ("image_gen_timeout", "image_ref_limit", "image_gen_concurrency",
              "video_gen_concurrency", "audio_gen_concurrency", "video_ref_limit_image",
              "video_ref_limit_video", "video_ref_limit_audio", "video_ref_limit_total",
              "max_chat_inserts", "default_image_provider_id", "default_image_model",
              "default_video_provider_id", "default_video_model", "chat_image_enabled",
              "default_image_resolution", "default_video_resolution", "max_shot_duration"),
    "skills": ("skills_disabled", "skill_catalog_max_entries"),
    "tasks": ("task_ttl_seconds", "task_max", "snapshot_max_per_project",
              "trace_file_max_bytes", "trace_rotation_keep", "trace_total_max_bytes",
              "trace_hot_window_s", "trace_warm_window_s", "trace_warm_reasoning_max",
              "trace_retention_enabled"),
    "storage": ("max_upload_size_mb", "storage_backend", "state_backend"),
    "canvas": ("canvas_timeout", "canvas_enabled", "canvas_health_cache_seconds",
               "canvas_agent_url", "canvas_agent_token", "infinite_canvas_url",
               "canvas_agent_state_cache_seconds", "canvas_shell_offset_x",
               "canvas_shell_offset_y", "canvas_read_prompt_max_chars",
               "canvas_asset_page_size"),
    "mcp": ("mcp_enabled", "mcp_max_active_tools", "mcp_result_max_chars"),
    "metrics": ("cache_metrics_enabled", "cache_metrics_max_bytes"),
}


class _SettingsGroup:
    """嵌套子组只读视图：属性访问实时委托到底层扁平字段。

    委托而非快照——运行时热更新（runtime_settings 通道 object.__setattr__
    改扁平字段）后，经子组视图读取立即反映最新值，与直接读扁平属性一致。
    """

    __slots__ = ("_settings", "_names", "_group")

    def __init__(self, settings_obj: "Settings", names, group: str = "") -> None:
        self._settings = settings_obj
        self._names = tuple(names)
        self._group = group

    def __getattr__(self, name: str):
        # 仅在常规查找失败时触发；_settings/_names/_group 为 slot，正常命中不进此处。
        # 防无限递归：slot 未初始化（pickle/copy 绕过 __init__ 等）时，
        # 读 self._names 会再次落入 __getattr__ → 死循环；改用
        # object.__getattribute__ 直取 slot，未初始化则立即 raise AttributeError(name)。
        try:
            names = object.__getattribute__(self, "_names")
            settings_obj = object.__getattribute__(self, "_settings")
            group = object.__getattribute__(self, "_group")
        except AttributeError:
            raise AttributeError(name)
        if name in names:
            return getattr(settings_obj, name)
        raise AttributeError(
            f"设置组 {group!r} 无字段 {name!r}（可用键: {', '.join(names)}）"
        )

    def __repr__(self) -> str:
        try:
            group = object.__getattribute__(self, "_group")
            names = object.__getattribute__(self, "_names")
        except AttributeError:
            return "<_SettingsGroup (uninitialized)>"
        return f"<_SettingsGroup {group!r}: {', '.join(names)}>"

    def __dir__(self):
        return list(self._names)

    def as_dict(self) -> dict:
        """本组全部字段的实时值快照（调试/序列化用）。"""
        return {n: getattr(self._settings, n) for n in self._names}


def _make_group_property(names, group: str = ""):
    """构造绑定到指定字段名集合的只读分组 property。"""
    def _getter(self):
        return _SettingsGroup(self, names, group)
    return property(_getter)


# 程序化挂载分组视图（组名均非 dataclass 字段名，不干扰 fields()/__init__）
for _group_name, _group_fields in SETTINGS_GROUPS.items():
    setattr(Settings, _group_name, _make_group_property(_group_fields, _group_name))


# 全局单例（启动时加载一次）
settings = Settings()
