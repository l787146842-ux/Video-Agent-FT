import { For } from 'solid-js';
import { FiFileText, FiZap } from 'solid-icons/fi';
import { openDocsPanel } from '@/stores/docs';
import type { ChatMessage } from '@/types';

/**
 * 用户消息内的 Skill / 文档引用块（Q5：块状展示在气泡内部，
 * 不再独立挂在气泡外；点击可查看对应 Skill/文档）。
 */
export function UserRefBlocks(props: { message: ChatMessage }) {
  return (
    <div class="msg-ref-blocks inline">
      <For each={props.message.skillBlocks || []}>
        {(name) => (
          <button
            type="button"
            class="msg-ref-block msg-ref-skill"
            title={`查看 Skill：${name}`}
            onClick={() => void openDocsPanel(name)}
          >
            <FiZap size={12} />
            <span class="msg-ref-name">{name}</span>
          </button>
        )}
      </For>
      <For each={props.message.docBlocks || []}>
        {(name) => (
          <button
            type="button"
            class="msg-ref-block msg-ref-doc"
            title={`查看文档：${name}`}
            onClick={() => void openDocsPanel(name)}
          >
            <FiFileText size={12} />
            <span class="msg-ref-name">{name}</span>
          </button>
        )}
      </For>
    </div>
  );
}
