import { createEffect, createSignal, For, Show, onCleanup } from 'solid-js';
import { chatState } from '@/stores/chat';
import { t } from '@/lib/locale';
import { ChatMessageItem } from './ChatMessageItem';
import { StreamingIndicator } from './StreamingIndicator';
import { StreamingBubble } from './StreamingBubble';
import { AgentTimeline } from './AgentTimeline';

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

  /** 当前待回应的确认消息下标：最后一条 confirm 消息，且必须出现在最后一条
   * 用户消息之后（用户回应后旧确认不再可操作）。不能用「整体最后一条」判定：
   * 文档卡片/图片卡片会追加在确认消息之后，会把确认消息顶掉导致引导按钮不渲染。 */
  const confirmTargetIdx = () => {
    if (chatState.isStreaming) return -1;
    const msgs = chatState.messages;
    let lastUser = -1;
    for (let i = msgs.length - 1; i >= 0; i -= 1) {
      if (msgs[i].sender === 'user') { lastUser = i; break; }
    }
    for (let i = msgs.length - 1; i >= 0; i -= 1) {
      if (msgs[i].confirm) return i > lastUser ? i : -1;
    }
    return -1;
  };

  return (
    <div ref={feedRef} data-testid="chat-feed" class="chat-feed" onScroll={onScroll}>
      <For each={chatState.messages}>
        {(msg, idx) => (
          <ChatMessageItem
            message={msg}
            isLast={idx() === confirmTargetIdx()}
          />
        )}
      </For>

      {/* 流式过程时间线：深度思考/工具操作实时追加（完成并入消息 trace，不重复展示） */}
      <Show when={chatState.isStreaming}>
        <div class="chat-msg agent">
          <AgentTimeline
            reasoning={() => chatState.streamingReasoning}
            items={chatState.streamingTools}
            live
          />
        </div>
      </Show>

      {/* 流式中的临时 agent 消息（markdown 节流渲染，避免每个 delta 全量解析掉帧） */}
      <StreamingBubble />

      <StreamingIndicator />

      {/* 无消息时（如新建项目）：只在左上角淡显一句能力提示，不占对话流的完整消息卡片 */}
      <Show when={!chatState.messages.length && !chatState.isStreaming}>
        <div class="chat-feed-hint">{t('rp.feed.hint')}</div>
      </Show>
    </div>
  );
}
