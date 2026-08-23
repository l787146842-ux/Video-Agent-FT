/**
 * use-sse 测试公共假件（任务 #30 拆分后的共享 testkit）。
 *
 * use-sse.test.ts 按主题拆为多个 ≤250 行的测试文件（终态/replay/重连/停止/事件路由），
 * 本文件承载四文件共用的 fake 传输层响应、chat store 观察点与状态复位，
 * 避免每个文件重复 60+ 行脚手架。非 .test.ts 文件，vitest 不会当用例收集。
 *
 * 注意：各测试文件需自行 vi.mock('@/api/sse' 等)（mock 必须在使用方文件顶层注册）。
 */
import { vi } from 'vitest';
import { chatActions } from '@/stores/chat';
import { studioActions } from '@/stores/studio';
import type { AgentChatRequest } from '@/types';

export const req: AgentChatRequest = {
  message: '你好', provider: 'mock', model: 'mock-chat',
} as AgentChatRequest;

const enc = new TextEncoder();

/** fake SSE 响应：按帧推送后自然关流（parseSSE 只消费 ok/status/body.getReader） */
export function sseResponse(frames: Array<string | object>, status = 200): Response {
  const data = frames.map((f) => enc.encode(`data: ${typeof f === 'string' ? f : JSON.stringify(f)}\n\n`));
  let i = 0;
  const reader = {
    read: async () => {
      if (i >= data.length) return { done: true as const, value: undefined };
      const value = data[i];
      i += 1;
      return { done: false as const, value };
    },
  };
  return { ok: status >= 200 && status < 300, status, body: { getReader: () => reader } } as unknown as Response;
}

/** 永不关流的挂起响应（忙碌态持续，供引导/停止场景） */
export function hangingResponse(): Response {
  return {
    ok: true, status: 200,
    body: { getReader: () => ({ read: () => new Promise<never>(() => {}) }) },
  } as unknown as Response;
}

export const doneFrame = (text = '完成') => ({
  type: 'done', payload: { text, elapsed_ms: 100, steps: 1, applied_actions: 0 },
});

/** chat store 观察点（断言调用而非内部状态） */
export const spies = {
  finishStream: vi.spyOn(chatActions, 'finishStream'),
  streamError: vi.spyOn(chatActions, 'streamError'),
  cancelStream: vi.spyOn(chatActions, 'cancelStream'),
  restoreStreamingState: vi.spyOn(chatActions, 'restoreStreamingState'),
  appendDelta: vi.spyOn(chatActions, 'appendDelta'),
  appendReasoning: vi.spyOn(chatActions, 'appendReasoning'),
  setStatus: vi.spyOn(chatActions, 'setStatus'),
  addMessage: vi.spyOn(chatActions, 'addMessage'),
  removeQueuedMessage: vi.spyOn(chatActions, 'removeQueuedMessage'),
  docWritten: vi.spyOn(chatActions, 'docWritten'),
  loadMessages: vi.spyOn(chatActions, 'loadMessages'),
  clearStreaming: vi.spyOn(chatActions, 'clearStreaming'),
  toolStarted: vi.spyOn(chatActions, 'toolStarted'),
  toolFinished: vi.spyOn(chatActions, 'toolFinished'),
  applyDecisionForm: vi.spyOn(chatActions, 'applyDecisionForm'),
};

export function clearSpies(): void {
  Object.values(spies).forEach((s) => s.mockClear());
}

/** 会话/工作台状态复位（每个用例独立起点） */
export function resetChatTestState(): void {
  chatActions.loadMessages([]);
  chatActions.clearQueuedMessages();
  studioActions.setPendingAttachments([]);
}

export async function tick(): Promise<void> {
  await new Promise((r) => setTimeout(r, 0));
}
