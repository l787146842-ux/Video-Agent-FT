/**
 * API 客户端封装
 * 所有面板组件通过 api/ 层调用，不直接 fetch
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`API Error ${status}: ${detail}`);
    this.name = 'ApiError';
  }
}

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return body.detail || body.message || res.statusText;
  } catch {
    return res.statusText;
  }
}

export async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readError(res));
  }
  // 204 No Content
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export async function apiDelete<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: 'DELETE' });
}

/**
 * 抓取图片并封装为 File 对象（聊天生图卡片拖拽用）。
 * 浏览器原生拖拽的 dataTransfer 只在 dragstart 同步阶段可写，
 * 因此组件需在拖拽前通过本函数预取 File 备用。失败返回 null，由调用方降级。
 */
export async function fetchImageAsFile(url: string, filename: string): Promise<File | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const blob = await res.blob();
    return new File([blob], filename, { type: blob.type || 'image/png' });
  } catch {
    return null;
  }
}
