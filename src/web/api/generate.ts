/**
 * 生成管线 API（图片/视频）
 * 端点：/api/canvas-image-tasks, /api/canvas-video, /api/tasks
 * SSE：按任务定向订阅由 lib/generate-polling.ts 消费 /api/generate/events/{task_id}
 *（fetch + ReadableStream 携带鉴权头；旧 EventSource 版 waitForTaskViaSSE
 * 为无引用死代码，已随任务7/P0 退役删除）
 */
import { apiPost, apiFetch } from './client';
import type { TaskResult } from '@/types';
import type {
  AddGenerationLogResponse,
  BatchImageGenRequest, GenLogRequest, GenerationLogEntry, GenerationLogsResponse,
  ImageGenRequest, VideoGenRequest,
} from '@/types/api.generated';

// ===== 请求体（以生成物为唯一来源；必填收窄与精化字段用交集登记） =====

export type GenerateImageRequest = ImageGenRequest & {
  provider_id: string;
  model: string;
  size: string;
  aspect_ratio: string;
  /** 生成物此处为 Record 粗型，精化为强类型（豁免清单登记） */
  reference_images?: Array<{ url: string; role: string }>;
  draft_id: string;
  draft_type: string;
};

export type GenerateVideoRequest = VideoGenRequest & {
  provider_id: string;
  model: string;
  duration: number;
  resolution: string;
  aspect_ratio: string;
  /** 生成物此处为 Record 粗型，精化为强类型（豁免清单登记） */
  images?: Array<{ url: string; role: string }>;
  /** 视频参考素材（C3：Seedance 2.5 支持 ≤10 段视频参考） */
  videos?: Array<{ url: string; role?: string }>;
  /** 音色参考音频（Seedance MultiModalToVideo 参考项） */
  audios?: Array<{ url: string; role?: string }>;
  draft_id: string;
  draft_type: string;
};

export interface ImageTaskResponse {
  task_id?: string;
  images?: string[];
}

export interface VideoTaskResponse {
  task_id?: string;
  video_url?: string;
  videos?: string[];
  images?: string[];
}

// ===== API 调用 =====

/** 提交生图任务 */
export function submitImageTask(body: GenerateImageRequest) {
  return apiPost<ImageTaskResponse>('/api/canvas-image-tasks', body);
}

/** 查询图片任务状态 */
export function getImageTaskStatus(taskId: string) {
  return apiFetch<TaskResult>(`/api/canvas-image-tasks/${encodeURIComponent(taskId)}`);
}

/** 提交视频生成任务 */
export function submitVideoTask(body: GenerateVideoRequest) {
  return apiPost<VideoTaskResponse>('/api/canvas-video', body);
}

/** 查询视频任务状态 */
export function getVideoTaskStatus(taskId: string) {
  return apiFetch<TaskResult>(`/api/tasks/${encodeURIComponent(taskId)}`);
}

// ===== 处理中任务（刷新后恢复读秒用） =====

export interface ActiveGenTask {
  task_id: string;
  draft_id: string;
  kind: 'image' | 'video';
  created_at: number;
}

/** 查询后端仍在处理中的生成任务（刷新页面后恢复转圈读秒） */
export function getActiveGenTasks() {
  return apiFetch<{ tasks: ActiveGenTask[] }>('/api/generate/active');
}

// ===== 批量生成 =====

/** 生成物字段全可选，前端语义全必填 → Required 收窄 */
export type BatchImageRequest = Required<BatchImageGenRequest>;

export interface BatchImageResponse {
  count?: number;
  detail?: string;
}

/** 批量提交生图任务（左侧面板"批量生成"按钮） */
export function batchImage(body: BatchImageRequest) {
  return apiPost<BatchImageResponse>('/api/generate/batch-image', body);
}

// ===== 生成日志（顶部导航「生成日志」面板） =====

/** 生成日志条目：以后端 GenerationLogEntry 生成物为唯一来源（豁免清单已清偿） */
export type { GenerationLogEntry };

/** 查询生成日志（时间倒序，图/视频/音频无论成败均有记录） */
export function getGenerationLogs(limit = 100) {
  return apiFetch<GenerationLogsResponse>(`/api/generation-logs?limit=${limit}`);
}

/** 前端补录生成日志（如音频规划等未走后端任务通道的生成行为） */
export function addGenerationLog(body: GenLogRequest) {
  return apiPost<AddGenerationLogResponse>('/api/generation-logs', body);
}

// ===== 图片尺寸工具 =====

const IMAGE_1K_SIZES: Record<string, string> = {
  '1:1': '1024x1024',
  '2:3': '1024x1536',
  '3:2': '1536x1024',
  '3:4': '1008x1344',
  '4:3': '1344x1008',
  '9:16': '720x1280',
  '16:9': '1280x720',
  '21:9': '1280x544',
  '9:21': '544x1280',
};

export function imageSizeForRatio(
  ratio: string,
  customWidth = '',
  customHeight = '',
): string {
  if (ratio !== 'custom') return IMAGE_1K_SIZES[ratio] || IMAGE_1K_SIZES['1:1'];
  const w = Number(customWidth);
  const h = Number(customHeight);
  if (!(w > 0) || !(h > 0)) return '';
  const r = w / h;
  const longSide = 1536;
  const pixelLimit = 1572864;
  const rawW = r >= 1 ? longSide : Math.min(longSide * r, Math.sqrt(pixelLimit * r));
  const rawH = r >= 1 ? Math.min(longSide / r, Math.sqrt(pixelLimit / r)) : longSide;
  const width = Math.max(64, Math.floor(rawW / 16) * 16);
  const height = Math.max(64, Math.floor(rawH / 16) * 16);
  return `${width}x${height}`;
}
