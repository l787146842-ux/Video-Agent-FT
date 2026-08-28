import { describe, it, expect, vi } from 'vitest';
import type { ApiProvider, Skill } from '@/types';

/** api/docs 桁：风格层/主流程激活走 API 的用例不发起真实请求 */
const apiMock = vi.hoisted(() => ({
  setActiveSkillApi: vi.fn(async () => ({})),
  setActiveStyleLayersApi: vi.fn(async () => ({})),
}));
vi.mock('@/api/docs', () => apiMock);

/**
 * 输入区 pill 选择持久化 —— API/模型/资产范围记住上次选择（localStorage），
 * 默认值预填，供应商失效时回退首选可用项。
 * 技能（批 C）：KEY_SKILL 降级为建议值——新项目（无 usedSkills）默认自由
 * 对话，全局值仅以 suggestedSkillId 呈现；激活事实归项目态（activeSkill），
 * 未登记绑定的存量项目保持旧口径（全局值校验后生效，不丢失）。
 */

const PROVIDERS: ApiProvider[] = [
  { id: 'custom-api', name: '自定义', protocol: 'openai', image_models: [], video_models: [], chat_models: ['chat-a', 'chat-b'] },
  { id: 'volcengine', name: '火山', protocol: 'openai', image_models: [], video_models: [], chat_models: ['vc-1'] },
];

const DOC_SKILLS: Skill[] = [
  { id: 'doc:demo', name: '测试 Skill', description: '', system_prompt: '', source: 'doc', slug: 'demo' },
  { id: 'doc:other', name: '另一个 Skill', description: '', system_prompt: '', source: 'doc', slug: 'other' },
];

const STYLE_SKILLS: Skill[] = [
  ...DOC_SKILLS,
  { id: 'doc:style-a', name: '风格甲', description: '', system_prompt: '', source: 'doc', slug: 'style-a', kind: 'style' },
  { id: 'doc:style-b', name: '风格乙', description: '', system_prompt: '', source: 'doc', slug: 'style-b', kind: 'style' },
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

describe('stores/agent-prefs（pill 持久化）', () => {
  it('无记录时不再预填已删除的代码 Skill（默认空）', async () => {
    const prefs = await loadPrefs({});
    expect(prefs.agentProvider()).toBe('custom-api');
    expect(prefs.agentModel()).toBe('chat-a');
    expect(prefs.agentSkillId()).toBe('');
    expect(prefs.agentAssetMode()).toBe('bound');
  });

  it('新项目（无 usedSkills）默认自由对话，全局值仅作建议（批 C）', async () => {
    const prefs = await loadPrefs({ studioAgentSkill: 'doc:demo' }, PROVIDERS, DOC_SKILLS);
    expect(prefs.agentSkillId()).toBe('');
    expect(prefs.suggestedSkillId()).toBe('doc:demo');
    expect(prefs.agentSkill()).toBeUndefined();
  });

  it('存量项目（有 usedSkills、未登记绑定）保持旧口径从 localStorage 恢复', async () => {
    const prefs = await loadPrefs({
      studioAgentProvider: 'volcengine',
      studioAgentModel: 'vc-1',
      studioAgentSkill: 'doc:demo',
      studioAgentAssetMode: 'all',
    }, PROVIDERS, DOC_SKILLS);
    const core = await import('@/stores/studio-core');
    core.setState('usedSkills', ['demo']);
    expect(prefs.agentProvider()).toBe('volcengine');
    expect(prefs.agentModel()).toBe('vc-1');
    expect(prefs.agentSkillId()).toBe('doc:demo');
    expect(prefs.agentAssetMode()).toBe('all');
  });

  it('项目态绑定为权威：agentSkillId 从 activeSkill 派生（批 C）', async () => {
    const prefs = await loadPrefs({ studioAgentSkill: 'doc:other' }, PROVIDERS, DOC_SKILLS);
    const core = await import('@/stores/studio-core');
    core.setState('activeSkill', { slug: 'demo', source: 'user' });
    expect(prefs.agentSkillId()).toBe('doc:demo');
    expect(prefs.agentSkill()?.id).toBe('doc:demo');
    // 摘除态（空 slug）= 显式自由对话，不再回落建议值/usedSkills
    core.setState('activeSkill', { slug: '', source: 'user' });
    expect(prefs.agentSkillId()).toBe('');
    expect(prefs.suggestedSkillId()).toBe('doc:other');
  });

  it('残留的已删除代码 Skill id（production-agent）回退到默认无技能（D2 基线）', async () => {
    const prefs = await loadPrefs({ studioAgentSkill: 'production-agent' }, PROVIDERS, DOC_SKILLS);
    expect(prefs.agentSkillId()).toBe('');
    expect(prefs.suggestedSkillId()).toBe('');
  });

  it('选择即写入 localStorage（建议值语义，批 C）', async () => {
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

  it('忽略建议只清全局值不动项目态（批 C）', async () => {
    const prefs = await loadPrefs({ studioAgentSkill: 'doc:demo' }, PROVIDERS, DOC_SKILLS);
    const core = await import('@/stores/studio-core');
    core.setState('activeSkill', { slug: 'demo', source: 'user' });
    prefs.dismissSkillSuggestion();
    expect(localStorage.getItem('studioAgentSkill')).toBe('');
    expect(prefs.agentSkillId()).toBe('doc:demo');
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

describe('stores/agent-prefs（任务 #11 风格层组合激活）', () => {
  it('skillSlugOf 从 slug/派生 id 取 slug', async () => {
    const prefs = await loadPrefs({}, PROVIDERS, STYLE_SKILLS);
    expect(prefs.skillSlugOf(STYLE_SKILLS[2])).toBe('style-a');
    expect(prefs.skillSlugOf({ ...STYLE_SKILLS[2], slug: undefined } as unknown as Skill)).toBe('style-a');
  });

  it('toggleStyleLayer 勾选/取消都全量替换式下发清单', async () => {
    const prefs = await loadPrefs({}, PROVIDERS, STYLE_SKILLS);
    apiMock.setActiveStyleLayersApi.mockClear();
    expect(await prefs.toggleStyleLayer(STYLE_SKILLS[2])).toBe(true);
    expect(prefs.activeStyleSlugs()).toEqual(['style-a']);
    expect(apiMock.setActiveStyleLayersApi).toHaveBeenCalledWith({ slugs: ['style-a'] });
    expect(await prefs.toggleStyleLayer(STYLE_SKILLS[3])).toBe(true);
    expect(prefs.activeStyleSlugs()).toEqual(['style-a', 'style-b']);
    expect(apiMock.setActiveStyleLayersApi).toHaveBeenLastCalledWith({ slugs: ['style-a', 'style-b'] });
    expect(await prefs.toggleStyleLayer(STYLE_SKILLS[2])).toBe(true);
    expect(prefs.activeStyleSlugs()).toEqual(['style-b']);
    expect(apiMock.setActiveStyleLayersApi).toHaveBeenLastCalledWith({ slugs: ['style-b'] });
  });

  it('toggleStyleLayer 后端失败时回滚本地清单', async () => {
    const prefs = await loadPrefs({}, PROVIDERS, STYLE_SKILLS);
    apiMock.setActiveStyleLayersApi.mockClear();
    apiMock.setActiveStyleLayersApi.mockRejectedValueOnce(new Error('boom'));
    expect(await prefs.toggleStyleLayer(STYLE_SKILLS[2])).toBe(false);
    expect(prefs.activeStyleSlugs()).toEqual([]);
  });

  it('主流程激活后同 slug 风格层同步摈除（与后端互斥同口径）', async () => {
    const prefs = await loadPrefs({}, PROVIDERS, STYLE_SKILLS);
    apiMock.setActiveSkillApi.mockClear();
    apiMock.setActiveStyleLayersApi.mockClear();
    await prefs.toggleStyleLayer(STYLE_SKILLS[2]);
    expect(prefs.activeStyleSlugs()).toEqual(['style-a']);
    await prefs.activateSkill('doc:style-a', 'user');
    expect(prefs.activeStyleSlugs()).toEqual([]);
  });

  it('快照下发的风格层清单进入项目态（同步口径）', async () => {
    const prefs = await loadPrefs({}, PROVIDERS, STYLE_SKILLS);
    const core = await import('@/stores/studio-core');
    core.setState('activeStyleSkills', ['style-b']);
    expect(prefs.activeStyleSlugs()).toEqual(['style-b']);
    expect(prefs.isStyleLayerActive(STYLE_SKILLS[3])).toBe(true);
    expect(prefs.isStyleLayerActive(STYLE_SKILLS[2])).toBe(false);
  });
});
