import { createSignal } from 'solid-js';
import { state, setState } from '@/stores/studio-core';
import {
  apiProvidersFor, preferredProviderIdForKind, providerModels,
} from '@/lib/providers';
import { setActiveSkillApi, setActiveStyleLayersApi } from '@/api/docs';
import { showToast } from '@/stores/toast';
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
  // 批 C：激活事实归项目态（后端 activeSkill 为权威，随快照下发）。
  // 已登记绑定：slug 空串 = 显式自由对话。
  const active = state.activeSkill;
  if (active) return active.slug ? `doc:${active.slug}` : '';
  // 未登记绑定的存量项目：保持旧口径（全局建议值校验后生效），
  // 不丢失既有选择；新项目（无 usedSkills）默认自由对话，
  // 全局值仅以建议形态呈现（suggestedSkillId + 采纳芯片）。
  if (!state.usedSkills.length) return '';
  const id = skillId();
  if (id && state.skills.some((s) => s.id === id)) return id;
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

/** 激活 Skill 到项目态（批 C）：乐观写本地态 + 后端落盘；
 * 同步更新全局建议值（不丢失）。失败回滚本地态。 */
export async function activateSkill(skillId: string, source: 'user' | 'suggested' = 'user'): Promise<boolean> {
  const slug = skillId.startsWith('doc:') ? skillId.slice(4) : '';
  if (!slug) return false;
  const prev = state.activeSkill;
  setState('activeSkill', { slug, source });
  setAgentSkill(skillId);
  try {
    await setActiveSkillApi(slug, source);
    // 组合激活（任务 #11）：新主流程若已在风格层清单内则同步摘除（与后端摈除同口径）
    if ((state.activeStyleSkills || []).includes(slug)) {
      setState('activeStyleSkills', (state.activeStyleSkills || []).filter((s) => s !== slug));
    }
    return true;
  } catch (err) {
    setState('activeSkill', prev);
    showToast(`Skill 激活失败：${(err as Error).message}`, 'error');
    return false;
  }
}

/** 摘除活跃 Skill（批 C）：回到自由对话（写项目态 + 后端留痕）；
 * 全局建议值不受影响（不丢失）。 */
export async function deactivateSkill(): Promise<boolean> {
  const prev = state.activeSkill;
  setState('activeSkill', { slug: '', source: 'user' });
  try {
    await setActiveSkillApi('', 'user');
    return true;
  } catch (err) {
    setState('activeSkill', prev);
    showToast(`Skill 摘除失败：${(err as Error).message}`, 'error');
    return false;
  }
}

/** 忽略建议（批 C）：仅清全局建议值，不动项目态（激活事实与建议分离） */
export function dismissSkillSuggestion() {
  setAgentSkill('');
}

// ===== 风格层组合激活（任务 #11：1 pipeline 可选 + N style 层） =====
// 激活事实归项目态（后端 styleSkills，随快照下发），与主流程激活同语义。

/** Skill id → slug（doc: 前缀剥离；与 SkillPicker 同源口径） */
export function skillSlugOf(skill: Skill): string {
  return (skill.slug as string) || skill.id.replace(/^doc:/, '');
}

/** 当前叠加的风格层 slug 清单（项目态权威） */
export function activeStyleSlugs(): string[] {
  return state.activeStyleSkills || [];
}

/** 某风格型 Skill 是否已叠加为风格层 */
export function isStyleLayerActive(skill: Skill): boolean {
  return activeStyleSlugs().includes(skillSlugOf(skill));
}

/** 切换风格层叠加态：全量替换式写项目态（乐观写本地 + 失败回滚）。
 * 仅 kind=style 的 Skill 可勾选（SkillPicker 按 kind 过滤）；
 * 后端对非法条目返 400/404，前端 toast 回显并回滚。 */
export async function toggleStyleLayer(skill: Skill): Promise<boolean> {
  const slug = skillSlugOf(skill);
  if (!slug) return false;
  const prev = [...(state.activeStyleSkills || [])];
  const next = prev.includes(slug) ? prev.filter((s) => s !== slug) : [...prev, slug];
  setState('activeStyleSkills', next);
  try {
    await setActiveStyleLayersApi({ slugs: next });
    return true;
  } catch (err) {
    setState('activeStyleSkills', prev);
    showToast(`风格层更新失败：${(err as Error).message}`, 'error');
    return false;
  }
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
