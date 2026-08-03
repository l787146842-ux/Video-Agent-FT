/**
 * Agent 聊天相关 API
 * 端点：/api/agent/chat, /api/agent/chat/stream, /api/canvas-llm
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

/** 非流式 LLM 调用（画布模式 / 音频规划用） */
export function canvasLlm(request: AgentChatRequest) {
  return apiPost<{ text: string }>('/api/canvas-llm', request);
}

/** 加载 Skill 列表（Agent 技能配置，/api/plugins/ftdyb-agent/config） */
export async function getSkills(): Promise<Skill[]> {
  const data = await apiFetch<{ skills?: Skill[] }>('/api/plugins/ftdyb-agent/config');
  return Array.isArray(data.skills) ? data.skills : [];
}
