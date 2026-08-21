/* eslint-disable max-lines */ // 前后端契约类型集中于单文件便于对照
/**
 * FTDYB 全局类型定义
 * 精确匹配后端 API 数据模型（从旧 studio/types.ts 迁移 + 规范化）
 *
 * 契约来源纪律（路线 a， 用户终裁；  消费面补齐）：
 * API 边界请求/响应类型以 api.generated.ts（FastAPI OpenAPI schema 生成）为唯一来源，
 * 本文件只保留别名 re-export 与视图态类型；tsc 编译期即契约门禁。
 * 消费覆盖防回退由 vitest 桥接测试 api-contract.test.ts 机械断言（只升不降）。
 *
 * 豁免清单（后端未建模为 Pydantic、OpenAPI 无对应 schema，或手写显著更精，留手写并登记）：
 * - SSE 事件族（SseStatusEvent/SseDonePayload 等）：SSE 流式载荷，后端 dict 直发；
 * - TaskResult / AgentTaskReplayPayload：任务式传输载荷，同上；
 * - ServerStateSnapshot / ChatMessage / Draft 等视图态：前端渲染形态，非 API 模型；
 * - 手写响应类型比生成物更精确的站点（生成物对 Dict 响应只能给出
 *   Record<string, unknown>）：ProjectListResponse/ProvidersResponse/
 *   UndoStatusResponse/OkWithStateResponse（api/project.ts、api/providers.ts）、
 *   ChatResponse/OkResponse/TestConnectionResponse/FetchModelsResponse、
 *   ConversationsPayload（api/conversations.ts）、画布读取结果族
 *   CanvasDropImageResult/CanvasNodeImagesResult/AllCanvasImagesResult（api/canvas.ts）、
 *   GenerationLogEntry（api/generate.ts 读形态）、MemoryRecordView（api/memory.ts）、
 *   SkillDoc/SkillDocVersion（api/docs.ts）、RuntimeSettings（api/agent.ts 读形态）、
 *   整板保存 payload（stores/studio/storyboard.ts，后端 ProjectStateUpdate 为粗粒度
 *   unknown 字段）——保留手写强类型，后端建模精细化后再迁。
 * - 生成物消费基座站点（生成物为类型来源，手写只做收窄/精化，  登记）：
 *   GenerateImageRequest/GenerateVideoRequest（交集精化，api/generate.ts）、
 *   BatchImageRequest（Required 收窄必填）、CanvasDropImagePayload（交集精化，api/canvas.ts）。
 * - 前端无消费路径的生成物（后端端点专用/前端走通用端点）：ModelFallbackPatch
 *   （前端开关走通用 runtime PUT）、TimelinePushRequest（时间线回画布走 Agent
 *   工具路径）、Body_upload_files_api_ai_upload_post（multipart 上传）、
 *   DraftCreate/DraftPatch/GroupPatch（草稿操作走整板保存通道）、ProjectStateResponse（空 schema）。
 */
import type { ChatRequest } from './api.generated';

// ===== 基础枚举 =====
export type DraftType = 'keyElement' | 'shot' | 'audio';
export type MediaType = 'image' | 'video' | 'audio';
export type LeftTab = 'storyboard' | 'uncategorized';
export type SubTab = 'keyElements' | 'shots' | 'audio';

// ===== 草稿 / 分组 =====
export interface Draft {
  id: string;
  label: string;
  tag?: string;
  mediaType: MediaType;
  /** 当前选中的生成类型；缺省回退 mediaType（切换生成标签不清空已有预览媒体） */
  genType?: MediaType;
  prompt?: string;
  model?: string;
  mode?: string;
  providerId?: string;
  /** 按种类参数隔离（2026-08-15）：三个生成器各自读写本种类字段，
   *  消除共享字段互相污染（选项集不匹配时下拉空值/塌缩）；
   *  旧共享字段保留，仅作旧数据回退 */
  imageProviderId?: string;
  imageModel?: string;
  videoProviderId?: string;
  videoModel?: string;
  /** 视频画幅比例（独立于图片 aspectRatio） */
  videoAspectRatio?: string;
  audioProviderId?: string;
  audioModel?: string;
  /** 音频生成模式（独立于视频 mode） */
  audioMode?: string;
  aspectRatio?: string;
  duration?: string;
  resolution?: string;
  /** 图片分辨率档位（1K/2K/4K），关键元素生图用 */
  imageResolution?: string;
  size?: string;
  timbre?: string;
  refAssets?: string[];
  imgUrl?: string;
  videoUrl?: string;
  /** 音频文件地址（上传/生成后回写） */
  audioUrl?: string;
  customRatioWidth?: string;
  customRatioHeight?: string;
  status?: string;
}

export interface KeyElementGroup {
  id: string;
  title: string;
  desc?: string;
  badgeLabel?: string;
  drafts: Draft[];
}

export interface ShotGroup {
  id: string;
  title: string;
  duration?: string;
  roughDesc?: string;
  sceneRefs?: string[];
  shotType?: string;
  drafts: Draft[];
}

export interface AudioGroup {
  id: string;
  title: string;
  timeRange?: string;
  prompt?: string;
  drafts: Draft[];
}

export type AnyGroup = KeyElementGroup | ShotGroup | AudioGroup;

// ===== 资产 =====
export interface Asset {
  id: string;
  name: string;
  type: MediaType;
  isBound: boolean;
  url: string;
  /** 来源信息（从故事板移除到未归类时记录，供右键「还原」）：类型/分组ID/草稿快照 */
  sourceType?: DraftType; sourceGroupId?: string; sourceDraft?: Draft;
}

// ===== API 供应商 =====
export interface ApiProvider {
  id: string;
  name: string;
  protocol?: string;
  base_url?: string;
  enabled?: boolean;
  chat_models?: string[];
  image_models?: string[];
  video_models?: string[];
  [key: string]: unknown;
}

// ===== Skill =====
export interface Skill {
  id: string;
  name: string;
  system_prompt?: string;
  description?: string;
  /** 审核整改批 2：规划级执行器名单（后端 capability 注册表下发，欠账显性化） */
  planning_executors?: string[];
  [key: string]: unknown;
}

// ===== 附件 =====
export interface PendingAttachment {
  id: string;
  name: string;
  url: string;
  type: string;
}

// ===== 内联媒体缩略块（输入框 / 消息气泡 / 插入请求共用） =====
/** 内联媒体：图片显示缩略图，视频显示首帧，音频显示图标块；均略大于文字、可混排 */
export interface InlineMedia {
  id: string;
  name: string;
  url: string;
  kind: MediaType;
  /** 缩略图地址（视频可用首帧；图片缺省即 url） */
  thumb?: string;
}

/** 有序富文本片段：文字与媒体按用户排版顺序交错，原样发送给后端供 LLM 识别对应关系 */
export type RichContentPart =
  | { type: 'text'; text: string }
  | { type: 'image'; url: string; name: string }
  | { type: 'video'; url: string; name: string; thumb?: string }
  | { type: 'audio'; url: string; name: string };

// ===== 聊天 =====
export interface ChatMessage {
  sender: 'user' | 'assistant' | 'agent';
  text: string;
  meta?: string;
  confirm?: string;
  appliedActions?: number;
  docCard?: string;
  /** 回复时使用的模型名称（agent 消息） */
  modelName?: string;
  /** 深度思考耗时（毫秒，完成后展示在「深度思考」卡片角标） */
  thinkingMs?: number;
  /** 生图结果图片卡片 */
  imageCard?: ImageCardData;
  /** 用户消息的有序富文本片段（文字 + 内联缩略图交错），用于气泡还原排版 */
  parts?: RichContentPart[];
  /** 用户消息携带的文档附件块（点击可查看文档，发送后才真正附加） */
  docBlocks?: string[];
  /** 用户消息携带的 Skill 引用块（点击查看 Skill 文档） */
  skillBlocks?: string[];
  /** 本轮已执行操作的中文描述清单（「阶段完成」卡片展开查看具体操作） */
  actionLog?: string[];
  /** 确认卡片的候选选项（单选卡片，点击即把 value||label 作为回复发送； value 机械消费） */
  confirmOptions?: Array<{ label: string; description?: string; group?: string; value?: string }>;
  /** 模型降级等警示行（常驻展示在 agent 气泡上，刷新后仍可见） */
  warnings?: string[];
  /** 本轮 Agent 参考的长期记忆命中（折叠展示） */
  memoryHits?: Array<{ date?: string; content: string }>;
  /** 执行轨迹（每轮 step/耗时/操作数，「执行轨迹」折叠区展示） */
  trace?: AgentTrace;
  /** ：鉴权/供应商类错误气泡附「检查 API 配置」跳转按钮 */
  settingsHint?: boolean;
  /** ：错误气泡的技术详情（上游原始报文），「技术详情」折叠渲染，默认不展开 */
  errorDetail?: string;
  /** ：轮次唯一标识（同轮正文/文档卡/图片卡共用，渲染层聚合为轮次容器） */
  turnId?: string;
  /** ：建议动作按钮（随 done payload 落消息，仅最后一条渲染；
   *  扩 next=状态驱动下一步建议，点击机械发送 value） */
  suggestedActions?: Array<{ kind: 'retry' | 'continue' | 'next'; label: string; value: string }>;
  /** 暂停卡结构化标识（后端三个 confirm 产生源统一签发，随 done payload 下发） */
  pauseId?: string;
  /** 用户回应暂停的结构化标记（与对应暂停卡的 pauseId 匹配；对勾不再靠文本反推） */
  pauseAnsweredId?: string;
  pauseAnsweredValue?: string;
  /** 消息形态标记（批6 收窄：system_action=系统动作行；其余为暂停卡语义种类，
   *  源自后端 pause_kind） */
  kind?: 'system_action' | 'remind' | 'collect' | 'stage_done' | 'confirm';
}

/** Agent 执行轨迹（后端 tracer.py 产出） */
export interface TraceAction { name: string; summary: string; elapsed_ms: number; ok: boolean; /** B2/F15：大阶段标签（后端权威下发） */ stage?: string; /** 批2 透明度：工具执行结果一句话摘要（与 SSE tool_finished 同口径） */ result_summary?: string; /** 审核整改批 2：规划级执行器标记（capability 注册表下发） */ planning?: boolean; }
/** 闸机判定明细（后端 tracer.record_gate 产出，：前端按结构渲染来源标注 chips） */
export interface GateRecord {
  rule_id: string;
  layer: 'platform' | 'skill' | 'session' | string;
  ok: boolean;
  overridden?: boolean;
  skill_name?: string;
  action?: string;
  draft_id?: string;
  message?: string;
}
export interface AgentTraceStep {
  step: number;
  timing_ms: number;
  token_usage: number;
  actions_applied: number;
  finish_reason: string;
  /** 本轮执行的操作明细（过程时间线逐条展示） */
  actions?: TraceAction[];
  /** 本轮 reasoning（深度思考）文本摘要（仅展示，不进下次上下文） */
  reasoning?: string;
  /** 本轮闸机判定明细（前端渲染来源标注 chips） */
  gates?: GateRecord[];
}
export interface AgentTrace {
  trace_id?: string;
  total_ms?: number;
  total_actions?: number;
  steps?: AgentTraceStep[];
}

// ===== 生图卡片（Agent 生图结果展示 + 拖拽） =====
export interface ImageCardData {
  image_urls: string[];
  /** 生成模型/供应商标识 */ provider?: string;
}

// ===== 文档 =====
export interface DocRecord {
  id: string;
  kind: string;
  key: string;
  name: string;
  content: string;
  updated_at?: string;
}

// ===== 生成任务 =====
export interface ActiveGeneration {
  start: number;
  kind: 'image' | 'video';
}

export interface TaskResult {
  status: string;
  task_id?: string;
  result?: { images?: string[] };
  video_url?: string;
  error?: string;
  elapsed?: string;
  mock?: boolean;
}

// ===== SSE 事件（Agent 聊天流） =====
// 契约锚点：事件名以后端 src/video_agent/core/sse_events.py 的 SSE_* 常量为唯一权威；
// 新增/改名事件时两侧必须同步（后端常量 → 本联合类型 → use-sse.ts 的 switch）。
export interface SseStatusEvent {
  type: 'status';
  text: string;
  /** ：固定文案 i18n 键（前端 locale 字典同键翻译；缺失时回退 text） */
  key?: string;
  /** key 的插值参数 */
  params?: Record<string, string | number>;
}
export interface SseDeltaEvent { type: 'delta'; text: string; }
/** 深度思考（reasoning）增量：仅 UI 展示，不进下次 LLM 上下文 */
export interface SseReasoningEvent { type: 'reasoning_delta'; text: string; }
/** 过程时间线：工具/操作开始 */
export interface SseToolStartedEvent { type: 'tool_started'; id: string; name: string; summary: string; }
/** 过程时间线：工具/操作完成 */
export interface SseToolFinishedEvent {
  type: 'tool_finished';
  id: string;
  ok: boolean;
  elapsed_ms: number;
  result_summary?: string;
  /** 审核整改批 2：规划级执行器标记（后端 capability 注册表下发） */
  planning?: boolean;
}
export interface SseDonePayload {
  text: string;
  elapsed_ms: number;
  steps: number;
  applied_actions: number;
  confirmation?: string;
  /** 暂停卡结构化标识（用户点选回应时经 pause_response 结构化回携） */
  pause_id?: string;
  /** Rule2 v6：暂停卡语义种类（remind/collect/stage_done/confirm，卡标题渲染依据） */
  pause_kind?: string;
  documents_written?: string[];
  warnings?: string[];
  image_urls?: string[];
  /** Agent 要求插入对话输入框的故事板媒体（insert_chat_media / storyboard_media_to_chat 产出） */
  chat_inserts?: Array<{ kind: MediaType; url: string; name: string; thumb?: string }>;
  /** 本轮已执行操作的中文描述清单（前端展示具体操作内容） */
  action_log?: string[];
  /** 确认卡片的候选选项（单选卡片，点击即把 value||label 作为回复发送） */
  confirmation_options?: Array<{ label: string; description?: string; group?: string; value?: string }>;
  /** 主模型故障时 fallback 实际使用的模型名（供气泡标注） */
  fallback_model?: string;
  /** 执行轨迹（每轮 step/耗时/操作数） */
  trace?: AgentTrace;
  /** 本轮 Agent 参考的长期记忆命中（4.7：前端「记忆参考」折叠展示） */
  memory_hits?: Array<{ id?: string; date?: string; content: string }>;
  /** ：轮次唯一标识（前端同轮消息聚合为轮次容器） */
  turn_id?: string;
  /** ：建议动作按钮（retry=机械重发上一条用户消息；continue=发送固定文本；
   * next=状态驱动下一步建议） */
  suggested_actions?: Array<{ kind: 'retry' | 'continue' | 'next'; label: string; value: string }>;
  state?: ServerStateSnapshot | null;
}
export interface SseDoneEvent { type: 'done'; payload: SseDonePayload; }
/** 操作已执行（携带最新状态快照）：推理中逐步刷新故事板，不必等全部完成 */
export interface SseActionsAppliedEvent { type: 'actions_applied'; payload?: { count?: number; state?: ServerStateSnapshot | null }; }
/** 后端 error 事件用 detail 字段，可携带 error_code 供前端 i18n 翻译 */
export interface SseErrorEvent { type: 'error'; detail?: string; text?: string; error_code?: string; /** audit-0819：上游原始报文（前端折叠展示） */ raw?: string; }
/** 模型降级即时联动：切换时刻即下发，前端立即把选择器跳到实际生效的组合 */
export interface SseModelFallbackEvent { type: 'model_fallback'; provider?: string; model?: string; }
/** 引导消息轮间注入成功：渲染用户气泡并从排队区移除对应条目 */
export interface SseGuidanceInjectedEvent { type: 'guidance_injected'; id?: string; text?: string; }
/** 文档写入即显：独立文档卡片立即渲染，不等整轮 done；
 * ：后端透传层打戳本轮 turn_id，即显卡严格归入轮次容器 */
export interface SseDocWrittenEvent { type: 'doc_written'; name?: string; turn_id?: string; }
/** 任务式传输：订阅时先回放累计状态（刷新/切项目重连后恢复进度） */
export interface AgentTaskReplayPayload {
  task_id?: string;
  project_id?: string;
  model?: string;
  status?: string;
  status_text?: string;
  reasoning?: string;
  text?: string;
  tools?: Array<{
    id?: string; name?: string; summary?: string; status?: string;
    elapsed_ms?: number | null; result_summary?: string; started_at_ms?: number;
    /** 审核整改批 2：规划级执行器标记 */
    planning?: boolean;
  }>;
  snapshot?: ServerStateSnapshot | null;
  done_payload?: SseDonePayload | null;
  /** Rule2 v6：断连期间已写文档累积账本（replay 补渲染文档卡） */
  docs?: string[];
  /** v2 收尾：workflow 事件序列高水位（重连按 sequence 补发/去重依据） */
  wf_event_sequence?: number;
  /** v2 批3：workflow 投影（run 快照 + 本轮事件序列，重载/重连同源重建） */
  workflow?: {
    run_id?: string;
    status?: string;
    current_node?: string;
    completed_nodes?: string[];
    event_sequence?: number;
    pending_decision?: boolean;
    turn_events?: Array<Record<string, unknown>>;
  } | null;
  fallback?: { provider?: string; model?: string } | null;
  error?: string | null;
}
export interface SseReplayEvent { type: 'replay'; payload?: AgentTaskReplayPayload; }
/** 任务状态变更通知（后端 agent_task_manager 下发，如 cancelled）；
 * 批2 契约对齐：此前仅后端 break 条件引用、前端联合类型缺失 */
export interface SseTaskStatusEvent { type: 'task_status'; status?: string; }
export type SseEvent =
  | SseStatusEvent
  | SseDeltaEvent
  | SseReasoningEvent
  | SseToolStartedEvent
  | SseToolFinishedEvent
  | SseActionsAppliedEvent
  | SseDoneEvent
  | SseErrorEvent
  | SseModelFallbackEvent
  | SseGuidanceInjectedEvent
  | SseDocWrittenEvent
  | SseReplayEvent
  | SseTaskStatusEvent;

// ===== 后端状态快照 =====
/** 单个对话（同一项目支持多对话窗口） */
export interface Conversation { id: string; title: string; messages: ChatMessage[]; }

export interface ServerStateSnapshot {
  /** 快照所属项目 ID（持久化请求回传，后端据此丢弃跨项目的过期写入） */
  project_id?: string;
  /** 故事板乐观锁版本（整板保存回携，防陈旧覆盖） */
  board_version?: number;
  keyElements?: KeyElementGroup[];
  shots?: ShotGroup[];
  audioItems?: AudioGroup[];
  assets?: Asset[];
  chatMessages?: ChatMessage[];
  documents?: DocRecord[];
  project_name?: string;
  /** 当前项目已发送给 Agent 的 Skill slug 列表（文档面板只展示这些 Skill 文档） */
  usedSkills?: string[];
  /** 多对话列表（含消息），活跃对话与 chatMessages 一致 */
  conversations?: Conversation[];
  /** 活跃对话 ID */
  activeConversationId?: string;
}

// ===== 查询辅助 =====
export interface DraftRecord {
  type: DraftType;
  group: AnyGroup;
  draft: Draft;
}

export interface GroupRecord {
  type: DraftType;
  group: AnyGroup;
}

// ===== Agent 聊天请求（路线 a：以生成物 ChatRequest 为唯一来源） =====
// 字段语义注释以后端 routes/agent.py::ChatRequest 为准；本别名使 tsc 编译期
// 直接校验请求体与后端 schema 的字段一致性（漂移即编译错）。
export type AgentChatRequest = ChatRequest;

// ===== 项目 =====
export interface Project {
  id: string;
  name: string;
  created_at?: string;
  updated_at?: string;
}
