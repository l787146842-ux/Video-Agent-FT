/**
 * 文件上传 API
 * 端点：POST /api/ai/upload（multipart/form-data）
 */
import { ApiError } from './client';

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

  const res = await fetch('/api/ai/upload', { method: 'POST', body: form });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail || detail;
    } catch {
      /* 非 JSON 错误响应，使用 statusText */
    }
    throw new ApiError(res.status, detail);
  }
  const data = (await res.json()) as UploadResponse;
  return data.files;
}
