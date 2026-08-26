/**
 * 排队消息自动出队（从 ChatInput 拆出，控制组件行数）：
 * Agent 一空闲就把队首引导消息按序发出（未选供应商时留在队里不丢）。
 * 发送走统一入口 submitMessage（intent='queued'）；
 * 发送失败（网络/被拦截）的回队首补偿由入口单点完成，不丢失。
 * 纯响应式副作用，调用方在组件作用域内调用一次即可。
 */
import { createEffect } from 'solid-js';
import { agentState } from '@/stores/agent-state';
import { chatState, chatActions } from '@/stores/chat';
import { submitMessage } from '@/lib/submit-message';
import { agentProvider, agentModel } from '@/stores/agent-prefs';

export function startQueuedAutosend() {
  createEffect(() => {
    if (agentState.agentBusy) return;
    if (!agentProvider() || !agentModel()) return;
    const q = chatState.queuedMessages;
    if (!q.length) return;
    const first = q[0];
    chatActions.removeQueuedMessage(first.id);
    // 携带原排队条目：校验被拦截时入口把原条目放回队首（保留 id 与顺序）
    void submitMessage('queued', {
      // 旧持久化条目可能无 parts 键（restore 归一化之外的双保险）：回落纯文本
      input: first.parts?.length ? first.parts : first.text,
      queuedEntry: first,
    });
  });
}
