/**
 * 记忆管理 API（4.7：记忆对用户可见可管理，不再是黑盒注入）
 * 对齐后端 routes/memory.py 契约
 */
import { apiFetch, apiDelete, apiPost } from './client';

export interface MemoryRecordView {
  id: string;
  kind: string;
  content: string;
  source: string;
  project_id: string;
  created_at: number;
  keywords: string[];
  /** 置顶（M4）：永远排在清单最前，豁免将来的自动清理 */
  pinned: boolean;
}

/** 记忆清单（新→旧）；projectId 传空返回全部 */
export async function listMemory(projectId = ''): Promise<{
  backend: string;
  records: MemoryRecordView[];
}> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return apiFetch<{ backend: string; records: MemoryRecordView[] }>(`/api/memory${qs}`);
}

/** 删除单条记忆 */
export function deleteMemory(id: string): Promise<{ ok: boolean }> {
  return apiDelete<{ ok: boolean }>(`/api/memory/${encodeURIComponent(id)}`);
}

/** 置顶/取消置顶（M4） */
export function pinMemory(id: string, pinned: boolean): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>(`/api/memory/${encodeURIComponent(id)}/pin`, { pinned });
}
