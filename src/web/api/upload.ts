/**
 * 文件上传 API
 * 端点：POST /api/ai/upload（multipart/form-data）
 */
import { ApiError, buildAuthHeaders } from './client';
import { httpErrorPayload } from '@/lib/error-payload';

export interface UploadedFile {
  name: string;
  kind: 'image' | 'video' | 'audio' | 'doc';
  url: string;
}

interface UploadResponse {
  files: UploadedFile[];
}

/**
 * 批量上传素材文件。
 * 注意：multipart 不能走 apiFetch（其强制 JSON Content-Type），
 * 必须由浏览器自动生成 FormData boundary。
 */
export async function uploadFiles(files: File[]): Promise<UploadedFile[]> {
  const form = new FormData();
  files.forEach((f) => form.append('files', f));

  const res = await fetch('/api/ai/upload', { method: 'POST', headers: buildAuthHeaders(), body: form });
  if (!res.ok) {
    let body: Record<string, unknown> | null = null;
    try {
      body = (await res.json()) as Record<string, unknown>;
    } catch {
      /* 非 JSON 错误响应，回落 statusText */
    }
    // P9：multipart 旁路也走统一解析器，采信后端 ErrorPayload 结构化字段
    const payload = httpErrorPayload(res.status, body, res.statusText);
    throw new ApiError(res.status, payload.message || res.statusText, payload);
  }
  const data = (await res.json()) as UploadResponse;
  return data.files;
}
