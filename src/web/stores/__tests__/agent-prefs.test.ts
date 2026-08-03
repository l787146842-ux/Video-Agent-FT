import { describe, it, expect, vi } from 'vitest';
import type { ApiProvider } from '@/types';

/**
 * P2-2：输入区 pill 选择持久化 —— API/模型/Skill 记住上次选择（localStorage），
 * 默认值预填，供应商失效时回退首选可用项。
 */

const PROVIDERS: ApiProvider[] = [
  { id: 'custom-api', name: '自定义', protocol: 'openai', image_models: [], video_models: [], chat_models: ['chat-a', 'chat-b'] },
  { id: 'volcengine', name: '火山', protocol: 'openai', image_models: [], video_models: [], chat_models: ['vc-1'] },
];

/** agent-prefs 在模块加载时读取 localStorage，需按用例重置模块缓存后动态导入；
 * 重置后必须在同一新模块图内注入 apiProviders，否则被测模块看不到供应商列表 */
async function loadPrefs(stored: Record<string, string>, providers: ApiProvider[] = PROVIDERS) {
  localStorage.clear();
  Object.entries(stored).forEach(([k, v]) => localStorage.setItem(k, v));
  vi.resetModules();
  const core = await import('@/stores/studio-core');
  core.setState('apiProviders', providers);
  return import('@/stores/agent-prefs');
}

describe('stores/agent-prefs（P2-2 pill 持久化）', () => {
  it('无记录时使用默认预填（首选 chat 供应商 + 其首个模型 + 默认 skill）', async () => {
    const prefs = await loadPrefs({});
    expect(prefs.agentProvider()).toBe('custom-api');
    expect(prefs.agentModel()).toBe('chat-a');
    expect(prefs.agentSkillId()).toBe('production-agent');
    expect(prefs.agentAssetMode()).toBe('bound');
  });

  it('记住上次选择：从 localStorage 恢复供应商/模型/技能', async () => {
    const prefs = await loadPrefs({
      studioAgentProvider: 'volcengine',
      studioAgentModel: 'vc-1',
      studioAgentSkill: 'story-generator',
      studioAgentAssetMode: 'all',
    });
    expect(prefs.agentProvider()).toBe('volcengine');
    expect(prefs.agentModel()).toBe('vc-1');
    expect(prefs.agentSkillId()).toBe('story-generator');
    expect(prefs.agentAssetMode()).toBe('all');
  });

  it('选择即写入 localStorage', async () => {
    const prefs = await loadPrefs({});
    prefs.setAgentProvider('volcengine');
    expect(localStorage.getItem('studioAgentProvider')).toBe('volcengine');
    prefs.setAgentModel('vc-1');
    expect(localStorage.getItem('studioAgentModel')).toBe('vc-1');
    prefs.setAgentSkill('story-generator');
    expect(localStorage.getItem('studioAgentSkill')).toBe('story-generator');
    prefs.setAgentAssetMode('all');
    expect(localStorage.getItem('studioAgentAssetMode')).toBe('all');
  });

  it('记录的供应商已失效（无 chat 模型）时回退首选可用项', async () => {
    const prefs = await loadPrefs({ studioAgentProvider: 'custom-api' }, [PROVIDERS[1]]);
    expect(prefs.agentProvider()).toBe('volcengine');
  });

  it('记录的模型不在当前供应商列表中时回退该供应商首个模型', async () => {
    const prefs = await loadPrefs({ studioAgentProvider: 'custom-api', studioAgentModel: '已下架模型' });
    expect(prefs.agentModel()).toBe('chat-a');
  });

  it('切换供应商后旧模型失效并回退新供应商首个模型', async () => {
    const prefs = await loadPrefs({ studioAgentProvider: 'custom-api', studioAgentModel: 'chat-b' });
    prefs.setAgentProvider('volcengine');
    expect(prefs.agentModel()).toBe('vc-1');
  });
});
