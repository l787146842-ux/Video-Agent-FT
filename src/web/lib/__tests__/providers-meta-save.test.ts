import { describe, it, expect, beforeEach, vi } from 'vitest';
import { setState } from '@/stores/studio';

// 捕获 putProviders 收到的请求体（saveChatModelMeta 保存链的决定性验证：
// 2026-09-12 二次反馈——后端日志锚点实证 PUT body 无 chat_models_meta）
const putBodies: unknown[] = [];
vi.mock('@/api/providers', () => ({
  putProviders: vi.fn(async (providers: unknown[]) => {
    putBodies.push(providers);
    return { providers };
  }),
}));

import { saveChatModelMeta } from '@/lib/providers';
import type { ApiProvider } from '@/types';

const PROVIDERS: ApiProvider[] = [
  { id: 'custom-api-4', name: '基源律动', protocol: 'openai', image_models: [], video_models: [], chat_models: ['deepseek-v4-flash-0731'] },
];

describe('saveChatModelMeta 保存链', () => {
  beforeEach(() => {
    putBodies.length = 0;
    setState('apiProviders', structuredClone(PROVIDERS));
  });

  it('点 1M 后 PUT 请求体必须携带 chat_models_meta（防回归：曾被静默洗掉）', async () => {
    await saveChatModelMeta('custom-api-4', 'deepseek-v4-flash-0731', { context_window: 1000000 });
    expect(putBodies).toHaveLength(1);
    const body = putBodies[0] as ApiProvider[];
    const target = body.find((p) => p.id === 'custom-api-4');
    expect(target?.chat_models_meta).toEqual([
      { model: 'deepseek-v4-flash-0731', context_window: 1000000 },
    ]);
  });

  it('JSON.stringify（apiPut 实际序列化路径）不得丢失新增的 chat_models_meta', async () => {
    await saveChatModelMeta('custom-api-4', 'deepseek-v4-flash-0731', { context_window: 1000000 });
    const body = putBodies[0] as ApiProvider[];
    const serialized = JSON.parse(JSON.stringify(body));
    const target = serialized.find((p: ApiProvider) => p.id === 'custom-api-4');
    expect(target?.chat_models_meta?.[0]?.context_window).toBe(1000000);
  });

  it('已有 meta 时合并 patch 而不是整体覆盖', async () => {
    setState('apiProviders', [{
      ...PROVIDERS[0],
      chat_models_meta: [{ model: 'deepseek-v4-flash-0731', context_window: 200000, thinking_enabled: true }],
    }] as ApiProvider[]);
    await saveChatModelMeta('custom-api-4', 'deepseek-v4-flash-0731', { context_window: 400000 });
    const body = putBodies[0] as ApiProvider[];
    const target = body.find((p) => p.id === 'custom-api-4');
    expect(target?.chat_models_meta).toEqual([
      { model: 'deepseek-v4-flash-0731', context_window: 400000, thinking_enabled: true },
    ]);
  });
});
