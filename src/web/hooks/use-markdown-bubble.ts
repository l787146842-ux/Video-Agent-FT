/**
 * markdown 气泡增强 hook：代码块按需高亮补刷 + 复制点击委托。
 * StreamingBubble（流式尾段）与 ChatMessageItem（最终消息）共用同一接线，
 * 高亮 chunk 仅在气泡内实际出现代码块时才动态拉取。
 */
import { createSignal, createEffect } from 'solid-js';

export function useMarkdownBubble(text: () => string) {
  const [el, setEl] = createSignal<HTMLDivElement>();
  createEffect(() => {
    void text(); // 文本变化 → innerHTML 重刷后对未处理块补刷
    const node = el();
    // 先探测再拉 chunk：无代码块的消息不触发高亮包加载
    if (node?.querySelector('pre > code:not([data-hl])')) {
      void import('@/lib/code-highlight').then(({ highlightBlocks }) => highlightBlocks(node));
    }
  });
  return { el, setEl };
}
