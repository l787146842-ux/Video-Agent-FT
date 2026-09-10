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
 * - ServerStateSnapshot / ChatMessage / Draft 等视图态：前端渲染形态，非 API 模型；
 * - 手写响应类型比生成物更精确的站点（生成物对 Dict 响应只能给出
 *   Record<string, unknown>）：ProvidersResponse/OkWithStateResponse
 *   （api/providers.ts、api/project.ts）、ChatResponse、
 *   画布选中节点族 CanvasSelectionNode/CanvasSelectionResult（api/canvas.ts，
 *   后端 /canvas/selection 未建模：节点 metadata 为外部画布动态数据，
 *   严格建模需 Dict[str, Any] 粗型，契约 phase1 裁决保留手写）、
 *   整板保存 payload（stores/studio/storyboard.ts，后端 ProjectStateUpdate 五列表
 *   已收窄为 Record<string, unknown>[] 但元素仍宽于手写 Draft/Group/Asset）
 *   ——保留手写强类型：整板保存条目随 D-06 专项清偿后删（docs/未清偿债务清单.md）；
 *   ProvidersResponse/OkWithStateResponse/ChatResponse 后端建模代价过大，
 *   任务 #10 裁决保留（2026-08-28），后端全量建模后再迁。
 *   （画布读取结果族 CanvasDropImageResult/CanvasNodeImagesResult/
 *   AllCanvasImagesResult 及 context-usage/metrics/cli 状态族/config/asset-picker
 *   手抄镜像已随契约 phase1 清偿：后端补 response_model，前端改生成物别名）
 * - 生成物消费基座站点（生成物为类型来源，手写只做收窄/精化，  登记）：
 *   GenerateImageRequest/GenerateVideoRequest（交集精化，api/generate.ts）、
 *   BatchImageRequest（Required 收窄必填）、CanvasDropImagePayload（交集精化，api/canvas.ts）、
 *   SSE 事件族（sidecar 生成帧为来源，本文件仅收窄 state/trace/
 *   workflow 等视图态字段并组装 SseEvent 联合）。
 * - 前端无消费路径的生成物（后端端点专用/前端走通用端点）：ModelFallbackPatch
 *   （前端开关走通用 runtime PUT）、TimelinePushRequest（时间线回画布走 Agent
 *   工具路径）、Body_upload_files_api_ai_upload_post（multipart 上传）、
 *   DraftCreate/DraftPatch/GroupPatch（草稿操作走整板保存通道）、ProjectStateResponse（空 schema）、
 *   ThreadRequest（微调真子对话线程接口，前端消费方批 S3 接入）。
 */
import type {
  ChatRequest,
  AgentTaskReplayPayload as GenAgentTaskReplayPayload,
  AgentTaskToolEntry,
  ConversationMeta,
  ProjectItem,
  SseActionsAppliedEvent as GenSseActionsAppliedEvent,
  SseDeltaEvent,
  SseDocWrittenEvent,
  SseDoneChatInsert,
  SseDoneConfirmationOption,
  SseDonePayload as GenSseDonePayload,
  SseDoneSuggestedAction,
  SseErrorEvent,
  SseGuidanceInjectedEvent,
  SseModelFallbackEvent,
  SseReasoningDeltaEvent,
  SseStatusEvent,
  SseStoppedEvent as GenSseStoppedEvent,
  SseStoppedInflightItem,
  SseTaskStatusEvent,
  SseToolFinishedEvent,
  SseToolStartedEvent,
} from './api.generated';
import type { ErrorKind } from '@/lib/error-payload';
import type { TurnLedger } from '@/lib/turn-ledger';

// ===== 基础枚举 =====
export type DraftType = 'keyElement' | 'shot' | 'audio';
export type MediaType = 'image' | 'video' | 'audio';
export type LeftTab = 'storyboard' | 'uncategorized' | 'subagents';
export type SubTab = 'keyElements' | 'shots' | 'audio';

// ===== 草稿 / 分组 =====
export interface Draft {
  id: string;
  label: string;
  /** 卡片描述（批 1 · A2）：角色（年龄/外貌/服装）、场景（空间/材质/光源/氛围）等 */
  desc?: string;
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
/** 模型编辑面板配置（chat_models_meta 条目，按模型名精确匹配） */
export interface ChatModelMeta {
  model: string;
  /** 上下文窗口（token 数；三挡 200K/400K/1M，未配置回落平台默认挡） */
  context_window?: number;
  /** 思考模式开关（默认开；关闭后平台不发任何思考参数） */
  thinking_enabled?: boolean;
  /** 推理档位（''=原生 / low / medium / high；开关开且未选档 → enable_thinking） */
  thinking_level?: string;
}

export interface ApiProvider {
  id: string;
  name: string;
  protocol?: string;
  base_url?: string;
  enabled?: boolean;
  chat_models?: string[];
  image_models?: string[];
  video_models?: string[];
  /** 模型级配置（编辑面板写入；后端查窗口与思考参数用） */
  chat_models_meta?: ChatModelMeta[];
  [key: string]: unknown;
}

// ===== Skill =====
export interface Skill {
  id: string;
  name: string;
  system_prompt?: string;
  description?: string;
  /** 规划级执行器名单（后端 capability 注册表下发） */
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
  /** 视频结果内联预览卡（首帧 poster + ▶ 角标，点击 lightbox 播放/下载） */
  videoCard?: VideoCardData;
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
  /** 结构化决策表单（workflow pending_decision schema→表单数据驱动；
   *  提交走既有暂停回应/消息通道，留痕同普通用户消息） */
  decisionForm?: PendingDecisionPayload;
  /** 模型降级等警示行（常驻展示在 agent 气泡上，刷新后仍可见） */
  warnings?: string[];
  /** 执行轨迹（每轮 step/耗时/操作数，「执行轨迹」折叠区展示） */
  trace?: AgentTrace;
  /** 轮次账本（F2 阶段一：finishStream 相位翻转后的 live 账本快照，仅前端本地；
   *  不随后端持久化——刷新/历史重建回落 ledgerFromSettled(trace) 同一归一入口） */
  ledger?: TurnLedger;
  /** ：鉴权/供应商类错误气泡附「检查 API 配置」跳转按钮 */
  settingsHint?: boolean;
  /** 错误结构化归类（ErrorPayload.kind；渲染层按映射表扩展 affordance） */
  errorKind?: ErrorKind;
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
  /** E1 消息级快照指针（后端轮末打快照挂最后一条 agent 消息；
   *  有值即可挂「回到此刻/从此刻新开项目」动作） */
  snapshotId?: string;
  pauseAnsweredValue?: string;
  /** 消息形态标记（system_action=系统动作行；其余为暂停卡语义种类，
   *  源自后端 pause_kind） */
  kind?: 'system_action' | 'remind' | 'collect' | 'stage_done' | 'confirm';
  /** 本地产生时刻（epoch ms，悬停工具条 HH:MM 展示）；
   *  后端持久化消息无此字段 → 工具条不显示时间 */
  ts?: number;
}

/** Agent 执行轨迹（后端 tracer.py 产出） */
export interface TraceAction { name: string; summary: string; elapsed_ms: number; ok: boolean; /** 大阶段标签（后端权威下发） */ stage?: string; /** 工具执行结果一句话摘要（与 SSE tool_finished 同口径） */ result_summary?: string; /** 事件卡折叠区全文（后端 emit_event_card 下发，仅 event_card 携带） */ detail_md?: string; /** 规划级执行器标记（capability 注册表下发） */ planning?: boolean; /** 工具输入参数预览（后端裁剪脱敏，详情卡展开区用） */ args?: Record<string, unknown>; }
/** 闸机判定明细（后端 tracer.record_gate 产出，前端按结构渲染来源标注 chips） */
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

// ===== 视频结果内联预览卡（done payload chat_inserts 中 kind=video 项） =====
export interface VideoCardItem {
  url: string;
  name?: string;
  /** 首帧缩略图（poster） */ thumb?: string;
}
export interface VideoCardData {
  items: VideoCardItem[];
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
}

// ===== 结构化决策表单（workflow pending_decision 投影契约） =====
/** 决策表单单字段（数据驱动：产出侧写入 schema.fields 即渲染，
 *  「几个分镜？画幅选哪个？」类多字段参数决策） */
export interface DecisionFormField {
  key: string;
  label?: string;
  /** 缺省按 text 渲染 */
  type?: 'text' | 'number' | 'select';
  /** select 类型的候选项 */
  options?: Array<{ label: string; value?: string }>;
  default?: string | number;
  placeholder?: string;
  required?: boolean;
}
/** 决策 schema（后端 pending_decision.schema 原样透传，表单由 fields 派生） */
export interface DecisionFormSchema {
  type?: string;
  title?: string;
  description?: string;
  required?: boolean;
  fields?: DecisionFormField[];
}
/** 待决决策完整结构（后端 workflow 投影 pending_decision_payload；
 *  DecisionRequest 五元组：token/node_id/message/schema/options） */
export interface PendingDecisionPayload {
  token?: string;
  node_id?: string;
  message?: string;
  schema?: DecisionFormSchema;
  options?: Array<{ label?: string; value?: string }>;
}
/** workflow 投影（后端 workflow_runtime.project 产出；done 载荷/replay 同源） */
export interface WorkflowProjection {
  run_id?: string;
  status?: string;
  current_node?: string;
  completed_nodes?: string[];
  event_sequence?: number;
  pending_decision?: boolean;
  /** 结构化决策表单数据源（无挂起决策时缺省） */
  pending_decision_payload?: PendingDecisionPayload | null;
  turn_events?: Array<Record<string, unknown>>;
}

// ===== SSE 事件（Agent 聊天流；契约生成化） =====
// 契约锚点：事件帧以生成物（sidecar：sse.schema.json ← core/sse_events.py
// TS_EVENT_FRAMES）为唯一来源；本段只做视图态收窄（state/trace/workflow 等
// 生成物只能给 Record<string, unknown> 的字段精化为前端渲染形态）。
export type {
  AgentTaskToolEntry,
  SseDeltaEvent,
  SseDocWrittenEvent,
  SseDoneChatInsert,
  SseDoneConfirmationOption,
  SseDoneSuggestedAction,
  SseErrorEvent,
  SseGuidanceInjectedEvent,
  SseModelFallbackEvent,
  SseReasoningDeltaEvent,
  SseStatusEvent,
  SseStoppedInflightItem,
  SseTaskStatusEvent,
  SseToolFinishedEvent,
  SseToolStartedEvent,
};

/** 停止终态事件：phase 收窄为后端三阶段字面量（气泡措辞分支依据） */
export type SseStoppedEvent = Omit<GenSseStoppedEvent, 'phase'> & {
  phase?: 'thinking' | 'tool_executing' | 'streaming';
};
/** 操作已执行：payload.state 收窄为状态快照（推理中逐步刷新故事板） */
export type SseActionsAppliedEvent = Omit<GenSseActionsAppliedEvent, 'payload'> & {
  payload?: { count?: number; state?: ServerStateSnapshot | null };
};
/** done 载荷：账本四件套收窄必填；state/trace/workflow 收窄视图态 */
export type SseDonePayload = Omit<GenSseDonePayload,
  'text' | 'elapsed_ms' | 'steps' | 'applied_actions'
  | 'chat_inserts' | 'confirmation_options' | 'suggested_actions'
  | 'trace' | 'state' | 'workflow'> & {
  text: string;
  elapsed_ms: number;
  steps: number;
  applied_actions: number;
  chat_inserts?: Array<{ kind: MediaType; url: string; name: string; thumb?: string }>;
  confirmation_options?: Array<{ label: string; description?: string; group?: string; value?: string }>;
  suggested_actions?: Array<{ kind: 'retry' | 'continue' | 'next'; label: string; value: string }>;
  trace?: AgentTrace;
  state?: ServerStateSnapshot | null;
  workflow?: WorkflowProjection | null;
};
export interface SseDoneEvent { type: 'done'; payload: SseDonePayload; }
/** 任务式传输 replay 快照：嵌套载荷收窄为上述视图态类型 */
export type AgentTaskReplayPayload = Omit<GenAgentTaskReplayPayload,
  'snapshot' | 'done_payload' | 'stopped_payload' | 'workflow' | 'fallback' | 'error_payload'> & {
  snapshot?: ServerStateSnapshot | null;
  done_payload?: SseDonePayload | null;
  /** 停止终态事件负载（status=stopped 时携带，刷新后恢复停止痕迹） */
  stopped_payload?: SseStoppedEvent | null;
  workflow?: WorkflowProjection | null;
  fallback?: { provider?: string; model?: string } | null;
  /** 错误结构化归类（replay 同源下发；旧记录无此字段时为 null） */
  error_payload?: { code?: string; kind?: string; raw?: string } | null;
};
export interface SseReplayEvent { type: 'replay'; payload?: AgentTaskReplayPayload; }
/** 前端事件联合（成员 = 生成物帧；收窄版替换同名生成帧） */
export type SseEvent =
  | SseStatusEvent
  | SseDeltaEvent
  | SseReasoningDeltaEvent
  | SseToolStartedEvent
  | SseToolFinishedEvent
  | SseDocWrittenEvent
  | SseActionsAppliedEvent
  | SseStoppedEvent
  | SseModelFallbackEvent
  | SseErrorEvent
  | SseGuidanceInjectedEvent
  | SseDoneEvent
  | SseReplayEvent
  | SseTaskStatusEvent;

// ===== 后端状态快照 =====
/** 单个对话（同一项目支持多对话窗口）：仅元信息（E-2 消息单一来源，
 * 消息唯一存于 chat store；装载走 GET /conversations/{id}/messages 或快照 chatMessages）。
 * 以后端 ConversationMeta 生成物为唯一来源（标签栏形态 = 后端元信息同形） */
export type Conversation = ConversationMeta;

/** 子代理隐藏线程（B3 左栏子任务卡）：后端 GET /conversations/subagents 返回。 */
export interface SubagentThread {
  conversation_id: string;
  title: string;
  /** 任务摘要（scope.label，截断后的委派文本） */
  label: string;
  parent_conversation: string;
  /** running=事件流未闭合；completed=已落 turn/end；unknown=读不到事件流 */
  status: 'running' | 'completed' | 'unknown' | string;
  /** 子级 assistant 响应步数 */
  steps: number;
}

/** 子代理只读执行记录条目：后端 GET /conversations/subagents/{id}/record 返回
 *（事件流派生，形状对齐 chatMessages entry 的子集）。 */
export interface SubagentRecordMessage {
  sender: 'user' | 'assistant';
  text?: string;
  ts?: number;
  reasoning_content?: string;
  actionLog?: string[];
}

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
  /** 项目态活跃 Skill 绑定（批 C）：slug 空串 = 显式自由对话；
   * 未登记过绑定的存量项目无此键（前端回落 usedSkills 旧口径） */
  activeSkill?: { slug: string; source: 'user' | 'suggested' } | null;
  /** 多对话列表（仅元信息，E-2）；活跃对话消息由顶层 chatMessages 携带 */
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
/** 项目索引条目：以后端 ProjectItem 生成物为唯一来源（项目列表形态同形） */
export type Project = ProjectItem;
