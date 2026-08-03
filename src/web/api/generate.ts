/**
 * 生成管线 API（图片/视频）
 * 端点：/api/canvas-image-tasks, /api/canvas-video, /api/tasks
 * SSE：/api/generate/events
 */
import { apiPost, apiFetch } from './client';
import type { TaskResult } from '@/types';

// ===== 请求体 =====

export interface GenerateImageRequest {
  prompt: string;
  provider_id: string;
  model: string;
  size: string;
  aspect_ratio: string;
  reference_images?: Array<{ url: string; role: string }>;
  draft_id: string;
  draft_type: string;
}

export interface GenerateVideoRequest {
  prompt: string;
  provider_id: string;
  model: string;
  duration: number;
  resolution: string;
  aspect_ratio: string;
  images?: Array<{ url: string; role: string }>;
  enhance_prompt?: boolean;
  multimodal?: boolean;
  draft_id: string;
  draft_type: string;
}

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

// ===== 批量生成 =====

export interface BatchImageRequest {
  /** "all_keyElements" / "all_shots" / 逗号分隔的 draft_id */
  target: string;
  provider_id: string;
  model: string;
  size: string;
  aspect_ratio: string;
}

export interface BatchImageResponse {
  count?: number;
  detail?: string;
}

/** 批量提交生图任务（左侧面板"批量生成"按钮） */
export function batchImage(body: BatchImageRequest) {
  return apiPost<BatchImageResponse>('/api/generate/batch-image', body);
}

// ===== SSE 任务等待 =====

/**
 * 通过 EventSource 等待指定任务完成
 * 超时或连接失败返回 null（调用方降级为轮询）
 */
export function waitForTaskViaSSE(
  taskId: string,
  timeoutSec: number,
): Promise<TaskResult | null> {
  return new Promise((resolve) => {
    let resolved = false;
    const timer = setTimeout(() => { cleanup(); resolve(null); }, timeoutSec * 1000);

    let es: EventSource | null = null;
    try {
      es = new EventSource('/api/generate/events');
    } catch {
      clearTimeout(timer);
      resolve(null);
      return;
    }

    function cleanup() {
      if (es) { es.close(); es = null; }
      clearTimeout(timer);
    }

    es.onmessage = (event: MessageEvent) => {
      if (resolved) return;
      try {
        const data = JSON.parse(event.data);
        if (data.task_id === taskId) {
          resolved = true;
          cleanup();
          resolve(data as TaskResult);
        }
      } catch { /* 忽略解析错误 */ }
    };

    es.onerror = () => {
      if (!resolved) {
        resolved = true;
        cleanup();
        resolve(null);
      }
    };
  });
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
