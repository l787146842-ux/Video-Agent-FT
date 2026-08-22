/**
 * API 客户端封装
 * 所有面板组件通过 api/ 层调用，不直接 fetch
 */
import { httpErrorPayload, makeErrorPayload, kindFromHttpStatus, type ErrorPayload } from '@/lib/error-payload';

export class ApiError extends Error {
  /** 任务 #19：结构化错误负载（消费方按 kind 做动作不再猜文案） */
  public payload: ErrorPayload;

  constructor(
    public status: number,
    public detail: string,
    /** 缺省按状态码兜底构造（兼容未走 readError 的直造点，如 upload） */
    payload?: ErrorPayload,
  ) {
    super(`API Error ${status}: ${detail}`);
    this.name = 'ApiError';
    this.payload = payload ?? makeErrorPayload(detail, kindFromHttpStatus(status));
  }
}

/** B6/F39：生产环境 X-API-Key 前端闭环——API 配置页写入 localStorage，
 * 每次 /api 请求自动携带（开发模式后端不校验，头被忽略无害）。 */
export const GLOBAL_API_KEY_STORAGE = 'ftdyb-api-key';

export function getGlobalApiKey(): string {
  try {
    return localStorage.getItem(GLOBAL_API_KEY_STORAGE) || '';
  } catch {
    return '';
  }
}

export function setGlobalApiKey(key: string): void {
  try {
    if (key.trim()) localStorage.setItem(GLOBAL_API_KEY_STORAGE, key.trim());
    else localStorage.removeItem(GLOBAL_API_KEY_STORAGE);
  } catch { /* 隐私模式等场景静默 */ }
}

async function readError(res: Response): Promise<ApiError> {
  let body: Record<string, unknown> | null = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  // 任务 #19：HTTP 失败与 SSE 错误事件共用同一解析器（lib/error-payload.ts）
  const payload = httpErrorPayload(res.status, body, res.statusText);
  return new ApiError(res.status, payload.message || res.statusText, payload);
}

export async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const key = getGlobalApiKey();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (key) headers['X-API-Key'] = key;
  const res = await fetch(path, {
    headers,
    ...opts,
  });
  if (!res.ok) {
    throw await readError(res);
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

/**
 * 抓取静态资源文本（文档面板展示上传的 md/txt 素材用，铁律 10.1：fetch 收口 api 层）。
 * 失败时抛错，由调用方决定降级行为（如新窗口打开）。
 */
export async function fetchResourceText(url: string): Promise<string> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`加载失败 (HTTP ${res.status})`);
  return res.text();
}

/**
 * 抓取媒体为 Blob（导出下载用，铁律 10.1：fetch 收口 api 层）。
 * 跨域资源自动走后端 /api/image-proxy 代理。
 */
export async function fetchMediaBlob(url: string): Promise<Blob> {
  const fullUrl = url;
  const isCrossOrigin = fullUrl.startsWith('http') && !fullUrl.startsWith(location.origin);
  const fetchUrl = isCrossOrigin
    ? `/api/image-proxy?url=${encodeURIComponent(fullUrl)}`
    : fullUrl;
  const res = await fetch(fetchUrl);
  if (!res.ok) throw new Error(`媒体下载失败 (HTTP ${res.status})`);
  return res.blob();
}
