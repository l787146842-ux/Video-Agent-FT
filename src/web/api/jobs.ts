/**
 * 视频批量生成任务 API（Job 面板数据源）
 * 端点：/api/generate/video-batch（列表/详情/resume/cancel）
 * 创建端点已由 BatchGenBar 直调 apiPost，此处补全剩余 4 端点。
 */
import { apiFetch, apiPost } from './client';

/** 批次摘要（列表项） */
export interface BatchSummary {
  batch_id: string;
  project_id: string;
  status: string;
  done: number;
  failed: number;
  total: number;
  created_at: number;
}

/** 单镜状态（详情内嵌） */
export interface BatchShotItem {
  group_id: string;
  draft_id: string;
  title: string;
  status: string;
  task_id: string;
  error: string;
}

/** 批次详情 */
export interface BatchDetail extends BatchSummary {
  provider_id: string;
  model: string;
  resolution: string;
  duration: number;
  shots: BatchShotItem[];
  updated_at: number;
}

/** 获取批量任务列表（最新在前） */
export function listVideoBatches(projectId?: string) {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return apiFetch<{ batches: BatchSummary[] }>(`/api/generate/video-batch${qs}`);
}

/** 获取单个批次详情（逐镜状态/错误） */
export function getVideoBatch(batchId: string) {
  return apiFetch<BatchDetail>(`/api/generate/video-batch/${encodeURIComponent(batchId)}`);
}

/** 断点续跑：只重试 failed/pending 镜，已成功镜跳过 */
export function resumeVideoBatch(batchId: string) {
  return apiPost<BatchDetail>(
    `/api/generate/video-batch/${encodeURIComponent(batchId)}/resume`, {},
  );
}

/** 取消批次（已提交的生成任务由管线各自完成，不再提交新镜） */
export function cancelVideoBatch(batchId: string) {
  return apiPost<{ ok: boolean }>(
    `/api/generate/video-batch/${encodeURIComponent(batchId)}/cancel`, {},
  );
}
