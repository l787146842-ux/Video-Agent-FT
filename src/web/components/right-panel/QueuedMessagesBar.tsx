import { For, Show, createSignal, createEffect } from 'solid-js';
import {
  FiEdit2, FiExternalLink, FiMoreHorizontal, FiNavigation, FiTrash2,
} from 'solid-icons/fi';
import { chatState, chatActions } from '@/stores/chat';
import type { QueuedMessage } from '@/stores/chat';
import { state as studioState } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { submitMessage } from '@/lib/submit-message';
import { convActions } from '@/stores/conversations';
import { t } from '@/lib/locale';

/**
 * 排队引导区（输入框顶部）：Agent 推理中用户继续发送的消息在此排队，
 * 当前任务完成后由 ChatInput 的出队逻辑按序自动发出。
 *
 * 每条排队消息的操作：
 * - 引导（不打断语义）：移到队首并登记到运行中任务的轮间注入队列，
 *   后端在当前操作完成后的最近轮边界注入（不打断执行中的操作）；
 *   注入成功由 guidance_injected 事件渲染气泡并出队；
 *   任务不存在/已结束时保留队首，回落「任务结束后自动出队发送」。
 * - 删除：移出队列
 * - ⋯ 菜单：编辑消息（回填输入框）/ 在侧边聊天中打开（新建对话并发送）/ 关闭排队（清空队列）
 */
export function QueuedMessagesBar(props: {
  /** 编辑消息：把排队文本回填输入框（由 ChatInput 操作 contenteditable） */
  onEdit: (text: string) => void;
}) {
  /** 当前展开 ⋯ 菜单的排队条目 id */
  const [menuId, setMenuId] = createSignal('');
  /** 已点「引导」的条目 id：该条原位转圈圈等待轮间注入（不再顶部 toast 提醒） */
  const [guidedId, setGuidedId] = createSignal('');

  // （审核）：条目出队/清空后 spinner 终止，防转圈悬挂
  createEffect(() => {
    const id = guidedId();
    if (id && !chatState.queuedMessages.some((m) => m.id === id)) setGuidedId('');
  });

  /** 引导：队首优先 + 登记轮间注入（不打断当前操作；走统一入口 intent='guidance'） */
  function guide(item: QueuedMessage) {
    setGuidedId(item.id);
    void submitMessage('guidance', { input: item.text, queuedEntry: item });
  }

  /** 在侧边聊天中打开：新建对话窗口并把这条消息发过去（Agent 忙碌时禁止新建对话） */
  async function openInSideChat(item: QueuedMessage) {
    setMenuId('');
    if (studioState.agentBusy) {
      showToast(t('rp.queue.openSideBusy'), 'warning');
      return;
    }
    chatActions.removeQueuedMessage(item.id);
    const ok = await convActions.create();
    if (!ok) {
      chatActions.enqueueMessage(item); // 新建失败放回队列，消息不丢
      return;
    }
    void submitMessage('queued', { input: item.parts?.length ? item.parts : item.text, queuedEntry: item });
  }

  function closeQueue() {
    chatActions.clearQueuedMessages();
    setMenuId('');
    showToast(t('rp.queue.cleared'), 'info');
  }

  return (
    <Show when={chatState.queuedMessages.length > 0}>
      {/* 排队区增删/引导态变更对读屏器可闻；Agent 忙碌时标 aria-busy */}
      <div class="queued-bar" aria-live="polite" aria-busy={chatState.isStreaming}>
        <div class="queued-bar-header">
          <span class="queued-bar-title">{t('rp.queue.title')}</span>
          <button
            type="button"
            class="queued-bar-clear"
            title={t('rp.queue.closeQueueTitle')}
            onClick={closeQueue}
          >
            {t('rp.queue.closeQueue')}
          </button>
        </div>
        <For each={chatState.queuedMessages}>
          {(item) => (
            <div class="queued-chip">
              <Show when={guidedId() === item.id}>
                <span class="queued-spin" title={t('rp.queue.guideSpinner')} />
              </Show>
              <span class="queued-chip-text" title={item.displayText}>
                {item.displayText}
              </span>
              <div class="queued-chip-actions">
                <button
                  type="button"
                  class="queued-action queued-action-guide"
                  title={t('rp.queue.guideTitle')}
                  onClick={() => guide(item)}
                >
                  <FiNavigation size={11} />
                  {t('rp.queue.guide')}
                </button>
                <button
                  type="button"
                  class="queued-action"
                  onClick={() => chatActions.removeQueuedMessage(item.id)}
                >
                  <FiTrash2 size={11} />
                  {t('rp.queue.delete')}
                </button>
                <div class="queued-more-wrap">
                  <button
                    type="button"
                    class="queued-action queued-more-btn"
                    title={t('rp.queue.more')}
                    onClick={() => setMenuId(menuId() === item.id ? '' : item.id)}
                  >
                    <FiMoreHorizontal size={13} />
                  </button>
                  <Show when={menuId() === item.id}>
                    <div class="queued-more-menu">
                      <button
                        type="button"
                        onClick={() => {
                          setMenuId('');
                          chatActions.removeQueuedMessage(item.id);
                          props.onEdit(item.text);
                        }}
                      >
                        <FiEdit2 size={12} />
                        {t('rp.queue.edit')}
                      </button>
                      <button type="button" onClick={() => void openInSideChat(item)}>
                        <FiExternalLink size={12} />
                        {t('rp.queue.openSide')}
                      </button>
                      <button type="button" onClick={closeQueue}>
                        <FiTrash2 size={12} />
                        {t('rp.queue.closeQueue')}
                      </button>
                    </div>
                  </Show>
                </div>
              </div>
            </div>
          )}
        </For>
      </div>
    </Show>
  );
}
