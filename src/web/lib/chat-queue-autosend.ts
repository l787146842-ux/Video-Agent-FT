/**
 * 排队消息自动出队（P4-23 结构清欠从 ChatInput 拆出）：
 * Agent 一空闲就把队首引导消息按序发出（未选供应商时留在队里不丢）。
 * B0/F60：发送失败（网络/被拦截）时把消息放回队首，不丢失。
 * 纯响应式副作用，调用方在组件作用域内调用一次即可。
 */
import { createEffect } from 'solid-js';
import { state } from '@/stores/studio';
import { chatState, chatActions } from '@/stores/chat';
import { sendUserMessage } from '@/lib/agent-actions';
import { agentProvider, agentModel } from '@/stores/agent-prefs';

export function startQueuedAutosend() {
  createEffect(() => {
    if (state.agentBusy) return;
    if (!agentProvider() || !agentModel()) return;
    const q = chatState.queuedMessages;
    if (!q.length) return;
    const first = q[0];
    chatActions.removeQueuedMessage(first.id);
    void sendUserMessage(first.parts.length ? first.parts : first.text).then((ok) => {
      if (!ok) {
        chatActions.enqueueMessage(first);
        chatActions.moveQueuedToFront(first.id);
      }
    });
  });
}
