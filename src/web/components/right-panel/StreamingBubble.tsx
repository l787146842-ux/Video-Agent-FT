import { createSignal, createEffect, onCleanup, Show } from 'solid-js';
import { chatState } from '@/stores/chat';
import { renderMarkdown } from '@/lib/markdown';

/** 流式 markdown 重渲染最小间隔（ms）：每个 delta 全量解析是 O(n²) 掉帧的主因 */
const RENDER_INTERVAL = 120;

/**
 * 流式临时气泡：随 delta 累积的 agent 正文。
 * markdown 渲染按时间节流（最多每 120ms 一次全量解析），
 * 流结束后由 ChatMessageItem 对正式消息做一次完整渲染（不影响最终排版）。
 */
export function StreamingBubble() {
  const [html, setHtml] = createSignal('');
  let timer: ReturnType<typeof setTimeout> | undefined;
  let lastRender = 0;

  function renderNow() {
    lastRender = Date.now();
    setHtml(renderMarkdown(chatState.streamingText));
  }

  createEffect(() => {
    // 订阅流式文本（读取即建立依赖）
    void chatState.streamingText;
    const elapsed = Date.now() - lastRender;
    if (elapsed >= RENDER_INTERVAL) {
      if (timer !== undefined) {
        clearTimeout(timer);
        timer = undefined;
      }
      renderNow();
    } else if (timer === undefined) {
      // 尾随调用：保证最后一个 delta 也被渲染
      timer = setTimeout(() => {
        timer = undefined;
        renderNow();
      }, RENDER_INTERVAL - elapsed);
    }
  });

  onCleanup(() => {
    if (timer !== undefined) clearTimeout(timer);
  });

  return (
    <Show when={chatState.isStreaming && chatState.streamingText}>
      <div class="chat-msg agent">
        <Show when={chatState.streamingModel}>
          <span class="msg-author">{chatState.streamingModel}</span>
        </Show>
        <div class="chat-bubble chat-markdown" innerHTML={html()} />
      </div>
    </Show>
  );
}
