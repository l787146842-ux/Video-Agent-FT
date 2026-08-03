import { describe, it, expect, beforeEach } from 'vitest';
import { setState } from '@/stores/studio';
import {
  apiProvidersFor, providerModels, preferredProviderIdForKind, defaultModelFor,
} from '@/lib/providers';
import type { ApiProvider } from '@/types';

const PROVIDERS: ApiProvider[] = [
  { id: 'custom-api', name: '自定义', protocol: 'openai', image_models: ['img-a'], video_models: [], chat_models: ['chat-a'] },
  { id: 'volcengine', name: '火山', protocol: 'openai', image_models: [], video_models: ['vid-a'], chat_models: [] },
  { id: 'jimeng', name: '即梦', protocol: 'openai', image_models: [], video_models: ['vid-b'], chat_models: [] },
  { id: 'empty', name: '空', protocol: 'openai', image_models: [], video_models: [], chat_models: [] },
];

describe('lib/providers', () => {
  beforeEach(() => {
    setState('apiProviders', PROVIDERS);
  });

  it('apiProvidersFor 按类型过滤有模型的供应商', () => {
    expect(apiProvidersFor('image').map((p) => p.id)).toEqual(['custom-api']);
    expect(apiProvidersFor('video').map((p) => p.id)).toEqual(['volcengine', 'jimeng']);
    expect(apiProvidersFor('chat').map((p) => p.id)).toEqual(['custom-api']);
  });

  it('providerModels 返回模型列表', () => {
    expect(providerModels('volcengine', 'video')).toEqual(['vid-a']);
    expect(providerModels('不存在', 'chat')).toEqual([]);
  });

  it('preferredProviderIdForKind 偏好顺序（视频优先 volcengine）', () => {
    expect(preferredProviderIdForKind('video')).toBe('volcengine');
    expect(preferredProviderIdForKind('image')).toBe('custom-api');
  });

  it('defaultModelFor 返回首个模型', () => {
    expect(defaultModelFor('jimeng', 'video')).toBe('vid-b');
    expect(defaultModelFor('empty', 'chat')).toBe('');
  });
});
