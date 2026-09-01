/**
 * 任务级副作用路由面（批 6-2 多会话并行，自 hooks/use-sse.ts 切出）：
 * 每个后台任务一份 fx——事件时刻按「任务对话 == 当前活跃对话」分流：
 * live → 实时渲染进聊天区；shadow（后台对话）→ 不碰聊天区/流式态，
 * 只维护忙态角标、终态置未读；故事板共享面恒同步（项目状态共享，
 * 只有对话视图隔离；对话元信息仅活跃任务快照路径同步，防串）。
 */
import { chatActions } from '@/stores/chat';
import { agentActions } from '@/stores/agent-state';
import { convState, convActions } from '@/stores/conversations';
import { studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { refreshHistoryStatus } from '@/stores/history';
import { applyFallbackModel } from '@/stores/agent-prefs';
import { requestInsertMedia } from '@/lib/chat/chat-input-bridge';
import type { SseEventFx, SseChatFx } from '@/lib/sse-events';
import { t } from '@/lib/locale';

/** 事件是否实时渲染（任务对话 = 当前活跃对话；'' 键旧路径恒视为活跃） */
export function isLiveConv(convId: string): boolean {
  return convId === '' || convId === (convState.activeId || '');
}

/** 静默聊天写面：后台对话任务的事件不进聊天区；终态置未读（角标提示） */
function makeShadowChat(convId: string): SseChatFx {
  const noop = () => {};
  const notify = (note: string) => {
    agentActions.markUnread(convId);
    showToast(note, 'info');
  };
  return {
    startStream: noop,
    streamError: () => notify(t('rp.parallel.bgFailed')),
    setStatus: noop,
    setRoundProgress: noop,
    appendDelta: noop,
    appendReasoning: noop,
    toolStarted: noop,
    toolFinished: noop,
    docWritten: noop,
    addMessage: noop,
    removeQueuedMessage: noop,
    restoreStreamingState: noop,
    clearStreaming: () => { agentActions.markUnread(convId); },
    loadMessages: noop,
    applyDecisionForm: noop,
    finishStream: () => notify(t('rp.parallel.bgDone')),
    cancelStream: () => notify(t('rp.parallel.bgStopped')),
  };
}

/** 按任务构建路由式 fx：切换活跃对话即时改变分流（无需重建连接） */
export function makeRoutedTaskFx(
  convId: string,
  taskId: string,
  signals: {
    setStreaming(v: boolean): void;
    setError(m: string | null): void;
  },
): SseEventFx {
  const shadowChat = makeShadowChat(convId);
  return {
    chat: new Proxy(chatActions, {
      get(target, prop: keyof SseChatFx) {
        if (isLiveConv(convId)) return target[prop];
        return shadowChat[prop];
      },
    }) as SseChatFx,
    setStreaming: (v) => { if (isLiveConv(convId)) signals.setStreaming(v); },
    setErrorText: (m) => { if (isLiveConv(convId)) signals.setError(m); },
    setAgentBusy: (v) => {
      if (v) agentActions.setConvBusy(convId, taskId);
      else agentActions.clearConvBusy(convId);
    },
    syncSnapshot: (s) => {
      studioActions.syncFromServer(s);
      if (isLiveConv(convId)) convActions.syncFromServer(s);
    },
    markBoardApplied: () => studioActions.markBoardApplied(),
    applyFallbackModel: (provider, model) => {
      if (isLiveConv(convId)) applyFallbackModel(provider, model);
    },
    toast: (msg, level) => showToast(msg, level),
    insertMedia: (media) => { if (isLiveConv(convId)) requestInsertMedia(media); },
    refreshHistory: () => { void refreshHistoryStatus(); },
    now: () => Date.now(),
  };
}
