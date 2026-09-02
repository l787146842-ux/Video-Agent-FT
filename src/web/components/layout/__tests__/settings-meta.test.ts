/**
 * layout 面板纯逻辑最小用例（任务 #30 覆盖口径纳入后的关键分支钉死）。
 * settings-meta：API 配置页常量一致性 + 工厂函数；
 * use-model-fetch：拉取模型的成功/空清单/异常/应用分支。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  PROTOCOL_OPTIONS, CLI_PROTOCOLS, CLI_ENTRIES, CLI_META, IMAGE_MODE_OPTIONS,
  imageModeLabel, newProvider, BUILTIN_IDS,
} from '../settings-meta';

vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));
vi.mock('@/api/client', () => ({ apiPost: vi.fn() }));

import { apiPost } from '@/api/client';
import { showToast } from '@/stores/toast';
import { useModelFetch } from '../use-model-fetch';
import type { EditableProvider } from '../settings-meta';

/**
 * 后端 CLI 路由清单（与 src/video_agent/web/routes/cli_status.py 对齐）。
 * 断言前端 CLI_ENTRIES 的 statusPath/helpPath 确实存在于后端已注册路由中，
 * 消除仅断言路径形状正则的假信心问题。
 */
const BACKEND_CLI_ROUTES: Array<{ path: string; method: 'GET' | 'POST' }> = [
  { path: '/api/gemini-cli/status', method: 'GET' },
  { path: '/api/gemini-cli/help', method: 'GET' },
  { path: '/api/codex/status', method: 'GET' },
  { path: '/api/codex/help', method: 'GET' },
  { path: '/api/jimeng/status', method: 'GET' },
  { path: '/api/jimeng/help', method: 'GET' },
  { path: '/api/jimeng/credit', method: 'GET' },
  { path: '/api/jimeng/login/start', method: 'POST' },
  { path: '/api/jimeng/login/status', method: 'GET' },
  { path: '/api/jimeng/logout', method: 'POST' },
];

describe('settings-meta 常量一致性', () => {
  it('CLI 协议都在协议选项表内（下拉与 CLI 集合不得漂移）', () => {
    const values = new Set(PROTOCOL_OPTIONS.map((o) => o.value));
    for (const p of CLI_PROTOCOLS) expect(values.has(p)).toBe(true);
  });

  it('CLI 条目与元数据键一一对应（状态/帮助端点路径存在于后端路由清单）', () => {
    const routeSet = new Set(BACKEND_CLI_ROUTES.map((r) => `${r.method} ${r.path}`));
    for (const e of CLI_ENTRIES) {
      expect(CLI_META[e.protocol]).toBeDefined();
      expect(routeSet.has(`GET ${e.statusPath}`)).toBe(true);
      expect(routeSet.has(`GET ${e.helpPath}`)).toBe(true);
    }
  });

  it('imageModeLabel：已知值取字典，未知值原样回显', () => {
    expect(imageModeLabel('openai')).toBe(IMAGE_MODE_OPTIONS[0].label);
    expect(imageModeLabel('unknown-mode')).toBe('unknown-mode');
  });

  it('newProvider 工厂：默认 OpenAI 协议 + 启用 + 空模型表', () => {
    const p = newProvider('my');
    expect(p).toMatchObject({
      id: 'my', protocol: 'openai', enabled: true, has_key: false,
      chat_models: [], image_models: [], video_models: [],
    });
  });

  it('内置平台集合含 modelscope（内置平台不得显示删除）', () => {
    expect(BUILTIN_IDS.has('modelscope')).toBe(true);
  });
});

describe('use-model-fetch 拉取模型分支', () => {
  const provider: EditableProvider = {
    id: 'prov1', name: 'P1', protocol: 'openai', base_url: 'https://x',
    enabled: true, chat_models: ['c1'], image_models: [' i2 '], video_models: [],
  };

  beforeEach(() => {
    vi.mocked(apiPost).mockReset();
    vi.mocked(showToast).mockClear();
  });

  it('无当前平台：早退不发请求', async () => {
    const m = useModelFetch(() => undefined, () => '', vi.fn());
    await m.fetchModels();
    expect(apiPost).not.toHaveBeenCalled();
  });

  it('成功：清单 = 上游 ∪ 已配置（trim/去重/字典序），savedCats 记录已配置项', async () => {
    vi.mocked(apiPost).mockResolvedValue({ all: ['b-model', 'a-model'], protocol: 'openai' });
    const m = useModelFetch(() => provider, () => 'sk-x', vi.fn());
    await m.fetchModels();
    expect(apiPost).toHaveBeenCalledWith('/api/providers/fetch-models', {
      base_url: 'https://x', api_key: 'sk-x', provider_id: 'prov1', protocol: 'openai',
    });
    const f = m.fetched();
    // 已配置 'i2'（trim 后）并入清单且字典序
    expect(f?.all).toEqual(['a-model', 'b-model', 'c1', 'i2']);
    expect(f?.total).toBe(4);
    expect(m.savedCats().chat.has('c1')).toBe(true);
    expect(m.savedCats().image.has('i2')).toBe(true);
  });

  it('上游空清单 / 显式 error：toast 报错不进入选择弹窗', async () => {
    vi.mocked(apiPost).mockResolvedValueOnce({ all: [] });
    const m1 = useModelFetch(() => provider, () => '', vi.fn());
    await m1.fetchModels();
    expect(m1.fetched()).toBeNull();
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('上游未返回模型'), 'error');

    vi.mocked(apiPost).mockResolvedValueOnce({ all: ['x'], error: '鉴权失败' });
    const m2 = useModelFetch(() => provider, () => '', vi.fn());
    await m2.fetchModels();
    expect(m2.fetched()).toBeNull();
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('鉴权失败'), 'error');
  });

  it('请求异常：toast 带错误消息', async () => {
    vi.mocked(apiPost).mockRejectedValue(new Error('网络不通'));
    const m = useModelFetch(() => provider, () => '', vi.fn());
    await m.fetchModels();
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('网络不通'), 'error');
  });

  it('applyFetched：勾选结果写回三模型表并关闭弹窗', () => {
    const patch = vi.fn();
    const m = useModelFetch(() => provider, () => '', patch);
    m.applyFetched({ image: ['i1'], chat: ['c1', 'c2'], video: [] });
    expect(patch).toHaveBeenCalledWith('image_models', ['i1']);
    expect(patch).toHaveBeenCalledWith('chat_models', ['c1', 'c2']);
    expect(patch).toHaveBeenCalledWith('video_models', []);
    expect(m.fetched()).toBeNull();
  });
});
