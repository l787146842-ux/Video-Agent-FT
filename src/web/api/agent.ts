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

/** 运行时设置：全局生成默认 + 模型 fallback 开关（热生效，持久化于后端） */
export interface RuntimeSettings {
  model_fallback_enabled: boolean;
  /** 聊天框出图开关：关 = Agent 在对话中不主动触发生图 */
  chat_image_enabled: boolean;
  default_image_provider_id: string;
  default_image_model: string;
  default_video_provider_id: string;
  default_video_model: string;
  default_image_resolution: string;
  default_video_resolution: string;
  /** 分镜最大时长（秒）：Agent 自拆分镜单镜上限 */
  max_shot_duration: number;
  /** 814H7：执行器机械调用推理档位（''=默认/原生） */
  executor_thinking_level: string;
  /** 814H7：辅助摘要（记忆摘要/会话压缩）推理档位（''=默认/原生） */
  aux_thinking_level: string;
}

export function getRuntimeSettings(): Promise<RuntimeSettings> {
  return apiFetch<RuntimeSettings>('/api/settings/runtime');
}

export function setRuntimeSettings(body: Partial<RuntimeSettings>): Promise<RuntimeSettings> {
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

/** 登记一条任务执行期间的用户引导（7777 三轮：轮间注入，不打断当前操作） */
export function sendGuidance(id: string, message: string) {
  return apiPost<{ ok: boolean; project_id: string }>('/api/agent/guidance', { id, message });
}
