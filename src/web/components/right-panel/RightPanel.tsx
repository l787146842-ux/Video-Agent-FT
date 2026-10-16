import { For, Show, createSignal } from 'solid-js';
import { FiCpu, FiPlus, FiSearch, FiX } from 'solid-icons/fi';
import { ChatFeed } from './ChatFeed';
import { ChatInput } from './ChatInput';
import { ChatSearchBar } from './ChatSearchBar';
import { agentState, agentActions } from '@/stores/agent-state';
import { convState, convActions } from '@/stores/conversations';
import { showToast } from '@/stores/toast';
import { useSplitter } from '@/hooks/use-splitter';
import { t } from '@/lib/locale';
import { state, studioActions } from '@/stores/studio';
import { subagentActivity } from '@/stores/chat/subagent-actors';

/**
 * 右侧聊天面板（对齐旧版布局）：
 * 顶部单栏（子任务入口 + 多对话标签 + 新建 + 状态点）
 * → 消息流 → 拖拽把手（上下拖动调输入框高度，100-400px）→ 一体化输入区
 * 多对话规则：≥2 个对话时任意关闭；仅剩 1 个时不可关闭（不渲染关闭钮）。
 * 批 6-2 多会话并行：任务绑定对话后，忙碌时新建/切换对话不再拦截，
 * 仅拦截关闭「正忙的对话」（后端同口径 400 兜底）。
 *
 * 子任务入口（2026-10-16 用户裁决：自顶栏迁至会话标签栏**最前方**）：
 * 仅图标（无文字），点击 = 切中间面板到子任务视图 / 再点一次切回预览的开关；
 * 有子代理正在执行时**常闪**（判据单点 = subagentActivity().running），
 * 收尾（完成/中断）即停闪。
 */
export default function RightPanel() {
  /** 消息搜索/轮次跳转条展开态（会话标签栏下方） */
  const [showSearch, setShowSearch] = createSignal(false);
  const inputSplit = useSplitter(150, {
    axis: 'y',
    min: 100,
    max: 400,
    invert: true,
    storageKey: 'splitChatInput',
  });

  /** 子代理活动（闪烁判据；任一条目变化即重算） */
  const activity = () => subagentActivity();
  const subagentsActive = () => state.middleView === 'subagents';

  /** 子任务入口点击：开关语义——已在子任务视图则回预览，否则切过去 */
  function toggleSubagents(): void {
    studioActions.setMiddleView(subagentsActive() ? 'preview' : 'subagents');
  }

  /** 删忙对话守卫（批 6-2）：仅拦截关闭正忙的对话；新建/切换已解锁 */
  function handleClose(id: string) {
    if (agentActions.isConvBusy(id)) {
      showToast(t('rp.conv.busyGuard'), 'warning');
      return;
    }
    void convActions.close(id);
  }

  return (
    <div class="panel-column">
      {/* 顶部单栏：子任务图标入口 + 多对话标签选择 + 新建对话 + 状态点 */}
      <div class="conv-tabs" role="tablist" aria-label="对话标签">
        {/* 子任务入口（仅图标，置会话标签栏最前）：点击 = 切子任务视图 / 再点回预览 */}
        <button
          type="button"
          class={`conv-subagents${subagentsActive() ? ' active' : ''}`}
          classList={{ running: activity().running }}
          title={t('rp.subagents.entry')}
          aria-label={t('rp.subagents.entry')}
          aria-pressed={subagentsActive()}
          data-testid="subagents-entry"
          onClick={toggleSubagents}
        >
          <FiCpu size={14} />
          {/* 执行中常闪（收尾即停）；单条状态点与图标同生命周期 */}
          <Show when={activity().running}>
            <span class="conv-subagents-pulse" aria-hidden="true" />
          </Show>
        </button>
        <For each={convState.list}>
          {(conv) => (
            <div
              role="tab"
              aria-selected={conv.id === convState.activeId}
              class={`conv-tab ${conv.id === convState.activeId ? 'active' : ''}`}
              title={conv.title}
              onClick={() => void convActions.activate(conv.id)}
            >
              {/* 批 6-2 角标：运行中（任务绑定该对话）/ 后台完成未读 */}
              <Show when={agentActions.isConvBusy(conv.id)}>
                <span class="conv-tab-badge running" title={t('rp.conv.running')} />
              </Show>
              <Show when={!agentActions.isConvBusy(conv.id) && agentState.unread[conv.id]}>
                <span class="conv-tab-badge unread" title={t('rp.conv.unread')} />
              </Show>
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
          <button
            type="button"
            class={`conv-tabs-add${showSearch() ? ' active' : ''}`}
            title={t('rp.search.open')}
            aria-pressed={showSearch()}
            onClick={() => setShowSearch((v) => !v)}
          >
            <FiSearch size={13} />
          </button>
          <button type="button" class="conv-tabs-add" title={t('rp.conv.create')} onClick={() => void convActions.create()}>
            <FiPlus size={13} />
          </button>
          <span
            class={`agent-status-dot ${agentState.agentBusy ? 'busy' : ''}`}
            title={agentState.agentBusy ? t('rp.header.busy') : t('rp.header.idle')}
          />
        </div>
      </div>

      {/* 消息搜索/轮次跳转条（标签栏与消息流之间展开） */}
      <Show when={showSearch()}>
        <ChatSearchBar onClose={() => setShowSearch(false)} />
      </Show>

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
