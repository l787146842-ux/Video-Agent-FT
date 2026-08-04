/**
 * Agent 聊天相关 API
 * 端点：/api/agent/chat, /api/agent/chat/stream
 */
import { apiPost, apiFetch } from './client';
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

/** 上下文用量估算（发送按钮旁状态图标悬停展示「已用多少K上下文」） */
export interface ContextUsage {
  chars: number;
  est_tokens: number;
  state_chars: number;
  history_chars: number;
}

export function getContextUsage(): Promise<ContextUsage> {
  return apiFetch<ContextUsage>('/api/agent/context-usage');
}
