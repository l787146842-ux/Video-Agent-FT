import { For, Show } from 'solid-js';
import { t } from '@/lib/locale';
import type { ChatMessage } from '@/types';

/**
 * 记忆命中可视化（批6 拆分自 ChatMessageItem）：
 * 本轮 Agent 参考了哪些长期记忆（折叠展示）。
 */
export function MemoryHits(props: { message: ChatMessage }) {
  const hits = () => props.message.memoryHits || [];
  return (
    <Show when={hits().length > 0}>
      <details class="msg-memory-hits">
        <summary>{t('rp.msg.memoryRefs', { count: hits().length })}</summary>
        <For each={hits()}>
          {(h) => (
            <div class="memory-hit-line">
              <span class="memory-hit-date">{h.date}</span>
              {h.content}
            </div>
          )}
        </For>
      </details>
    </Show>
  );
}
