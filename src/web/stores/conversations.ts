/**
 * 多对话状态管理（同一项目多个对话窗口）
 * 标签栏数据来自后端 /api/conversations（仅 id/title 元信息）。
 * E-2 消息单一来源：convState 不持有消息副本，消息唯一存于 chat store；
 * 切换/新建/关闭/分支后活跃对话变化时，经 GET /conversations/{id}/messages
 * 单独装载目标对话历史；刷新/重连路径由状态快照顶层 chatMessages 承载。
 * 标签栏元信息的唯一事实源 = conversations REST 接口 + 启动/切项目快照；
 * SSE 任务快照不得回写对话列表（任务专属实例的清单冻结于起任务时刻）。
 */
import { createStore, produce } from 'solid-js/store';
import type { Conversation, ServerStateSnapshot } from '@/types';
import {
  createConversation as apiCreate,
  deleteConversation as apiDelete,
  activateConversation as apiActivate,
  getConversationMessages as apiMessages,
  type ConversationsPayload,
} from '@/api/conversations';
import { chatActions } from './chat';
import { showToast } from './toast';

export interface ConversationsState {
  list: Conversation[];
  activeId: string;
}

const [convState, setConvState] = createStore<ConversationsState>({
  list: [],
  activeId: '',
});

/** 后端 payload → store；loadActiveMessages 且活跃对话变化时经
 * 「按会话拉消息」接口装载目标对话历史（消息单一来源，E-2） */
async function applyPayload(
  payload: ConversationsPayload,
  loadActiveMessages: boolean,
): Promise<void> {
  const prevActive = convState.activeId;
  setConvState(produce((s) => {
    s.list = payload.conversations || [];
    s.activeId = payload.active_conversation_id || '';
  }));
  if (!loadActiveMessages) return;
  const targetId = convState.activeId;
  // 活跃对话未变（如关闭非活跃对话）：chat store 已持有该对话消息，
  // 不重载（避免冲掉本地流式状态）
  if (!targetId || targetId === prevActive) return;
  try {
    const data = await apiMessages(targetId);
    // 并发兜底：响应回来时活跃对话已再次切换，丢弃过期结果
    if (convState.activeId !== targetId) return;
    chatActions.loadMessages(data.messages || []);
  } catch (e) {
    if (convState.activeId === targetId) chatActions.loadMessages([]);
    showToast(`装载对话消息失败：${(e as Error).message}`, 'error');
  }
}

export const convActions = {
  /** 初始加载 / 项目切换：从状态快照装载（快照无 conversations 时清空标签栏；
   * 快照对话仅元信息，活跃消息由调用方经 snapshot.chatMessages 灌入 chat store） */
  loadFromSnapshot(snapshot: ServerStateSnapshot | null) {
    const convs = snapshot?.conversations;
    if (!Array.isArray(convs) || convs.length === 0) {
      setConvState({ list: [], activeId: '' });
      return;
    }
    setConvState(produce((s) => {
      s.list = convs;
      s.activeId = snapshot?.activeConversationId || convs[0].id;
    }));
  },

  /** 整态快照同步对话元信息（仅启动/切项目等权威快照路径；
   * SSE 任务快照禁用——见文件头注释）；快照对话不含消息副本，
   * 消息唯一来源 = chat store，此处不重载 chat */
  syncFromServer(snapshot: ServerStateSnapshot) {
    const convs = snapshot.conversations;
    if (!Array.isArray(convs) || convs.length === 0) return;
    setConvState(produce((s) => {
      s.list = convs;
      s.activeId = snapshot.activeConversationId || s.activeId;
    }));
  },

  /** B11：分支操作后整体应用后端 payload（含分支消息装载） */
  async applyPayload(payload: ConversationsPayload): Promise<void> {
    await applyPayload(payload, true);
  },

  /** 新建对话（+ 号）：成功后切换到空白新对话 */
  async create(): Promise<boolean> {
    try {
      const payload = await apiCreate();
      await applyPayload(payload, true);
      return true;
    } catch (e) {
      showToast(`新建对话失败：${(e as Error).message}`, 'error');
      return false;
    }
  },

  /** 切换活跃对话：经按会话拉消息接口装载目标对话的历史消息 */
  async activate(id: string) {
    if (id === convState.activeId) return;
    try {
      const payload = await apiActivate(id);
      await applyPayload(payload, true);
    } catch (e) {
      showToast(`切换对话失败：${(e as Error).message}`, 'error');
    }
  },

  /** 关闭对话（仅剩一个时不允许，前端不渲染关闭钮 + 后端兜底） */
  async close(id: string) {
    if (convState.list.length <= 1) return;
    try {
      const payload = await apiDelete(id);
      await applyPayload(payload, true);
    } catch (e) {
      showToast(`关闭对话失败：${(e as Error).message}`, 'error');
    }
  },
};

export { convState, setConvState };
