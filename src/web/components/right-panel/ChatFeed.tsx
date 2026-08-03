import { createEffect, createSignal, For, Show, onCleanup } from 'solid-js';
import { chatState } from '@/stores/chat';
import { ChatMessageItem } from './ChatMessageItem';
import { StreamingIndicator } from './StreamingIndicator';

/** 判断是否接近底部（阈值 80px） */
function isNearBottom(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
}

/**
 * 聊天消息流：<For> keyed 列表 + 智能自动滚底
 * 用户手动上滚时不强制拉底，回到底部后恢复自动滚动。
 */
export function ChatFeed() {
  let feedRef: HTMLDivElement | undefined;
  const [autoScroll, setAutoScroll] = createSignal(true);
  let rafId: number | undefined;

  // 监听用户滚动：离开底部时暂停自动滚动
  function onScroll() {
    if (feedRef) setAutoScroll(isNearBottom(feedRef));
  }

  // 消息数或流式文本变化时滚动到底部（仅 autoScroll 开启时）
  createEffect(() => {
    void chatState.messages.length;
    void chatState.streamingText;
    void chatState.streamingStatus;
    if (!autoScroll()) return;
    if (rafId !== undefined) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(() => {
      rafId = undefined;
      if (feedRef) feedRef.scrollTop = feedRef.scrollHeight;
    });
  });

  onCleanup(() => { if (rafId !== undefined) cancelAnimationFrame(rafId); });

  return (
    <div ref={feedRef} data-testid="chat-feed" class="chat-feed" onScroll={onScroll}>
      <For each={chatState.messages}>
        {(msg, idx) => (
          <ChatMessageItem
            message={msg}
            isLast={idx() === chatState.messages.length - 1 && !chatState.isStreaming}
          />
        )}
      </For>

      {/* 流式中的临时 agent 消息 */}
      <Show when={chatState.isStreaming && chatState.streamingText}>
        <ChatMessageItem
          message={{ sender: 'agent', text: chatState.streamingText, modelName: chatState.streamingModel || undefined }}
          isLast={false}
        />
      </Show>

      <StreamingIndicator />

      <Show when={!chatState.messages.length && !chatState.isStreaming}>
        <div class="empty-state centered roomy">
          和 Agent 聊聊，让它帮你规划故事板
        </div>
      </Show>
    </div>
  );
}
