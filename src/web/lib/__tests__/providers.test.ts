import { describe, it, expect, beforeEach } from 'vitest';
import { setState } from '@/stores/studio';
import {
  apiProvidersFor, providerModels, preferredProviderIdForKind, defaultModelFor,
  audioProvidersFor,
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

  it('audioProvidersFor 只列已接适配器且该通道有模型的启用供应商', () => {
    setState('apiProviders', [
      { id: 'bailian', name: '百炼', audio_adapter: 'dashscope', audio_models: ['x'],
        audio_models_meta: [{ model: 'x', capabilities: ['tts'] }] },
      { id: 'tencent', name: '腾讯云', audio_adapter: '', audio_models: ['y'],
        audio_models_meta: [{ model: 'y', capabilities: ['tts'] }] },
      { id: 'music', name: '音乐', audio_adapter: 'openai-speech', audio_models: ['m'],
        audio_models_meta: [{ model: 'm', capabilities: ['music'] }] },
      { id: 'disabled', name: '停用', enabled: false, audio_adapter: 'dashscope', audio_models: ['z'],
        audio_models_meta: [{ model: 'z', capabilities: ['tts'] }] },
    ] as never);
    expect(audioProvidersFor('tts').map((p) => p.id)).toEqual(['bailian']);
    expect(audioProvidersFor('music').map((p) => p.id)).toEqual(['music']);
  });
});
