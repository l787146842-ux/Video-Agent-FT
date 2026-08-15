import { createSignal } from 'solid-js';
import { state } from '@/stores/studio-core';
import {
  apiProvidersFor, preferredProviderIdForKind, providerModels,
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
export const KEY_THINKING = 'studioAgentThinkingLevel';

const [provider, setProviderSig] = createSignal(localStorage.getItem(KEY_PROVIDER) || '');
const [model, setModelSig] = createSignal(localStorage.getItem(KEY_MODEL) || '');
const [skillId, setSkillSig] = createSignal(localStorage.getItem(KEY_SKILL) || '');
const [assetMode, setAssetModeSig] = createSignal(localStorage.getItem(KEY_ASSET_MODE) || 'bound');
const [thinkingLevel, setThinkingLevelSig] = createSignal(localStorage.getItem(KEY_THINKING) || '');

/** 814H7 会话级推理档位：''=默认（模型原生）；low/medium/high 透传 reasoning_effort */
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
  // B4/F28·D2：默认无技能——localStorage 无值/失效时返回空（不自动回落第一个技能），
  // 用户显式选择 Skill 才激活流程/闸机；SkillPicker 提供「不使用技能」卡。
  const id = skillId();
  if (id && state.skills.some((s) => s.id === id)) return id;
  return '';
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

/** 模型降级即时联动（7777 事故）：切换时刻就把输入框选择器跳到实际生效的组合 */
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
