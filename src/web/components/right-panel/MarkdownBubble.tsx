/**
 * agent 消息 markdown 气泡（自 ChatMessageItem 抽出）：全量渲染 + 代码块高亮补刷 + 复制委托。
 * 从 ChatMessageItem 抽出以控制其行数（铁律 10.1），流式气泡 StreamingBubble
 * 因走增量 HTML 通道不复用本组件，但复制/高亮接线完全同源。
 */
import { renderMarkdown } from '@/lib/markdown';
import { handleCodeBlockClick } from '@/lib/code-copy';
import { useMarkdownBubble } from '@/hooks/use-markdown-bubble';

export function MarkdownBubble(props: { text: string }) {
  const bubble = useMarkdownBubble(() => props.text);
  return (
    <div
      class="chat-bubble chat-markdown"
      ref={bubble.setEl}
      innerHTML={renderMarkdown(props.text)}
      onClick={handleCodeBlockClick}
    />
  );
}
