/**
 * api/client.ts 传输层测试（任务 #30）。
 * 钉死：ApiError 携带结构化 ErrorPayload、X-API-Key 注入、
 * 204/网络失败归类、媒体/文本资源抓取收口。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  apiFetch, apiPost, apiPut, apiDelete, ApiError,
  getGlobalApiKey, setGlobalApiKey, GLOBAL_API_KEY_STORAGE,
  fetchImageAsFile, fetchResourceText, fetchMediaBlob,
} from '../client';

const fetchMock = vi.fn();

/** 最小 Response 假件（client 只消费 ok/status/statusText/json/text/blob） */
function res(body: unknown, init?: { status?: number; statusText?: string }): Response {
  const status = init?.status ?? 200;
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: init?.statusText ?? 'OK',
    json: async () => body,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
    blob: async () => new Blob([String(body)], { type: 'image/png' }),
  } as unknown as Response;
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  localStorage.clear();
});

describe('apiFetch 请求装配', () => {
  it('默认携带 Content-Type；未配置 Key 不注入 X-API-Key', async () => {
    fetchMock.mockResolvedValue(res({ a: 1 }));
    const data = await apiFetch<{ a: number }>('/api/x');
    expect(data).toEqual({ a: 1 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/x');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(init.headers['X-API-Key']).toBeUndefined();
  });

  it('配置 Key 后每次请求自动注入 X-API-Key（生产鉴权前端闭环）', async () => {
    setGlobalApiKey('sk-test-123');
    expect(getGlobalApiKey()).toBe('sk-test-123');
    fetchMock.mockResolvedValue(res({}));
    await apiFetch('/api/x');
    expect(fetchMock.mock.calls[0][1].headers['X-API-Key']).toBe('sk-test-123');
    // 空白 Key 视为清除
    setGlobalApiKey('   ');
    expect(getGlobalApiKey()).toBe('');
    expect(localStorage.getItem(GLOBAL_API_KEY_STORAGE)).toBeNull();
  });

  it('204 No Content 返回 undefined（不解析空响应体）', async () => {
    fetchMock.mockResolvedValue(res(null, { status: 204 }));
    await expect(apiFetch('/api/x')).resolves.toBeUndefined();
  });

  it('apiPost/apiPut/apiDelete 方法与 body 序列化', async () => {
    fetchMock.mockResolvedValue(res({}));
    await apiPost('/api/p', { k: 'v' });
    await apiPut('/api/u', { n: 2 });
    await apiDelete('/api/d');
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST', body: '{"k":"v"}' });
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'PUT', body: '{"n":2}' });
    expect(fetchMock.mock.calls[2][1].method).toBe('DELETE');
  });
});

/** 捕获 reject 并收窄为 ApiError（catch 的 err 为 unknown，先断言实例再访问字段） */
async function catchApiError(p: Promise<unknown>): Promise<ApiError> {
  const err = await p.catch((e) => e);
  expect(err).toBeInstanceOf(ApiError);
  return err as ApiError;
}

describe('HTTP 失败 → ApiError + ErrorPayload', () => {
  it('后端结构化负载直接采信（code/kind/message/raw）', async () => {
    fetchMock.mockResolvedValue(res({
      code: 'err.auth.invalid_key', kind: 'auth', message: 'Key 无效', raw: 'upstream 401',
    }, { status: 401, statusText: 'Unauthorized' }));
    const err = await catchApiError(apiFetch('/api/x'));
    expect(err.status).toBe(401);
    expect(err.payload).toEqual({
      code: 'err.auth.invalid_key', kind: 'auth', message: 'Key 无效', raw: 'upstream 401',
    });
  });

  it('旧后端 legacy error_code 桥接归类', async () => {
    fetchMock.mockResolvedValue(res({ error_code: 'RATE_LIMITED', detail: '触发限流' }, { status: 429 }));
    const err = await catchApiError(apiPost('/api/x', {}));
    expect(err.payload).toMatchObject({ kind: 'quota', code: 'err.quota.rate_limited', message: '触发限流' });
  });

  it('无结构化信息按状态码兜底（500 → upstream）', async () => {
    fetchMock.mockResolvedValue(res({}, { status: 500, statusText: 'Internal Server Error' }));
    const err = await catchApiError(apiFetch('/api/x'));
    expect(err.payload).toMatchObject({ kind: 'upstream' });
    expect(err.message).toContain('500');
  });

  it('网络层失败（fetch reject）原样上抛——非 ApiError，由调用方归 network', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const err = await apiFetch('/api/x').catch((e) => e);
    expect(err).toBeInstanceOf(TypeError);
    expect(err).not.toBeInstanceOf(ApiError);
  });
});

describe('资源抓取收口', () => {
  it('fetchImageAsFile：成功封装 File；HTTP 失败/异常降级 null', async () => {
    fetchMock.mockResolvedValueOnce(res('img'));
    const file = await fetchImageAsFile('/a.png', 'a.png');
    expect(file).toBeInstanceOf(File);
    expect(file?.name).toBe('a.png');

    fetchMock.mockResolvedValueOnce(res('', { status: 404 }));
    expect(await fetchImageAsFile('/a.png', 'a.png')).toBeNull();

    fetchMock.mockRejectedValueOnce(new Error('net'));
    expect(await fetchImageAsFile('/a.png', 'a.png')).toBeNull();
  });

  it('fetchResourceText：成功返文本；失败抛错由调用方降级', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, text: async () => '# 文档' });
    await expect(fetchResourceText('/doc.md')).resolves.toBe('# 文档');
    fetchMock.mockResolvedValueOnce({ ok: false, status: 404, text: async () => '' });
    await expect(fetchResourceText('/doc.md')).rejects.toThrow('404');
  });

  it('fetchMediaBlob：跨域资源自动走 /api/image-proxy 代理；同源直取', async () => {
    fetchMock.mockResolvedValue(res('blob'));
    await fetchMediaBlob('https://cdn.example.com/x.png');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/image-proxy?url=https%3A%2F%2Fcdn.example.com%2Fx.png');
    await fetchMediaBlob('/workspace/assets/x.png');
    expect(fetchMock.mock.calls[1][0]).toBe('/workspace/assets/x.png');
  });
});
