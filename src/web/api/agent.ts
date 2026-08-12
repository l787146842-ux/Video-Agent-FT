/**
 * Agent 聊天相关 API
 * 端点：/api/agent/chat, /api/agent/chat/stream
 */
import { apiPost, apiFetch, apiPut } from './client';
import type { AgentChatRequest, Skill } from '@/types';

/** 非流式聊天响应 */
export interface AgentChatResponse {
  text: string;
  applied_actions: number;
  steps: number;
  warnings: string[];
  confirmation: string;
  documents_written: string[];
  state?: Record<string, unknown>;
}

/** 非流式 LLM 调用（音频规划等场景用） */
export function canvasLlm(request: AgentChatRequest) {
  return apiPost<{ text: string }>('/api/agent/chat', request);
}

/** 加载 Skill 列表（Agent 技能配置，/api/plugins/ftdyb-agent/config） */
export async function getSkills(): Promise<Skill[]> {
  const data = await apiFetch<{ skills?: Skill[] }>('/api/plugins/ftdyb-agent/config');
  return Array.isArray(data.skills) ? data.skills : [];
}

/** 上下文用量估算（发送按钮旁小圆圈悬停展示「已用多少K上下文」） */
export interface ContextUsage {
  chars: number;
  est_tokens: number;
  state_chars: number;
  history_chars: number;
  /** 当前模型上下文窗口（0 = 未传模型，前端回退纯数字展示） */
  window_tokens: number;
}

export function getContextUsage(model?: string): Promise<ContextUsage> {
  const qs = model ? `?model=${encodeURIComponent(model)}` : '';
  return apiFetch<ContextUsage>(`/api/agent/context-usage${qs}`);
}

/** 运行时设置：模型 fallback 开关（开=联不通换同模型其他厂商；关=按上游报错） */
export interface RuntimeSettings {
  model_fallback_enabled: boolean;
}

export function getRuntimeSettings(): Promise<RuntimeSettings> {
  return apiFetch<RuntimeSettings>('/api/settings/runtime');
}

export function setRuntimeSettings(body: RuntimeSettings): Promise<RuntimeSettings> {
  return apiPut<RuntimeSettings>('/api/settings/runtime', body);
}

/** 是否有聊天 worker 仍在运行（含刷新后转后台的） */
export function getAgentRunning(): Promise<{ running: boolean }> {
  return apiFetch<{ running: boolean }>('/api/agent/running');
}

/** 显式停止聊天 worker（停止按钮专用；刷新不调用，worker 续跑） */
export function stopAgentTask(): Promise<{ ok: boolean; cancelled: number }> {
  return apiPost<{ ok: boolean; cancelled: number }>('/api/agent/stop', {});
}
