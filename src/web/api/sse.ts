/**
 * SSE 流式请求封装（api 层）
 * 将 Agent 聊天的 HTTP POST + ReadableStream 读取集中于此，
 * hooks/use-sse.ts 只负责事件分发与状态管理。
 */
import type { AgentChatRequest } from '@/types';

export interface SseStreamHandle {
  reader: ReadableStreamDefaultReader<Uint8Array>;
  abort: () => void;
}

/**
 * 发起 Agent 流式聊天请求，返回 ReadableStream reader。
 * 调用方负责逐块读取并解析 SSE 事件。
 */
export async function postAgentChatStream(
  request: AgentChatRequest,
  signal: AbortSignal,
): Promise<Response> {
  const res = await fetch('/api/agent/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  });
  return res;
}
