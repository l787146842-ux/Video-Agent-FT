/**
 * Skill 启停开关 store（批7）：数据源 = runtime_settings.skills_disabled。
 * 钉死：设置未加载 = 全启用（与后端默认空同口径）；切换发
 * PUT /api/settings/runtime 携 skills_disabled（加入=停用/移除=启用），
 * 回读后状态即时反映；设置加载失败只提示不写入。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const toastMock = vi.hoisted(() => vi.fn());
vi.mock('@/stores/toast', () => ({
  showToast: (...args: unknown[]) => toastMock(...args),
  dismissToast: vi.fn(),
  toasts: [],
}));

const fetchMock = vi.fn();

function res(body: unknown): Response {
  return {
    ok: true, status: 200, statusText: 'OK',
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

/** 每用例全新模块实例（global-settings 模块级缓存隔离） */
async function fresh() {
  vi.resetModules();
  vi.stubGlobal('fetch', fetchMock);
  return import('../skill-prefs');
}

beforeEach(() => {
  fetchMock.mockReset();
  toastMock.mockClear();
});

describe('skill-prefs 启停开关（批7：接线 runtime_settings）', () => {
  it('设置未加载 → 全启用（后端默认空口径，开关不误报停用）', async () => {
    const { isSkillEnabled } = await fresh();
    expect(isSkillEnabled('any-skill')).toBe(true);
  });

  it('GET runtime_settings 定启停：skills_disabled 内为停用、外为启用', async () => {
    fetchMock.mockResolvedValueOnce(res({ skills_disabled: ['doc-a'] }));
    const { isSkillEnabled } = await fresh();
    const { ensureGlobalSettings } = await import('../global-settings');
    await ensureGlobalSettings();
    expect(fetchMock.mock.calls[0][0]).toBe('/api/settings/runtime');
    expect(isSkillEnabled('doc-a')).toBe(false);
    expect(isSkillEnabled('doc-b')).toBe(true);
  });

  it('停用切换：PUT body 的 skills_disabled 加入该 slug，回读后即时停用', async () => {
    fetchMock.mockResolvedValueOnce(res({ skills_disabled: [] }));
    fetchMock.mockResolvedValueOnce(res({ skills_disabled: ['doc-a'] }));
    const { isSkillEnabled, toggleSkillEnabled } = await fresh();
    await toggleSkillEnabled('doc-a');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe('/api/settings/runtime');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({ skills_disabled: ['doc-a'] });
    expect(isSkillEnabled('doc-a')).toBe(false);
  });

  it('启用切换：PUT body 的 skills_disabled 移除该 slug', async () => {
    fetchMock.mockResolvedValueOnce(res({ skills_disabled: ['doc-a', 'doc-b'] }));
    fetchMock.mockResolvedValueOnce(res({ skills_disabled: ['doc-b'] }));
    const { isSkillEnabled, toggleSkillEnabled } = await fresh();
    await toggleSkillEnabled('doc-a');
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ skills_disabled: ['doc-b'] });
    expect(isSkillEnabled('doc-a')).toBe(true);
    expect(isSkillEnabled('doc-b')).toBe(false);
  });

  it('设置加载失败：不发 PUT，toast 提示', async () => {
    fetchMock.mockRejectedValueOnce(new Error('offline'));
    const { toggleSkillEnabled } = await fresh();
    await toggleSkillEnabled('doc-a');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(toastMock).toHaveBeenCalled();
  });
});
