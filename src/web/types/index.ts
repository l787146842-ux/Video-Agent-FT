/**
 * FTDYB 全局类型定义
 * 精确匹配后端 API 数据模型（从旧 studio/types.ts 迁移 + 规范化）
 */

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
  /** 当前选中的生成类型（图片/视频/音频生成标签）；缺省时回退 mediaType。
   *  与 mediaType 解耦：切换生成标签不清空已有预览媒体 */
  genType?: MediaType;
  prompt?: string;
  model?: string;
  mode?: string;
  providerId?: string;
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
/**
 * 内联媒体：插入到 Agent 输入框光标处的缩略块。
 * 图片显示缩略图，视频显示首帧，音频显示图标块；均略大于文字、可混排。
 */
export interface InlineMedia {
  id: string;
  name: string;
  url: string;
  kind: MediaType;
  /** 缩略图地址（视频可用首帧；图片缺省即 url） */
  thumb?: string;
}

/**
 * 有序富文本片段：文字与媒体按用户排版顺序交错排列。
 * 原样发送给后端，LLM 据此精确识别「文字 ↔ 媒体」的对应关系。
 */
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
  confirm?: boolean | string;
  appliedActions?: number;
  docCard?: boolean | string;
  /** 回复时使用的模型名称（agent 消息） */
  modelName?: string;
  /** 生图结果图片卡片 */
  imageCard?: ImageCardData;
  /** 用户消息的有序富文本片段（文字 + 内联缩略图交错），用于气泡还原排版 */
  parts?: RichContentPart[];
  /** 本轮已执行操作的中文描述清单（「阶段完成」卡片展开查看具体操作） */
  actionLog?: string[];
  /** 执行轨迹（每轮 step/耗时/操作数，「执行轨迹」折叠区展示） */
  trace?: AgentTrace;
}

/** Agent 执行轨迹（后端 tracer.py 产出） */
export interface TraceAction {
  name: string;
  summary: string;
  elapsed_ms: number;
  ok: boolean;
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
  /** 生成模型/供应商标识 */
  provider?: string;
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

// ===== 工作流 =====
export type PhaseState = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

export interface WorkflowPhaseInfo {
  name: string;
  label: string;
  icon: string;
  state: PhaseState;
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
export interface SseStatusEvent { type: 'status'; text: string; }
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
}
export interface SseDonePayload {
  text: string;
  elapsed_ms: number;
  steps: number;
  applied_actions: number;
  confirmation?: string;
  documents_written?: string[];
  warnings?: string[];
  image_urls?: string[];
  /** Agent 要求插入对话输入框的故事板媒体（insert_chat_media / storyboard_media_to_chat 产出） */
  chat_inserts?: Array<{ kind: MediaType; url: string; name: string; thumb?: string }>;
  /** 本轮已执行操作的中文描述清单（前端展示具体操作内容） */
  action_log?: string[];
  /** 主模型故障时 fallback 实际使用的模型名（供气泡标注） */
  fallback_model?: string;
  /** 执行轨迹（每轮 step/耗时/操作数） */
  trace?: AgentTrace;
  state?: ServerStateSnapshot | null;
}
export interface SseDoneEvent { type: 'done'; payload: SseDonePayload; }
/** 后端 error 事件使用 detail 字段（chat_service.py emit({"type":"error","detail":...})），可携带 error_code 供 i18n 翻译 */
export interface SseErrorEvent { type: 'error'; detail?: string; text?: string; error_code?: string; }
export type SseEvent =
  | SseStatusEvent
  | SseDeltaEvent
  | SseReasoningEvent
  | SseToolStartedEvent
  | SseToolFinishedEvent
  | SseDoneEvent
  | SseErrorEvent;

// ===== 后端状态快照 =====
/** 单个对话（同一项目支持多对话窗口） */
export interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
}

export interface ServerStateSnapshot {
  /** 快照所属项目 ID（持久化请求回传，后端据此丢弃跨项目的过期写入） */
  project_id?: string;
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

// ===== Agent 聊天请求 =====
export interface AgentChatRequest {
  message: string;
  /** 幂等键：后端同 id 处理中时拒绝重复提交 */
  request_id?: string;
  provider?: string;
  model?: string;
  ms_model?: string;
  messages?: Array<{ role: string; content: string }>;
  images?: string[];
  videos?: string[];
  /** 对齐后端 List[Dict[str, str]]：{id, name, url, kind} */
  attachments?: Array<Record<string, string>>;
  /** 有序富文本片段（文字/图片/视频/音频交错），后端据此构建交错多模态内容 */
  content_parts?: RichContentPart[];
  selected_draft_id?: string;
  selected_type?: string;
  context_mode?: string;
  asset_mode?: string;
  /** 本次消息携带的 Skill slug（仅当消息含 Skill 引用块时传，后端记入项目 usedSkills） */
  skill_slug?: string;
  /** 前端当前选中的 Skill 名称（渐进式披露：仅作相关性标注，不注入全文） */
  skill_name?: string;
}

// ===== 项目 =====
export interface Project {
  id: string;
  name: string;
  created_at?: string;
  updated_at?: string;
}
