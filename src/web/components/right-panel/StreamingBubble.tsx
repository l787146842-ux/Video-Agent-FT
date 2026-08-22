import { createSignal, createEffect, onCleanup, Show } from 'solid-js';
import { chatState } from '@/stores/chat';
import { renderMarkdownIncremental, createIncrementalCache } from '@/lib/markdown-incremental';
import { handleCodeBlockClick } from '@/lib/code-copy';
import { useMarkdownBubble } from '@/hooks/use-markdown-bubble';

/** 流式 markdown 重渲染最小间隔（ms）：节流保留，增量解析在其上再降复杂度 */
const RENDER_INTERVAL = 120;

/**
 * 流式临时气泡：随 delta 累积的 agent 正文。
 * 增量渲染：已闭合段落（围栏外空行分界）缓存 HTML 不再重解析，
 * 每 tick 只增量 parse 尾段（未闭合代码围栏/进行中的表格整体留在尾段）；
 * 120ms 节流保留。闭合段的高亮升级由缓存异步回写并触发一次补渲染。
 * 代码块复制走容器级事件委托（innerHTML 重刷不丢交互）。
 * 流结束后由 ChatMessageItem 对正式消息做一次完整渲染（不影响最终排版）。
 */
export function StreamingBubble() {
  const [html, setHtml] = createSignal('');
  const cache = createIncrementalCache();
  // html 应用后对尾段代码块做 DOM 高亮（动态 import 按需拉高亮 chunk；缓存段已在字符串里带好）
  const bubble = useMarkdownBubble(html);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let lastRender = 0;

  function renderNow() {
    lastRender = Date.now();
    setHtml(renderMarkdownIncremental(chatState.streamingText, cache));
  }

  /** 节流调度：到点即渲，否则挂尾随定时器保证最后一个 delta 落地 */
  function scheduleRender() {
    const elapsed = Date.now() - lastRender;
    if (elapsed >= RENDER_INTERVAL) {
      if (timer !== undefined) {
        clearTimeout(timer);
        timer = undefined;
      }
      renderNow();
    } else if (timer === undefined) {
      timer = setTimeout(() => {
        timer = undefined;
        renderNow();
      }, RENDER_INTERVAL - elapsed);
    }
  }

  createEffect(() => {
    // 订阅流式文本（读取即建立依赖）
    void chatState.streamingText;
    scheduleRender();
  });

  // 闭合段高亮升级回写缓存 → 补渲染一次（升级即最终形态，此后恒命中缓存）
  onCleanup(cache.subscribe(scheduleRender));

  onCleanup(() => {
    if (timer !== undefined) clearTimeout(timer);
  });

  return (
    <Show when={chatState.isStreaming && chatState.streamingText}>
      <div class="chat-msg agent">
        <Show when={chatState.streamingModel}>
          <span class="msg-author">{chatState.streamingModel}</span>
        </Show>
        <div
          class="chat-bubble chat-markdown"
          ref={bubble.setEl}
          innerHTML={html()}
          onClick={handleCodeBlockClick}
        />
      </div>
    </Show>
  );
}
