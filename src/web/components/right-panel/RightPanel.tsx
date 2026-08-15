import { For, Show } from 'solid-js';
import { FiPlus, FiX } from 'solid-icons/fi';
import { ChatFeed } from './ChatFeed';
import { ChatInput } from './ChatInput';
import { state } from '@/stores/studio';
import { convState, convActions } from '@/stores/conversations';
import { showToast } from '@/stores/toast';
import { useSplitter } from '@/hooks/use-splitter';
import { t } from '@/lib/locale';

/**
 * 右侧聊天面板（对齐旧版布局）：
 * 顶部单栏（多对话标签 + 新建 + 状态点）
 * → 消息流 → 拖拽把手（上下拖动调输入框高度，100-400px）→ 一体化输入区
 * 多对话规则：≥2 个对话时任意关闭；仅剩 1 个时不可关闭（不渲染关闭钮）。
 */
export default function RightPanel() {
  const inputSplit = useSplitter(150, {
    axis: 'y',
    min: 100,
    max: 400,
    invert: true,
    storageKey: 'splitChatInput',
  });

  /** Agent 回复中禁止新建/切换/关闭对话（后端写入活跃对话，避免串话） */
  function busyGuard(): boolean {
    if (state.agentBusy) {
      showToast(t('rp.conv.busyGuard'), 'warning');
      return true;
    }
    return false;
  }

  function handleCreate() {
    if (busyGuard()) return;
    void convActions.create();
  }

  function handleActivate(id: string) {
    if (busyGuard()) return;
    void convActions.activate(id);
  }

  function handleClose(id: string) {
    if (busyGuard()) return;
    void convActions.close(id);
  }

  return (
    <div class="panel-column">
      {/* 顶部单栏：多对话标签选择 + 新建对话 + 状态点（已去掉 Agent 标题行） */}
      <div class="conv-tabs">
        <For each={convState.list}>
          {(conv) => (
            <div
              role="tab"
              aria-selected={conv.id === convState.activeId}
              class={`conv-tab ${conv.id === convState.activeId ? 'active' : ''}`}
              title={conv.title}
              onClick={() => handleActivate(conv.id)}
            >
              <span class="conv-tab-title">{conv.title}</span>
              <Show when={convState.list.length > 1}>
                <button
                  type="button"
                  class="conv-tab-close"
                  title={t('rp.conv.close')}
                  onClick={(e) => { e.stopPropagation(); handleClose(conv.id); }}
                >
                  <FiX size={12} />
                </button>
              </Show>
            </div>
          )}
        </For>
        <div class="conv-tabs-actions">
          <button type="button" class="conv-tabs-add" title={t('rp.conv.create')} onClick={handleCreate}>
            <FiPlus size={13} />
          </button>
          <span
            class={`agent-status-dot ${state.agentBusy ? 'busy' : ''}`}
            title={state.agentBusy ? t('rp.header.busy') : t('rp.header.idle')}
          />
        </div>
      </div>

      <ChatFeed />

      {/* 输入区与消息区之间的拖拽分隔线（旧版 chat-resize-handle） */}
      <div
        class={`chat-resize-handle ${inputSplit.dragging() ? 'dragging' : ''}`}
        title={t('rp.header.resizeHint')}
        onMouseDown={(e) => inputSplit.onMouseDown(e)}
      />

      <div class="chat-input-shell" style={{ height: `${inputSplit.size()}px` }}>
        <ChatInput />
      </div>
    </div>
  );
}
