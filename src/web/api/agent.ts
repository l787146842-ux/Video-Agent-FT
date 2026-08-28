/**
 * Agent 聊天相关 API
 * 端点：/api/agent/chat（非流式）、/api/agent/metrics 等辅助端点
 */
import { apiPost, apiFetch, apiPut } from './client';
import type { AgentChatRequest, Skill } from '@/types';
import type { RuntimeSettings, RuntimeSettingsUpdate } from '@/types/api.generated';

/** 运行时设置读形态：以后端 RuntimeSettings 生成物为唯一来源（豁免清单已清偿） */
export type { RuntimeSettings };

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

/** 非流式 LLM 调用（音频规划等场景用）；：返回完整响应（documents_written
 * 由调用方即显渲染，通道与流式轨对齐，§5.2） */
export function canvasLlm(request: AgentChatRequest) {
  return apiPost<AgentChatResponse>('/api/agent/chat', request);
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

export function getRuntimeSettings(): Promise<RuntimeSettings> {
  return apiFetch<RuntimeSettings>('/api/settings/runtime');
}

export function setRuntimeSettings(body: RuntimeSettingsUpdate): Promise<RuntimeSettings> {
  return apiPut<RuntimeSettings>('/api/settings/runtime', body);
}

/** ：成本看板聚合指标 */
export interface AgentMetrics {
  traces_count: number;
  avg_turn_ms: number;
  /** ：平均耗时口径（llm_rounds=仅含模型调用轮；all=旧数据回落全量） */
  avg_turn_scope?: string;
  total_steps: number;
  total_actions: number;
  gate_total: number;
  gate_intercepts: number;
  gate_intercept_rate: number;
  fallback_count: number;
  recent_fallbacks: Array<{ ts: number; provider: string; model: string }>;
}

export function getAgentMetrics(): Promise<AgentMetrics> {
  return apiFetch<AgentMetrics>('/api/agent/metrics');
}

// ：原 getAgentRunning（GET /api/agent/running）与 stopAgentTask（POST /api/agent/stop）
// 为死代码——真实停止链路为 sse.ts::stopAgentTask → /api/agent/tasks/{id}/stop，
// 运行态由任务列表（listAgentTasks）派生；后端同名路由已同步清退。
// ：原 sendGuidance（POST /api/agent/guidance）为死代码——后端无该端点
// （真实链路为 sse.ts::postAgentTaskGuidance → /api/agent/tasks/{id}/guidance），已删除。
