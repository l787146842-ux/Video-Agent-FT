import { describe, it, expect, vi } from 'vitest';
import type { ApiProvider, Skill } from '@/types';

/**
 * P2-2：输入区 pill 选择持久化 —— API/模型/Skill 记住上次选择（localStorage），
 * 默认值预填，供应商失效时回退首选可用项。
 * 代码内置 Skill（production-agent 等）已彻底移除：默认不再预填。
 * B4/F28·D2 基线：默认无技能——残留无效 Skill id 同样返回空
 * （不自动回落第一个文档 Skill），由「不使用技能」卡承载默认态。
 */

const PROVIDERS: ApiProvider[] = [
  { id: 'custom-api', name: '自定义', protocol: 'openai', image_models: [], video_models: [], chat_models: ['chat-a', 'chat-b'] },
  { id: 'volcengine', name: '火山', protocol: 'openai', image_models: [], video_models: [], chat_models: ['vc-1'] },
];

const DOC_SKILLS: Skill[] = [
  { id: 'doc:demo', name: '测试 Skill', description: '', system_prompt: '', source: 'doc', slug: 'demo' },
  { id: 'doc:other', name: '另一个 Skill', description: '', system_prompt: '', source: 'doc', slug: 'other' },
];

/** agent-prefs 在模块加载时读取 localStorage，需按用例重置模块缓存后动态导入；
 * 重置后必须在同一新模块图内注入 apiProviders/skills，否则被测模块看不到列表 */
async function loadPrefs(
  stored: Record<string, string>,
  providers: ApiProvider[] = PROVIDERS,
  skills: Skill[] = [],
) {
  localStorage.clear();
  Object.entries(stored).forEach(([k, v]) => localStorage.setItem(k, v));
  vi.resetModules();
  const core = await import('@/stores/studio-core');
  core.setState('apiProviders', providers);
  core.setState('skills', skills);
  return import('@/stores/agent-prefs');
}

describe('stores/agent-prefs（P2-2 pill 持久化）', () => {
  it('无记录时不再预填已删除的代码 Skill（默认空）', async () => {
    const prefs = await loadPrefs({});
    expect(prefs.agentProvider()).toBe('custom-api');
    expect(prefs.agentModel()).toBe('chat-a');
    expect(prefs.agentSkillId()).toBe('');
    expect(prefs.agentAssetMode()).toBe('bound');
  });

  it('记住上次选择：从 localStorage 恢复供应商/模型/技能', async () => {
    const prefs = await loadPrefs({
      studioAgentProvider: 'volcengine',
      studioAgentModel: 'vc-1',
      studioAgentSkill: 'doc:demo',
      studioAgentAssetMode: 'all',
    }, PROVIDERS, DOC_SKILLS);
    expect(prefs.agentProvider()).toBe('volcengine');
    expect(prefs.agentModel()).toBe('vc-1');
    expect(prefs.agentSkillId()).toBe('doc:demo');
    expect(prefs.agentAssetMode()).toBe('all');
  });

  it('残留的已删除代码 Skill id（production-agent）回退到默认无技能（D2 基线）', async () => {
    const prefs = await loadPrefs({ studioAgentSkill: 'production-agent' }, PROVIDERS, DOC_SKILLS);
    expect(prefs.agentSkillId()).toBe('');
  });

  it('选择即写入 localStorage', async () => {
    const prefs = await loadPrefs({});
    prefs.setAgentProvider('volcengine');
    expect(localStorage.getItem('studioAgentProvider')).toBe('volcengine');
    prefs.setAgentModel('vc-1');
    expect(localStorage.getItem('studioAgentModel')).toBe('vc-1');
    prefs.setAgentSkill('doc:other');
    expect(localStorage.getItem('studioAgentSkill')).toBe('doc:other');
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
