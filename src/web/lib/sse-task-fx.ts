/**
 * 任务级副作用路由面（批 6-2 多会话并行，自 hooks/use-sse.ts 切出）：
 * 每个后台任务一份 fx——事件时刻按「任务对话 == 当前活跃对话」分流：
 * live → 实时渲染进聊天区；shadow（后台对话）→ 不碰聊天区/流式态，
 * 只维护忙态角标、终态置未读；故事板共享面恒同步（项目状态共享，
 * 只有对话视图隔离）。对话元信息不走任务快照同步：任务专属状态实例的
 * 对话列表冻结于起任务时刻，覆盖会把新建的对话从标签栏抹掉；
 * 标签栏唯一事实源 = conversations REST 接口 + 启动/切项目快照。
 */
import { chatActions } from '@/stores/chat';
import { agentActions } from '@/stores/agent-state';
import { convState } from '@/stores/conversations';
import { studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { refreshHistoryStatus } from '@/stores/history';
import { applyFallbackModel } from '@/stores/agent-prefs';
import { requestInsertMedia } from '@/lib/chat/chat-input-bridge';
import { getConversationMessages } from '@/api/conversations';
import { adjustScopeActions, threadConvIdOf } from '@/stores/adjust-scopes';
import type { ScopeToolEntry } from '@/stores/adjust-scopes';
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
      // 只同步故事板；对话列表不得用任务快照覆盖（任务专属实例的对话清单
      // 是起任务时的分叉，缺其后新建/删除的对话，覆盖会缩标签栏）
      studioActions.syncFromServer(s);
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

/** replay 工具条目 → 线程视图工具条目（字段同构，只取浮窗所需面） */
function replayTools(
  tools: Array<Partial<ScopeToolEntry> & Record<string, unknown>> | undefined,
): ScopeToolEntry[] {
  return (tools || []).map((tool) => ({
    id: String(tool.id || ''),
    name: String(tool.name || ''),
    summary: String(tool.summary || ''),
    status: tool.status === 'done' || tool.status === 'failed' ? tool.status : 'running',
    startedAtMs: Number(tool.started_at_ms ?? tool.startedAtMs ?? 0) || Date.now(),
    elapsedMs: Number(tool.elapsed_ms ?? tool.elapsedMs ?? 0) || undefined,
    resultSummary: String(tool.result_summary ?? tool.resultSummary ?? '') || undefined,
  }));
}

/**
 * scope 任务专用事件分流面（微调真子对话，批 S3）：与 makeRoutedTaskFx
 * 同构但结构性不进聊天区——不经过 isLiveConv/chatActions Proxy，
 * delta/status/tool 系事件/终态/图卡全部写入 adjust-scopes store（浮窗渲染）。
 * 故事板共享面恒同步照旧；忙态/未读角标按线程对话 id 登记。
 */
export function makeScopeTaskFx(
  scopeKey: string,
  taskId: string,
  signals: { setStreaming(v: boolean): void; setError(m: string | null): void },
): SseEventFx {
  void signals; // scope 不动全局流式/错误信号（属主聊天区）
  const convIdOf = () => threadConvIdOf(scopeKey);
  /** 终态提示：未读角标按线程 id 复用 markUnread 口径（浮窗/左栏消费） */
  const markTerminal = () => { const cid = convIdOf(); if (cid) agentActions.markUnread(cid); };
  const chat: SseChatFx = {
    startStream: () => {},
    streamError: (payload) => {
      adjustScopeActions.appendEvent(scopeKey, { kind: 'error', message: payload.message });
      markTerminal();
    },
    setStatus: (text) => adjustScopeActions.appendEvent(scopeKey, { kind: 'status', text }),
    appendDelta: (text) => adjustScopeActions.appendEvent(scopeKey, { kind: 'delta', text }),
    appendReasoning: (text) => adjustScopeActions.appendEvent(scopeKey, { kind: 'reasoning', text }),
    toolStarted: (id, name, summary) => {
      adjustScopeActions.appendEvent(scopeKey, { kind: 'tool_started', id, name, summary });
    },
    toolFinished: (id, ok, elapsedMs, resultSummary) => {
      adjustScopeActions.appendEvent(scopeKey, {
        kind: 'tool_finished', id, ok, elapsedMs, resultSummary,
      });
    },
    docWritten: () => {}, // 文档卡归文档区（refreshHistory 已在终态刷新）
    addMessage: (message) => adjustScopeActions.appendEvent(scopeKey, { kind: 'message', message }),
    removeQueuedMessage: () => {}, // 线程无排队区（多轮续聊直提）
    restoreStreamingState: (p) => {
      adjustScopeActions.appendEvent(scopeKey, {
        kind: 'replay',
        snapshot: {
          text: p.text, reasoning: p.reasoning, statusText: p.statusText,
          tools: replayTools(p.tools as Array<Partial<ScopeToolEntry> & Record<string, unknown>> | undefined),
        },
      });
    },
    clearStreaming: () => markTerminal(),
    // replay 终态快照的 chatMessages 属任务实例的活跃对话（主对话），
    // 不是线程历史——不得直接装入线程视图；改按线程 id 走消息
    // 单一来源 API 装载（后端终态已冲刷落盘，任务 #19）
    loadMessages: () => {
      const cid = convIdOf();
      if (!cid) return;
      void getConversationMessages(cid)
        .then((r) => adjustScopeActions.loadThreadMessages(scopeKey, r.messages))
        .catch(() => { /* 装载失败不阻断终态收尾；下次重开入口会再装 */ });
    },
    applyDecisionForm: () => {}, // 决策表单浮窗二期（方案风险表已登记）
    finishStream: (payload) => {
      adjustScopeActions.appendEvent(scopeKey, { kind: 'done', payload });
      markTerminal();
    },
    cancelStream: () => {
      adjustScopeActions.appendEvent(scopeKey, { kind: 'stopped' });
      markTerminal();
    },
  };
  return {
    chat,
    setStreaming: () => {},
    setErrorText: () => {},
    setAgentBusy: (v) => {
      const cid = convIdOf();
      if (!cid) return;
      if (v) agentActions.setConvBusy(cid, taskId);
      else agentActions.clearConvBusy(cid);
    },
    syncSnapshot: (s) => {
      // 故事板共享面恒同步（结果写回故事板复用 actions_applied/syncSnapshot 回流）；
      // 对话列表不得经任务快照回写（同 makeRoutedTaskFx 口径）
      studioActions.syncFromServer(s);
    },
    markBoardApplied: () => studioActions.markBoardApplied(),
    applyFallbackModel: () => {}, // 降级不动主聊天区选择器（线程任务不感知）
    toast: (msg, level) => showToast(msg, level),
    insertMedia: () => {}, // 媒体不进主输入框；图卡经 done 载荷 chat_inserts 落线程
    refreshHistory: () => { void refreshHistoryStatus(); },
    now: () => Date.now(),
  };
}
