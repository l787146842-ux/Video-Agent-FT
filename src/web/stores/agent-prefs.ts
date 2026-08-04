import { createSignal } from 'solid-js';
import { state } from '@/stores/studio-core';
import {
  preferredProviderIdForKind, providerModels,
} from '@/lib/providers';

/**
 * Agent 聊天偏好：供应商/模型/技能/资产范围
 * localStorage 持久化（keys 与旧版一致）+ 响应式 signal。
 * Pill 下拉显示与 sendUserMessage 发送共用同一份状态。
 */

export const KEY_PROVIDER = 'studioAgentProvider';
export const KEY_MODEL = 'studioAgentModel';
export const KEY_SKILL = 'studioAgentSkill';
export const KEY_ASSET_MODE = 'studioAgentAssetMode';

const [provider, setProviderSig] = createSignal(localStorage.getItem(KEY_PROVIDER) || '');
const [model, setModelSig] = createSignal(localStorage.getItem(KEY_MODEL) || '');
const [skillId, setSkillSig] = createSignal(localStorage.getItem(KEY_SKILL) || '');
const [assetMode, setAssetModeSig] = createSignal(localStorage.getItem(KEY_ASSET_MODE) || 'bound');

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
  // 代码内置 Skill（如 production-agent）已彻底移除；若旧 localStorage 里残留
  // 无效 id，回退到第一个可用文档 Skill，避免选中一个不存在的项。
  const id = skillId();
  if (id && state.skills.some((s) => s.id === id)) return id;
  return state.skills.length ? state.skills[0].id : '';
}

export function agentSkill() {
  const id = agentSkillId();
  return state.skills.find((s) => s.id === id);
}

export function setAgentSkill(v: string) {
  localStorage.setItem(KEY_SKILL, v);
  setSkillSig(v);
}

export function agentAssetMode(): 'bound' | 'all' {
  return assetMode() === 'all' ? 'all' : 'bound';
}

export function setAgentAssetMode(v: 'bound' | 'all') {
  localStorage.setItem(KEY_ASSET_MODE, v);
  setAssetModeSig(v);
}
