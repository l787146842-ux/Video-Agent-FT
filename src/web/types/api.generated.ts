/**
 * 自动生成 —— 请勿手工编辑。
 * 来源：FastAPI OpenAPI schema + SSE sidecar（python scripts/gen_api_types.py）
 * 用途：前端 API 边界类型的唯一来源；
 * 视图态类型（ChatMessage 等纯 UI 形态）见手写 src/web/types/index.ts。
 */

export interface ActiveSkillRequest {
  slug: string;
  source?: string;
}

export interface AddGenerationLogResponse {
  ok?: boolean;
  log?: GenerationLogEntry;
}

export interface AgentMetricsResponse {
  traces_count: number;
  avg_turn_ms: number;
  avg_turn_scope: string;
  total_steps: number;
  total_actions: number;
  gate_total: number;
  gate_intercepts: number;
  gate_intercept_rate: number;
  fallback_count: number;
  recent_fallbacks: RecentFallbackItem[];
  unlogged_llm_calls: number;
}

export interface AllCanvasImageItem {
  id: string;
  name: string;
  url: string;
  thumb: string;
  canvas_title: string;
  canvas_kind: string;
}

export interface AllCanvasImagesResponse {
  items: AllCanvasImageItem[];
  canvas_online: boolean;
  canvas_title?: string;
  canvas_kind?: string;
}

export interface AppConfigResponse {
  chat_models: string[];
  image_models: string[];
  video_models: string[];
  canvas_url: string;
  model_fallback_enabled: boolean;
  max_attachments: number;
  infinite_canvas_embed?: InfiniteCanvasEmbedConfig | undefined;
}

export interface AssetPickerItemModel {
  id: string;
  file: string;
  name: string;
  url: string;
  thumb: string;
  kind: string;
  size: number;
  mtime: string;
  created_at: number;
  folder: string;
  category: string;
  tags: string[];
  source: string;
}

export interface AssetPickerResponseModel {
  items: AssetPickerItemModel[];
  canvas_online: boolean;
}

export interface BatchImageGenRequest {
  target?: string;
  provider_id?: string;
  model?: string;
  size?: string;
  aspect_ratio?: string;
}

export interface BoardMergeResponse {
  ok?: boolean;
  applied?: boolean;
  base_available?: boolean;
  board_version?: number | undefined;
  merged?: Record<string, unknown> | undefined;
  conflicts?: Record<string, unknown>[];
}

export interface Body_upload_files_api_ai_upload_post {
  files: string[];
}

export interface BranchRequest {
  title?: string;
}

export interface CanvasDropImageRequest {
  /** 图片 URL（/workspace/assets/... 或绝对 URL） */
  url: string;
  /** 文件名 */
  name?: string;
  /** 目标画布 ID（空则自动推断最近活跃画布） */
  canvas_id?: string;
  /** 落点相对画布 iframe 的屏幕坐标 */
  drop?: DropPoint | undefined;
  /** 画布 iframe 可视尺寸 */
  view?: ViewSize | undefined;
}

export interface CanvasDropImageResponse {
  node_id: string;
  canvas_id: string;
  canvas_title: string;
  image_url: string;
}

export interface CanvasListItem {
  id: string;
  title: string;
  kind: string;
  updated_at: number;
}

export interface CanvasListResponse {
  canvases: CanvasListItem[];
  canvas_online: boolean;
}

export interface CanvasNodeImageItem {
  id: string;
  name: string;
  url: string;
  thumb: string;
  category: string;
}

export interface CanvasNodeImagesResponse {
  items: CanvasNodeImageItem[];
  canvas_online: boolean;
  canvas_title?: string;
}

export interface CanvasSelectNodesRequest {
  /** 要设为选中的画布节点 id 列表 */
  node_ids: string[];
}

export interface CanvasSelectNodesResponse {
  supported: boolean;
  selected: number;
}

export interface ChatRequest {
  message: string;
  request_id?: string;
  conversation_id?: string;
  project_id?: string;
  provider?: string;
  model?: string;
  ms_model?: string;
  messages?: Record<string, string>[];
  images?: string[];
  videos?: string[];
  attachments?: Record<string, string>[];
  content_parts?: Record<string, string>[];
  selected_draft_id?: string;
  selected_type?: string;
  context_mode?: string;
  asset_mode?: string;
  skill_slug?: string;
  skill_name?: string;
  doc_blocks?: string[];
  skill_blocks?: string[];
  gate_overrides?: string[];
  user_id?: string;
  thinking_level?: string;
  pause_response?: Record<string, string>;
  system_action?: string;
  resume_failed?: boolean;
  adjust_scope?: Record<string, unknown> | undefined;
}

export interface ChatResponse {
  text: string;
  applied_actions?: number;
  steps?: number;
  warnings?: string[];
  confirmation?: string;
  pause_id?: string;
  documents_written?: string[];
  image_urls?: string[];
  chat_inserts?: Record<string, unknown>[];
  action_log?: string[];
  state?: Record<string, unknown> | undefined;
  stopped?: boolean;
  stop_phase?: string;
}

export interface CliHelpResponse {
  output: string;
  ok: boolean;
}

export interface CliStatusResponse {
  installed: boolean;
  version: string;
  path: string;
  message: string;
}

export interface ContextBreakdownModel {
  system: number;
  history: number;
  state: number;
  tools: number;
  skill: number;
  total: number;
  budget: number;
}

export interface ContextUsageResponse {
  chars: number;
  est_tokens: number;
  state_chars: number;
  history_chars: number;
  window_tokens: number;
  cache_hit_rate: number;
  cache_sample_count: number;
  cache_prompt_tokens: number;
  cache_cached_tokens: number;
  breakdown?: ContextBreakdownModel | undefined;
}

export interface ConversationMeta {
  id: string;
  title: string;
}

export interface ConversationsMetaResponse {
  conversations: ConversationMeta[];
  active_conversation_id: string;
}

export interface CreateConversationRequest {
  title?: string;
}

export interface DeleteProjectRequest {
  project_id: string;
}

export interface DocumentDelete {
  name: string;
}

export interface DocumentSave {
  name: string;
  content: string;
}

export interface DraftCreate {
  label?: string;
  tag?: string;
  mediaType?: string;
  prompt?: string;
  model?: string;
  mode?: string;
  aspectRatio?: string;
  resolution?: string;
  duration?: string;
  timbre?: string;
  refAssets?: string[];
}

export interface DraftPatch {
  label?: string | undefined;
  tag?: string | undefined;
  prompt?: string | undefined;
  imgUrl?: string | undefined;
  videoUrl?: string | undefined;
  model?: string | undefined;
  mode?: string | undefined;
  aspectRatio?: string | undefined;
  resolution?: string | undefined;
  duration?: string | undefined;
  timbre?: string | undefined;
  refAssets?: string[] | undefined;
}

export interface DropPoint {
  x: number;
  y: number;
}

export interface FetchModelsResponse {
  all?: string[];
  image_models?: string[];
  chat_models?: string[];
  video_models?: string[];
  total?: number;
  protocol?: string;
  error?: string;
}

export interface GenLogRequest {
  media_type: string;
  status: string;
  provider?: string;
  model?: string;
  prompt?: string;
  draft_id?: string;
  error?: string;
  result_url?: string;
  elapsed?: number;
  requested_size?: string;
  source?: string;
}

export interface GenerationLogEntry {
  id?: string;
  task_id?: string;
  media_type?: string;
  status?: string;
  provider?: string;
  provider_name?: string;
  model?: string;
  prompt?: string;
  draft_id?: string;
  error?: string;
  result_url?: string;
  elapsed?: number;
  requested_size?: string;
  source?: string;
  ts?: string;
}

export interface GenerationLogsResponse {
  logs?: GenerationLogEntry[];
}

export interface GroupPatch {
  title?: string | undefined;
  desc?: string | undefined;
  roughDesc?: string | undefined;
  duration?: string | undefined;
  timeRange?: string | undefined;
  shotType?: string | undefined;
  sceneRefs?: string[] | undefined;
  prompt?: string | undefined;
}

export interface GuidanceItem {
  id: string;
  text: string;
}

export interface ImageGenRequest {
  prompt: string;
  provider_id?: string;
  model?: string;
  size?: string;
  aspect_ratio?: string;
  resolution?: string;
  reference_images?: Record<string, string>[];
  draft_id?: string;
  draft_type?: string;
}

export interface InfiniteCanvasEmbedConfig {
  canvas_url: string;
  agent_url: string;
  agent_token: string;
}

export interface JimengCreditResponse {
  ok: boolean;
  text?: string;
  message: string;
}

export interface JimengLoginStartResponse {
  ok: boolean;
  message: string;
  running?: boolean;
}

export interface JimengLoginStatusResponse {
  running: boolean;
  text: string;
  qr_url: string;
}

export interface JimengLogoutResponse {
  ok: boolean;
  message: string;
}

export interface JimengStatusResponse {
  installed: boolean;
  logged_in: boolean;
  version: string;
  path: string;
  raw?: string;
  message: string;
}

export interface ModelFallbackPatch {
  enabled: boolean;
}

export interface NewProjectRequest {
  name?: string;
}

export interface OkResponse {
  ok?: boolean;
  board_version?: number | undefined;
}

export interface OkWithStateResponse {
  ok?: boolean;
  state?: Record<string, unknown> | undefined;
  project_id?: string;
}

export interface PolicyRow {
  provider?: string;
  model?: string;
  thinking_level?: string;
}

export interface ProjectItem {
  id: string;
  name: string;
  created_at?: string;
  updated_at?: string;
}

export interface ProjectListResponse {
  projects?: ProjectItem[];
  active_project_id?: string;
}

export interface ProjectStateResponse {
}

export interface ProjectStateUpdate {
  project_id?: string | undefined;
  base_version?: number | undefined;
  keyElements?: Record<string, unknown>[] | undefined;
  shots?: Record<string, unknown>[] | undefined;
  audioItems?: Record<string, unknown>[] | undefined;
  assets?: Record<string, unknown>[] | undefined;
  chatMessages?: Record<string, unknown>[] | undefined;
}

export interface ProviderProbeRequest {
  base_url?: string;
  api_key?: string;
  provider_id?: string;
  protocol?: string;
  image_request_mode?: string;
}

export interface ProvidersResponse {
  providers?: Record<string, unknown>[];
  canvas_online?: boolean;
}

export interface RecentFallbackItem {
  ts: number;
  provider: string;
  model: string;
}

export interface ReorderRequest {
  category: string;
  group_ids: string[];
}

export interface RuntimeSettings {
  model_fallback_enabled: boolean;
  chat_image_enabled: boolean;
  default_image_provider_id: string;
  default_image_model: string;
  default_video_provider_id: string;
  default_video_model: string;
  default_image_resolution: string;
  default_video_resolution: string;
  max_shot_duration: number;
  llm_max_tokens: number;
  skills_disabled: string[];
  script_inject_limit: number;
  execution_preference: string;
  execution_mode: string;
  model_policy: Record<string, PolicyRow>;
}

export interface RuntimeSettingsUpdate {
  model_fallback_enabled?: boolean | undefined;
  chat_image_enabled?: boolean | undefined;
  default_image_provider_id?: string | undefined;
  default_image_model?: string | undefined;
  default_video_provider_id?: string | undefined;
  default_video_model?: string | undefined;
  default_image_resolution?: string | undefined;
  default_video_resolution?: string | undefined;
  max_shot_duration?: number | undefined;
  llm_max_tokens?: number | undefined;
  skills_disabled?: string[] | undefined;
  script_inject_limit?: number | undefined;
  execution_preference?: string | undefined;
  execution_mode?: string | undefined;
  model_policy?: Record<string, unknown> | undefined;
}

export interface SkillAssistantMessage {
  role: string;
  content: string;
}

export interface SkillAssistantRequest {
  content: string;
  messages?: SkillAssistantMessage[];
  provider?: string;
  model?: string;
}

export interface SkillDoc {
  slug: string;
  name: string;
  description?: string;
  content?: string;
}

export interface SkillDocHistoryResponse {
  versions?: SkillDocVersion[];
}

export interface SkillDocSave {
  content: string;
}

export interface SkillDocVersion {
  version: string;
  content: string;
}

export interface SkillDocsResponse {
  docs?: SkillDoc[];
}

export interface SkillFormatRequest {
  content: string;
}

export interface SnapshotActionRequest {
  snapshot_id: string;
  name?: string;
}

export interface SnapshotItem {
  id: string;
  ts?: string;
  label?: string;
}

export interface SnapshotListResponse {
  snapshots?: SnapshotItem[];
}

export interface SnapshotRequest {
  up_to_index?: number | undefined;
  pinned?: boolean;
}

export interface SwitchProjectRequest {
  project_id: string;
}

export interface TestConnectionResponse {
  ok?: boolean;
  status?: number;
  protocol?: string;
  message?: string;
  model_count?: number;
  all?: string[];
  image_models?: string[];
  chat_models?: string[];
  video_models?: string[];
  image_request_mode?: string;
}

export interface ThreadRequest {
  scope?: Record<string, string>;
}

export interface ThreadUnrefRequest {
  conversation_id: string;
  ref_id: string;
}

export interface TimelinePushRequest {
  shot_group_id?: string;
  canvas_id?: string;
}

export interface TruncateResendRequest {
  text?: string | undefined;
  provider?: string | undefined;
  model?: string | undefined;
  thinking_level?: string | undefined;
  conversation_id?: string;
}

export interface UndoStatusResponse {
  can_undo: boolean;
  can_redo: boolean;
}

export interface VideoBatchCreate {
  provider_id?: string;
  model?: string;
  resolution?: string;
  duration?: number;
  shot_group_ids?: string[] | undefined;
}

export interface VideoGenRequest {
  prompt: string;
  provider_id?: string;
  model?: string;
  duration?: number;
  resolution?: string;
  aspect_ratio?: string;
  images?: Record<string, string>[];
  videos?: Record<string, string>[];
  audios?: Record<string, string>[];
  enhance_prompt?: boolean;
  multimodal?: boolean;
  draft_id?: string;
  draft_type?: string;
}

export interface ViewSize {
  width: number;
  height: number;
}

// ===== SSE 事件载荷（sidecar：src/web/types/sse.schema.json）=====

export interface SseStatusEvent {
  type: 'status';
  text?: string;
  key?: string;
  params?: Record<string, string | number>;
}

export interface SseDeltaEvent {
  type: 'delta';
  text?: string;
}

export interface SseReasoningDeltaEvent {
  type: 'reasoning_delta';
  text?: string;
}

export interface SseToolStartedEvent {
  type: 'tool_started';
  id: string;
  name: string;
  summary: string;
  args?: Record<string, unknown> | undefined;
  detail_md?: string | undefined;
}

export interface SseToolFinishedEvent {
  type: 'tool_finished';
  id: string;
  ok: boolean;
  elapsed_ms: number;
  result_summary?: string;
  detail_md?: string | undefined;
  planning?: boolean | undefined;
}

export interface SseDocWrittenEvent {
  type: 'doc_written';
  name?: string;
  turn_id?: string | undefined;
}

export interface SseActionsAppliedEvent {
  type: 'actions_applied';
  count?: number | undefined;
  step?: number | undefined;
  payload?: Record<string, unknown> | undefined;
}

export interface SseStoppedInflightItem {
  task_id?: string;
  media_type?: string;
  model?: string;
  draft_id?: string;
  summary?: string;
}

export interface SseStoppedEvent {
  type: 'stopped';
  phase?: string;
  step?: number | undefined;
  inflight?: SseStoppedInflightItem[] | undefined;
}

export interface SseModelFallbackEvent {
  type: 'model_fallback';
  provider?: string;
  model?: string;
}

export interface SseErrorEvent {
  type: 'error';
  detail?: string | undefined;
  text?: string | undefined;
  raw?: string | undefined;
  error_code?: string | undefined;
  code?: string;
  kind?: string;
  message?: string;
}

export interface SseGuidanceInjectedEvent {
  type: 'guidance_injected';
  id?: string;
  text?: string;
}

export interface SseDoneChatInsert {
  kind?: string;
  url?: string;
  name?: string;
  thumb?: string;
}

export interface SseDoneConfirmationOption {
  label?: string;
  description?: string;
  group?: string;
  value?: string;
}

export interface SseDoneSuggestedAction {
  kind?: string;
  label?: string;
  value?: string;
}

export interface SseDonePayload {
  text?: string;
  applied_actions?: number;
  steps?: number;
  warnings?: string[];
  confirmation?: string;
  pause_id?: string;
  documents_written?: string[];
  image_urls?: string[];
  chat_inserts?: SseDoneChatInsert[];
  action_log?: string[];
  confirmation_options?: SseDoneConfirmationOption[];
  suggested_actions?: SseDoneSuggestedAction[];
  pause_kind?: string;
  snapshot_id?: string;
  stopped?: boolean;
  stop_phase?: string;
  fallback_model?: string | undefined;
  elapsed_ms?: number | undefined;
  turn_id?: string | undefined;
  state?: Record<string, unknown> | undefined;
  trace?: Record<string, unknown> | undefined;
  workflow?: Record<string, unknown> | undefined;
}

export interface SseDoneEvent {
  type: 'done';
  payload?: SseDonePayload;
}

export interface AgentTaskToolEntry {
  id?: string;
  name?: string;
  summary?: string;
  args?: Record<string, unknown> | undefined;
  status?: string;
  elapsed_ms?: number | undefined;
  result_summary?: string;
  planning?: boolean | undefined;
  started_at_ms?: number | undefined;
}

export interface AgentTaskReplayPayload {
  task_id?: string;
  project_id?: string;
  model?: string;
  status?: string;
  status_text?: string;
  reasoning?: string;
  text?: string;
  tools?: AgentTaskToolEntry[];
  snapshot?: Record<string, unknown> | undefined;
  done_payload?: Record<string, unknown> | undefined;
  stopped_payload?: Record<string, unknown> | undefined;
  docs?: string[];
  wf_event_sequence?: number;
  workflow?: Record<string, unknown> | undefined;
  fallback?: Record<string, unknown> | undefined;
  error?: string | undefined;
  error_payload?: Record<string, unknown> | undefined;
}

export interface SseReplayEvent {
  type: 'replay';
  payload?: AgentTaskReplayPayload;
}

export interface SseTaskStatusEvent {
  type: 'task_status';
  status?: string;
}

/** SSE 事件联合类型（判别列 = type 字面量；后端帧模型自动生成） */
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

// ===== 错误语义契约（来源：web/error_payload.py，sidecar 导出）=====

export interface ErrorPayloadContract {
  code: string;
  kind: string;
  message: string;
  raw?: string;
}

/** 错误归类封闭集合（后端 ALL_KINDS 生成，改动自动同步） */
export const SSE_ERROR_KINDS = ['auth', 'quota', 'network', 'upstream', 'content', 'unknown'] as const;
export type SseErrorKind = (typeof SSE_ERROR_KINDS)[number];
/** legacy error_code → kind/code 桥接表（后端 LEGACY_CODE_MAP 生成） */
export const SSE_LEGACY_ERROR_CODES: Record<string, { kind: SseErrorKind; code: string }> = {
  ADAPTER_ERROR: { kind: 'upstream', code: 'err.upstream.server_error' },
  FETCH_ERROR: { kind: 'network', code: 'err.network.connection' },
  FORBIDDEN_ORIGIN: { kind: 'auth', code: 'err.auth.forbidden_origin' },
  GENERATION_ERROR: { kind: 'upstream', code: 'err.upstream.server_error' },
  NETWORK_ERROR: { kind: 'network', code: 'err.network.connection' },
  PROBE_HTTP_ERROR: { kind: 'upstream', code: 'err.upstream.server_error' },
  PROBE_TIMEOUT: { kind: 'network', code: 'err.network.timeout' },
  RATE_LIMITED: { kind: 'quota', code: 'err.quota.rate_limited' },
  TIMEOUT: { kind: 'network', code: 'err.network.timeout' },
  UNAUTHORIZED: { kind: 'auth', code: 'err.auth.invalid_key' },
  VIDEO_CONNECT_ERROR: { kind: 'network', code: 'err.network.connection' },
  VIDEO_HTTP_ERROR: { kind: 'upstream', code: 'err.upstream.server_error' },
  VIDEO_SUBMIT_FAILED: { kind: 'upstream', code: 'err.upstream.server_error' },
  VIDEO_TIMEOUT: { kind: 'network', code: 'err.network.timeout' },
};

// ===== 工具时间线展示档（来源：各工具 detail_tier 声明，sidecar 导出）=====

/** 工具名 → 展示档（expand=展开输入+结果 / output=仅输出留痕） */
export const TOOL_DETAIL_TIERS: Record<string, 'expand' | 'output'> = {
  canvas_add_node: 'expand',
  canvas_batch_add_nodes: 'expand',
  canvas_delete_node: 'output',
  canvas_list: 'output',
  canvas_list_assets: 'output',
  canvas_read_nodes: 'output',
  canvas_update_node: 'expand',
  document_write: 'expand',
  generate_video: 'expand',
  get_skill_asset: 'output',
  image_generate: 'expand',
  list_skills: 'output',
  mcp_tool_catalog: 'output',
  read_draft: 'output',
  read_project_doc: 'output',
  read_skill: 'output',
  read_state_group: 'output',
  read_uploaded_doc: 'output',
  run_subagent: 'expand',
  script_analysis_report: 'expand',
  storyboard_add_draft: 'expand',
  storyboard_confirm_draft: 'output',
  storyboard_create_group: 'expand',
  storyboard_delete_group: 'output',
  storyboard_media_to_chat: 'output',
  storyboard_patch_draft: 'expand',
  view_storyboard_media: 'output',
  workflow_pause: 'expand',
};
/** 未登记工具/未知名的默认档（新工具至少留输出痕迹） */
export const TOOL_DETAIL_TIER_DEFAULT = 'output' as const;
/** 非工具内部条目（恒定 none，不经元数据） */
export const TOOL_DETAIL_INTERNAL_NONE: readonly string[] = ['model_reasoning'] as const;

// ===== 工具审批分级档（来源：各工具 approval_tier 声明/推导，sidecar 导出）=====

/** 工具名 → 生效审批档（none=无需审批 / confirm=执行前确认卡 / review=人工审批复核） */
export const TOOL_APPROVAL_TIERS: Record<string, 'none' | 'confirm' | 'review'> = {
  canvas_add_node: 'none',
  canvas_batch_add_nodes: 'none',
  canvas_delete_node: 'none',
  canvas_list: 'none',
  canvas_list_assets: 'none',
  canvas_read_nodes: 'none',
  canvas_update_node: 'none',
  document_write: 'none',
  generate_video: 'confirm',
  get_skill_asset: 'none',
  image_generate: 'confirm',
  list_skills: 'none',
  mcp_tool_catalog: 'none',
  read_draft: 'none',
  read_project_doc: 'none',
  read_skill: 'none',
  read_state_group: 'none',
  read_uploaded_doc: 'none',
  run_subagent: 'none',
  script_analysis_report: 'none',
  storyboard_add_draft: 'none',
  storyboard_confirm_draft: 'none',
  storyboard_create_group: 'none',
  storyboard_delete_group: 'none',
  storyboard_media_to_chat: 'none',
  storyboard_patch_draft: 'none',
  view_storyboard_media: 'none',
  workflow_pause: 'none',
};
/** 未登记工具的默认档（high risk 口径，deny-by-default） */
export const TOOL_APPROVAL_TIER_DEFAULT = 'confirm' as const;

// ===== 执行偏好三档（来源：config.py 白名单枚举，sidecar 导出）=====

/** 执行偏好三档枚举（花钱生成动作是否先弹确认卡） */
export const EXECUTION_PREFERENCE_VALUES = ['auto_decide', 'confirm_before_gen', 'generate_directly'] as const;
export type ExecutionPreference = (typeof EXECUTION_PREFERENCE_VALUES)[number];
/** 默认档（= 现状行为：每次花钱生成前弹确认卡） */
export const EXECUTION_PREFERENCE_DEFAULT = 'confirm_before_gen' as const;

// ===== 执行模式四档（来源：config.py 白名单枚举，sidecar 导出）=====

/** 执行模式四档枚举（流程推进的暂停策略） */
export const EXECUTION_MODE_VALUES = ['ai_decide', 'auto_full', 'key_steps_confirm', 'pause_all'] as const;
export type ExecutionMode = (typeof EXECUTION_MODE_VALUES)[number];
/** 默认档（= 现状行为：停不停由模型按 Skill 散文与当场情况判断） */
export const EXECUTION_MODE_DEFAULT = 'ai_decide' as const;
