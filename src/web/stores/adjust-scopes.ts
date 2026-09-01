/**
 * 微调真子对话线程注册表（批 S3；方案「微调真子对话对齐 Flova」）。
 *
 * 每张被微调的草稿卡对应一个后端隐藏线程对话（POST /api/conversations/thread
 * 幂等取/建）。本 store 持有线程视图数据（历史消息 + 当前轮流式累积）与运行
 * 登记；事件写入唯一通道 = appendEvent（scope 专用 fx 见 lib/sse-task-fx，
 * 结构性不进聊天区）。浮窗组件（批 S4）消费 open 标志与 messages。
 * 视图模型与事件归约拆在 stores/adjust-scope-events.ts（行数红线）。
 */
import { createStore, produce } from 'solid-js/store';
import type { AgentChatRequest, ChatMessage } from '@/types';
import { getOrCreateAdjustThread } from '@/api/conversations';
import { ApiError } from '@/api/client';
import { agentActions } from './agent-state';
import { agentProvider, agentModel } from './agent-prefs';
import { state } from './studio';
import { showToast } from './toast';
import { streamAgentChat } from '@/hooks/use-sse';
import { CHAT_HISTORY_WINDOW, uid } from '@/lib/utils';
import { t } from '@/lib/locale';
import {
  applyScopeEvent, emptyStreaming,
  type AdjustScopeTarget, type ScopeEvent, type ScopeThread,
} from './adjust-scope-events';

export type {
  AdjustScopeTarget, ScopeEvent, ScopeThread,
  ScopeToolEntry, ScopeStreamingView, ScopeThreadStatus,
} from './adjust-scope-events';

/** 线程注册表：键 = 目标草稿卡 id（同卡同线程；draft id 全局唯一不撞） */
const [adjustScopes, setAdjustScopes] = createStore<Record<string, ScopeThread>>({});

/** 并发取/建线程的在途去重（连点入口只打一次幂等接口） */
const inflight = new Map<string, Promise<boolean>>();

/** 幂等取/建线程并装载历史（失败返回 false，入口据此回落旧路径） */
async function loadThread(target: AdjustScopeTarget): Promise<boolean> {
  try {
    const data = await getOrCreateAdjustThread({ ...target });
    // 契约字段缺失同样视为不可用（探测口径：接口 4xx 或契约字段）
    if (!data || !data.conversation_id) return false;
    setAdjustScopes(produce((s) => {
      const prev = s[target.draft_id];
      // 运行中重开：保留任务登记与流式累积，不冲掉进行中的轮
      const keep = prev && (prev.status === 'running' || prev.status === 'starting') ? prev : null;
      s[target.draft_id] = {
        scope: target,
        convId: data.conversation_id,
        open: true,
        messages: data.messages || [],
        taskId: keep ? keep.taskId : '',
        status: keep ? keep.status : 'idle',
        errorText: '',
        streaming: prev?.streaming.active ? prev.streaming : emptyStreaming(),
      };
    }));
    return true;
  } catch {
    return false;
  }
}

export const adjustScopeActions = {
  /** 打开线程（幂等装载历史 + 置 open；浮窗组件据此弹出） */
  async openThread(target: AdjustScopeTarget): Promise<boolean> {
    const key = target.draft_id;
    let pending = inflight.get(key);
    if (!pending) {
      pending = loadThread(target).finally(() => inflight.delete(key));
      inflight.set(key, pending);
    }
    const ok = await pending;
    if (ok) setAdjustScopes(key, 'open', true);
    return ok;
  },

  /** 关闭浮窗（仅隐藏，线程存活；批 S4 用） */
  closeThread(scopeKey: string) {
    if (adjustScopes[scopeKey]) setAdjustScopes(scopeKey, 'open', false);
  },

  /** 对象删除级联（二期子对话批 1）：元素被删后移除本注册表对应键；
   *  浮窗渲染依赖 open 键，键删除后若正开着随之关闭（后端线程已同帧硬删）。
   *  撤销恢复时线程随快照回来，重新打开入口会幂等重建登记。 */
  dropThread(scopeKey: string) {
    if (!adjustScopes[scopeKey]) return;
    inflight.delete(scopeKey);
    setAdjustScopes(produce((s) => {
      delete s[scopeKey];
    }));
  },

  /** 登记运行中任务（sendAdjust 建任务成功 / resume 忙态恢复时） */
  registerTask(scopeKey: string, taskId: string) {
    if (!adjustScopes[scopeKey]) return;
    setAdjustScopes(produce((s) => {
      s[scopeKey].taskId = taskId;
      s[scopeKey].status = 'running';
    }));
  },

  /**
   * 提交微调（真子对话）：用户气泡落线程 + 组装瘦身请求直调 streamAgentChat。
   * 不带主对话历史/附件/媒体清单/技能（服务端自线程装载历史为准）；
   * 同目标运行中拒重复提交。返回 false = 未受理（调用方保留输入）。
   */
  sendAdjust(target: AdjustScopeTarget, text: string): boolean {
    const trimmed = text.trim();
    const key = target.draft_id;
    const th = adjustScopes[key];
    if (!trimmed || !th?.convId) return false;
    if (th.taskId || th.status === 'running' || th.status === 'starting'
      || agentActions.isConvBusy(th.convId)) {
      showToast(t('rp.adjust.duplicate'), 'warning');
      return false;
    }
    const provider = agentProvider();
    const model = agentModel();
    if (!provider || !model) {
      showToast(t('rp.send.noProvider'), 'warning');
      return false;
    }
    // 用户气泡先落线程视图（乐观；失败时错误事件也落线程，主对话零痕迹）
    setAdjustScopes(produce((s) => {
      s[key].messages.push({ sender: 'user', text: trimmed });
      s[key].status = 'starting';
      s[key].errorText = '';
      s[key].open = true; // 提交后自动弹浮窗（=open）
    }));
    const request: AgentChatRequest = {
      message: trimmed,
      request_id: uid('req'),
      conversation_id: th.convId,
      project_id: state.projectId || '',
      provider,
      model,
      ms_model: provider === 'modelscope' ? model : '',
      // 线程历史窗口（后端 scope 请求改服务端装载，此处仅作兼容兜底）
      messages: adjustScopes[key].messages.slice(-CHAT_HISTORY_WINDOW).map((m) => (
        { role: m.sender === 'user' ? 'user' : 'assistant', content: m.text }
      )),
      selected_draft_id: target.draft_id,
      selected_type: target.cat,
      context_mode: 'studio',
      adjust_scope: { ...target },
    };
    void streamAgentChat(request, {
      scope: true,
      onTaskStarted: (taskId) => adjustScopeActions.registerTask(key, taskId),
    }).catch((err: unknown) => {
      const msg = err instanceof ApiError
        ? err.payload.message
        : ((err as Error).message || t('rp.adjust.failed'));
      adjustScopeActions.appendEvent(key, { kind: 'error', message: msg });
    });
    return true;
  },

  /** scope fx 事件写入：推进线程视图数据（浮窗渲染的唯一数据面） */
  appendEvent(scopeKey: string, ev: ScopeEvent): void {
    setAdjustScopes(produce((s) => {
      const th = s[scopeKey];
      if (!th) return;
      applyScopeEvent(th, ev);
    }));
  },

  /** replay 终态快照装载线程历史（消息单一来源口径，同主对话 loadMessages） */
  loadThreadMessages(scopeKey: string, messages: ChatMessage[]): void {
    if (!adjustScopes[scopeKey]) return;
    setAdjustScopes(scopeKey, 'messages', messages);
  },

  /** 测试复位/硬重置（同 agentActions.resetBusy 口径）；
   * 注：Solid setStore 对象参数是递归合并，须逐键删才能清空 */
  reset() {
    setAdjustScopes(produce((s) => {
      for (const k of Object.keys(s)) delete s[k];
    }));
    inflight.clear();
  },
};

/** 线程对话 id（忙态/未读角标按线程 id 登记）；未知键返回 '' */
export function threadConvIdOf(scopeKey: string): string {
  return adjustScopes[scopeKey]?.convId || '';
}

/** 线程对话 id → 注册表键（事件分流寻址）；未知返回 '' */
export function threadKeyOfConvId(convId: string): string {
  if (!convId) return '';
  for (const [key, th] of Object.entries(adjustScopes)) {
    if (th.convId === convId) return key;
  }
  return '';
}

/** 是否已知隐藏线程对话（标签栏过滤双保险 / resume 分流判定） */
export function isScopedConvId(convId: string): boolean {
  return threadKeyOfConvId(convId) !== '';
}

export { adjustScopes };
