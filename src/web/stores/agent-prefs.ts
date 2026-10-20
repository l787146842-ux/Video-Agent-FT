import { createSignal } from 'solid-js';
import { state, setState } from '@/stores/studio-core';
import {
  apiProvidersFor, preferredProviderIdForKind, providerModels,
} from '@/lib/providers';
import { setActiveSkillApi } from '@/api/docs';
import { showToast } from '@/stores/toast';
import { isSkillEnabled } from '@/stores/skill-prefs';
import type { Skill } from '@/types';

/**
 * Agent 聊天偏好：供应商/模型/技能/资产范围。
 * 供应商/模型/资产：localStorage 持久化（keys 与旧版一致）+ 响应式 signal。
 * 技能（批 C）：KEY_SKILL 降级为「建议值」（跨会话记忆，不自动生效）；
 * 激活事实归项目态（后端 activeSkill，随快照下发），新项目默认自由对话。
 */

export const KEY_PROVIDER = 'studioAgentProvider';
export const KEY_MODEL = 'studioAgentModel';
export const KEY_SKILL = 'studioAgentSkill';
export const KEY_ASSET_MODE = 'studioAgentAssetMode';
export const KEY_THINKING = 'studioAgentThinkingLevel';

const [provider, setProviderSig] = createSignal(localStorage.getItem(KEY_PROVIDER) || '');
const [model, setModelSig] = createSignal(localStorage.getItem(KEY_MODEL) || '');
const [skillId, setSkillSig] = createSignal(localStorage.getItem(KEY_SKILL) || '');
const [assetMode, setAssetModeSig] = createSignal(localStorage.getItem(KEY_ASSET_MODE) || 'bound');
const [thinkingLevel, setThinkingLevelSig] = createSignal(localStorage.getItem(KEY_THINKING) || '');

/**  会话级推理档位：''=默认（模型原生）；low/medium/high 透传 reasoning_effort */
export type ThinkingLevel = '' | 'low' | 'medium' | 'high';
export const THINKING_LEVEL_OPTIONS: Array<{ value: ThinkingLevel; label: string }> = [
  { value: 'high', label: '高' },
  { value: 'medium', label: '中' },
  { value: 'low', label: '低' },
  { value: '', label: '默认' },
];

export function agentThinkingLevel(): ThinkingLevel {
  const v = thinkingLevel();
  return v === 'low' || v === 'medium' || v === 'high' ? v : '';
}

export function setAgentThinkingLevel(v: string) {
  const norm: ThinkingLevel = v === 'low' || v === 'medium' || v === 'high' ? v : '';
  localStorage.setItem(KEY_THINKING, norm);
  setThinkingLevelSig(norm);
}

export function thinkingLevelLabel(): string {
  const opt = THINKING_LEVEL_OPTIONS.find((o) => o.value === agentThinkingLevel());
  return opt?.label || '默认';
}

/** 有效供应商（localStorage 值失效时回退到首选可用项） */
export function agentProvider(): string {
  const p = provider();
  return providerModels(p, 'chat').length ? p : preferredProviderIdForKind('chat');
}

export function setAgentProvider(v: string) {
  localStorage.setItem(KEY_PROVIDER, v);
  setProviderSig(v);
  // 供应商切换后模型失效，重置
  setAgentModel('');
}

/** 有效模型 */
export function agentModel(): string {
  const models = providerModels(agentProvider(), 'chat');
  const m = model();
  return models.includes(m) ? m : models[0] || '';
}

export function setAgentModel(v: string) {
  localStorage.setItem(KEY_MODEL, v);
  setModelSig(v);
}

export function agentSkillId(): string {
  // 文档区 Skill 为唯一权威（2026-10-16 用户裁决，推翻批 C 的「空 slug =
  // 显式自由对话」）：项目里登记过的 Skill 一律生效，空 slug 不再等于关闭，
  // 而是「无显式偏好」→ 回落 usedSkills 倒序（与后端
  // registry.fallback_skill_from_state 同口径，P1 单一事实源）。
  //
  // 可加载性判据与后端 `resolve_loadable_entry` 对齐：**已登记 ∧ 未停用**。
  // 此前前端只查 `state.skills`（含被停用项）⇒ 后端返空、前端仍显芯片的漂移；
  // 现同引 `isSkillEnabled`（数据源 = runtime_settings.skills_disabled）。
  const loadable = (id: string) =>
    state.skills.some((s) => s.id === id)
    && isSkillEnabled(id.replace(/^doc:/, ''));
  const active = state.activeSkill;
  if (active?.slug) {
    const id = `doc:${active.slug}`;
    if (loadable(id)) return id;
    // 显式绑定不可加载（文档已删/被停用）：不再短路，继续回落（同后端口径）
  }
  // 倒序取首个仍可加载的（跳过已删文档/已停用项留下的陈旧登记）
  for (let i = state.usedSkills.length - 1; i >= 0; i -= 1) {
    const id = `doc:${state.usedSkills[i]}`;
    if (loadable(id)) return id;
  }
  // 新项目（usedSkills 为空）不回落全局建议值——建议只以建议芯片呈现，
  // 新项目是唯一获准的「无 Skill」入口（自由对话）。
  return '';
}

export function agentSkill() {
  const id = agentSkillId();
  return state.skills.find((s) => s.id === id);
}

/** 建议值（批 C）：全局 KEY_SKILL 仅作可一键采纳的建议，不自动激活；
 * 无效/无记录返回空（建议不呈现）。 */
export function suggestedSkillId(): string {
  const id = skillId();
  if (id && state.skills.some((s) => s.id === id)) return id;
  return '';
}

/** 写入建议值（跨会话记忆；不再是激活动作，激活走 activateSkill） */
export function setAgentSkill(v: string) {
  localStorage.setItem(KEY_SKILL, v);
  setSkillSig(v);
}

/** 激活 Skill 到项目态：乐观写本地态 + 后端落盘；
 * 同步更新全局建议值（不丢失）。失败回滚本地态。 */
export async function activateSkill(skillId: string, source: 'user' | 'suggested' = 'user'): Promise<boolean> {
  const slug = skillId.startsWith('doc:') ? skillId.slice(4) : '';
  if (!slug) return false;
  const prev = state.activeSkill;
  setState('activeSkill', { slug, source });
  setAgentSkill(skillId);
  try {
    await setActiveSkillApi(slug, source);
    return true;
  } catch (err) {
    setState('activeSkill', prev);
    showToast(`Skill 激活失败：${(err as Error).message}`, 'error');
    return false;
  }
}

// 2026-10-16 用户裁决：`deactivateSkill` 已整体移除——
// 文档区 Skill 是唯一权威，「关闭技能」不再是可用状态（详见 CHANGELOG）。
// 需要自由对话时新建一个没有 Skill 的项目；不需要在既有项目里「关掉」技能。

/** 忽略建议：仅清全局建议值，不动项目态（激活事实与建议分离） */
export function dismissSkillSuggestion() {
  setAgentSkill('');
}

export function agentAssetMode(): 'bound' | 'all' {
  return assetMode() === 'all' ? 'all' : 'bound';
}

export function setAgentAssetMode(v: 'bound' | 'all') {
  localStorage.setItem(KEY_ASSET_MODE, v);
  setAssetModeSig(v);
}

/** 模型降级即时联动：切换时刻就把输入框选择器跳到实际生效的组合 */
export function applyFallbackModel(providerId: string | undefined, modelName: string | undefined) {
  const name = (modelName || '').trim();
  if (!name) return;
  const chats = apiProvidersFor('chat');
  // 优先按后端给定的供应商 id 匹配；对不上再遍历找同名模型的供应商
  let target = chats.find((p) => p.id === providerId && providerModels(p.id, 'chat').includes(name));
  if (!target) target = chats.find((p) => providerModels(p.id, 'chat').includes(name));
  if (!target) return;
  if (agentProvider() !== target.id) setAgentProvider(target.id);
  setAgentModel(name);
}
