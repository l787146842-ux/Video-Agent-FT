import { For, Show } from 'solid-js';
import { FiFileText, FiVideo, FiX } from 'solid-icons/fi';
import { state, studioActions } from '@/stores/studio';
import { t } from '@/lib/locale';

/**
 * 待发送附件 chips（媒体已内联到编辑器，这里主要是文档类附件）。
 * 从 ChatInput 拆出以保持主组件精简。
 */
export function PendingAttachmentBar() {
  return (
    <Show when={state.pendingAttachments.length > 0}>
      <div class="pending-attachments" style={{ display: 'flex' }}>
        <For each={state.pendingAttachments}>
          {(att) => (
            <div class={`attachment-chip ${att.type === 'image' && att.url ? 'attachment-img-chip' : ''}`}>
              <Show
                when={att.type === 'image' && att.url}
                fallback={att.type === 'video' ? <FiVideo size={12} /> : <FiFileText size={12} />}
              >
                <img src={att.url} alt={att.name} class="attachment-thumb" />
              </Show>
              <span class="attachment-name">{att.name}</span>
              <button
                type="button"
                class="attachment-remove"
                title={t('rp.attachment.remove')}
                onClick={() => studioActions.removePendingAttachment(att.id)}
              >
                <FiX size={10} />
              </button>
            </div>
          )}
        </For>
      </div>
    </Show>
  );
}
