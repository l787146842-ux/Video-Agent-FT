/**
 * 自动生成 —— 请勿手工编辑。
 * 来源：FastAPI OpenAPI schema（python scripts/gen_api_types.py）
 * 用途：前端 API 边界类型的唯一来源；
 * 视图态类型（ChatMessage 等纯 UI 形态）见手写 src/web/types/index.ts。
 */

export interface BatchImageGenRequest {
  target?: string;
  provider_id?: string;
  model?: string;
  size?: string;
  aspect_ratio?: string;
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
  drop?: DropPoint | unknown;
  /** 画布 iframe 可视尺寸 */
  view?: ViewSize | unknown;
}

export interface ChatRequest {
  message: string;
  system_prompt?: string;
  request_id?: string;
  provider?: string;
  model?: string;
  ms_model?: string;
  messages?: Record<string, unknown>[];
  images?: string[];
  videos?: string[];
  attachments?: Record<string, unknown>[];
  content_parts?: Record<string, unknown>[];
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
  pause_response?: Record<string, unknown>;
  system_action?: string;
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
  state?: Record<string, unknown> | unknown;
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
  label?: string | unknown;
  tag?: string | unknown;
  prompt?: string | unknown;
  imgUrl?: string | unknown;
  videoUrl?: string | unknown;
  model?: string | unknown;
  mode?: string | unknown;
  aspectRatio?: string | unknown;
  resolution?: string | unknown;
  duration?: string | unknown;
  timbre?: string | unknown;
  refAssets?: string[] | unknown;
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

export interface GroupPatch {
  title?: string | unknown;
  desc?: string | unknown;
  roughDesc?: string | unknown;
  duration?: string | unknown;
  timeRange?: string | unknown;
  shotType?: string | unknown;
  sceneRefs?: string[] | unknown;
  prompt?: string | unknown;
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
  reference_images?: Record<string, unknown>[];
  draft_id?: string;
  draft_type?: string;
}

export interface ModelFallbackPatch {
  enabled: boolean;
}

export interface NewProjectRequest {
  name?: string;
}

export interface OkResponse {
  ok?: boolean;
  board_version?: number | unknown;
}

export interface OkWithStateResponse {
  ok?: boolean;
  state?: Record<string, unknown> | unknown;
  project_id?: string;
}

export interface PinBody {
  pinned?: boolean;
}

export interface ProjectListResponse {
  projects?: Record<string, unknown>[];
  active_project_id?: string;
}

export interface ProjectStateResponse {
}

export interface ProjectStateUpdate {
  project_id?: string | unknown;
  base_version?: number | unknown;
  keyElements?: unknown[] | unknown;
  shots?: unknown[] | unknown;
  audioItems?: unknown[] | unknown;
  assets?: unknown[] | unknown;
  chatMessages?: unknown[] | unknown;
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

export interface ReorderRequest {
  category: string;
  group_ids: string[];
}

export interface RuntimeSettingsUpdate {
  model_fallback_enabled?: boolean | unknown;
  chat_image_enabled?: boolean | unknown;
  default_image_provider_id?: string | unknown;
  default_image_model?: string | unknown;
  default_video_provider_id?: string | unknown;
  default_video_model?: string | unknown;
  default_image_resolution?: string | unknown;
  default_video_resolution?: string | unknown;
  max_shot_duration?: number | unknown;
  script_inject_limit?: number | unknown;
  model_policy?: Record<string, unknown> | unknown;
}

export interface SkillDocSave {
  content: string;
}

export interface SkillFormatRequest {
  content: string;
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

export interface TimelinePushRequest {
  shot_group_id?: string;
  canvas_id?: string;
}

export interface UndoStatusResponse {
  can_undo?: boolean;
  can_redo?: boolean;
}

export interface VideoBatchCreate {
  provider_id?: string;
  model?: string;
  resolution?: string;
  duration?: number;
  shot_group_ids?: string[] | unknown;
}

export interface VideoGenRequest {
  prompt: string;
  provider_id?: string;
  model?: string;
  duration?: number;
  resolution?: string;
  aspect_ratio?: string;
  images?: Record<string, unknown>[];
  videos?: Record<string, unknown>[];
  audios?: Record<string, unknown>[];
  enhance_prompt?: boolean;
  multimodal?: boolean;
  draft_id?: string;
  draft_type?: string;
}

export interface ViewSize {
  width: number;
  height: number;
}
