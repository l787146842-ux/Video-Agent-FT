import { For, Show, type JSX } from 'solid-js';
import { safeUrl } from '@/lib/utils';
import type { RichContentPart } from '@/types';

/**
 * 用户消息富文本气泡：按 parts 顺序交错渲染文字与内联缩略图，
 * 还原用户在输入框里的排版，让对话记录与发送给 LLM 的顺序一致。
 * before（可选）：渲染在气泡内、parts 之前的内容（如 Skill/文档引用块，Q5）。
 */
export function RichBubble(props: {
  parts: RichContentPart[];
  onImageClick: (url: string) => void;
  before?: JSX.Element;
}) {
  function renderPart(part: RichContentPart) {
    if (part.type === 'text') {
      return <span class="rich-text">{part.text}</span>;
    }
    if (part.type === 'image') {
      return (
        <img
          class="bubble-inline-media"
          src={safeUrl(part.url)}
          alt={part.name}
          title={part.name}
          onClick={() => props.onImageClick(part.url)}
        />
      );
    }
    if (part.type === 'video') {
      const thumb = safeUrl(part.url);
      return (
        <span class="bubble-inline-media bubble-inline-video" title={part.name}>
          <Show when={thumb}>
            <video
              src={thumb.includes('#') ? thumb : `${thumb}#t=0.1`}
              muted
              playsinline
              preload="metadata"
            />
          </Show>
          <span class="inline-media-badge">▶</span>
          <span class="bubble-inline-name">{part.name}</span>
        </span>
      );
    }
    // audio
    return (
      <span class="bubble-inline-media bubble-inline-audio" title={part.name}>
        <span class="inline-media-audio">♬</span>
        <span class="bubble-inline-name">{part.name}</span>
      </span>
    );
  }

  return (
    <div class="chat-bubble chat-bubble-rich">
      <Show when={props.before != null}>{props.before}</Show>
      <For each={props.parts}>
        {(part) => renderPart(part)}
      </For>
    </div>
  );
}
