import { createSignal } from 'solid-js';
import type { SseEvent, SseDonePayload, AgentChatRequest } from '@/types';
import { chatActions } from '@/stores/chat';
import { convActions } from '@/stores/conversations';
import { studioActions, getProjectSession } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { refreshHistoryStatus } from '@/stores/history';
import { resolveErrorMessage } from '@/lib/i18n';
import { postAgentChatStream } from '@/api/sse';
import { requestInsertMedia } from '@/lib/chat-input-bridge';
import { uid } from '@/lib/utils';

/**
 * Agent 流式聊天（模块级单例）
 * 匹配后端 SSE 协议：type = status | delta | reasoning_delta | tool_started | tool_finished | done | error
 * 端点：POST /api/agent/chat/stream
 *
 * 任何组件/面板均可直接调用 streamAgentChat / stopAgentStream；
 * useAgentStream() 仅是响应式状态的薄封装。
 */

const [streaming, setStreaming] = createSignal(false);
const [error, setError] = createSignal<string | null>(null);

let abortController: AbortController | null = null;

/** 发起流时捕获项目会话纪元；流期间项目被切换后，
 * 旧项目的事件（尤其 done 携带的状态快照）一律丢弃，
 * 避免旧项目快照覆盖新项目故事板、旧回复流入新对话。 */
let streamSession = 0;

export async function streamAgentChat(request: AgentChatRequest): Promise<void> {
  if (streaming()) return;
  setStreaming(true);
  setError(null);
  streamSession = getProjectSession();
  studioActions.setAgentBusy(true);
  chatActions.startStream(request.model || '');
  abortController = new AbortController();

  try {
    const res = await postAgentChatStream(request, abortController.signal);

    if (!res.ok || !res.body) {
      const data = await res.json().catch(() => ({}));
      const body = data as Record<string, string>;
      // error_code → 中文友好提示（P2-17），无 code 回退 detail
      throw new Error(
        resolveErrorMessage(body.error_code, body.detail || `请求失败 (${res.status})`),
      );
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE 以 \n\n 分隔事件
      let idx: number;
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 2);

        if (!raw.startsWith('data:')) continue;
        const jsonStr = raw.slice(5).trim();
        if (jsonStr === '[DONE]') continue;

        let ev: SseEvent;
        try {
          ev = JSON.parse(jsonStr);
        } catch {
          continue;
        }

        handleEvent(ev);
      }
    }
  } catch (err) {
    if ((err as Error).name !== 'AbortError') {
      const msg = (err as Error).message || '未知错误';
      setError(msg);
      chatActions.streamError(msg);
    }
  } finally {
    setStreaming(false);
    studioActions.setAgentBusy(false);
    abortController = null;
  }
}

export function stopAgentStream(): void {
  if (abortController) {
    abortController.abort();
    abortController = null;
    chatActions.cancelStream();
  }
}

function handleEvent(ev: SseEvent) {
  // 项目已切换：旧项目流的全部事件直接丢弃
  if (streamSession !== getProjectSession()) return;
  switch (ev.type) {
    case 'status':
      chatActions.setStatus(ev.text || '');
      break;
    case 'delta':
      chatActions.appendDelta(ev.text || '');
      break;
    case 'reasoning_delta':
      // 深度思考增量：仅 UI 展示，不进下次上下文
      chatActions.appendReasoning(ev.text || '');
      break;
    case 'tool_started':
      chatActions.toolStarted(ev.id, ev.name, ev.summary);
      break;
    case 'tool_finished':
      chatActions.toolFinished(ev.id, ev.ok, ev.elapsed_ms || 0, ev.result_summary);
      break;
    case 'actions_applied': {
      // 逐步可见：每批操作执行完就同步最新状态快照，
      // 推理中就能看到新建的分组/写入的提示词，不必等全部完成
      const snapshot = ev.payload?.state;
      if (snapshot) {
        studioActions.syncFromServer(snapshot);
        convActions.syncFromServer(snapshot);
        studioActions.markBoardApplied();
      }
      break;
    }
    case 'done':
      handleDone(ev.payload);
      break;
    case 'error': {
      // error_code → 中文友好提示（P2-17），未知 code 回退原始 detail
      const msg = resolveErrorMessage(ev.error_code, ev.detail || ev.text || '服务端错误');
      setError(msg);
      chatActions.streamError(msg);
      break;
    }
  }
}

function handleDone(payload: SseDonePayload) {
  chatActions.finishStream(payload);
  // 同步后端状态快照到全局 store
  if (payload.state) {
    studioActions.syncFromServer(payload.state);
    // 多对话标签栏：刷新各对话消息与活跃态
    convActions.syncFromServer(payload.state);
  }
  // Agent 动作会压入后端 undo 栈，刷新撤销/重做指示位
  void refreshHistoryStatus();
  // Agent 把故事板媒体自动添加到对话输入框（insert_chat_media / storyboard_media_to_chat）
  const inserts = payload.chat_inserts || [];
  if (inserts.length) {
    const seen = new Set<string>();
    for (const it of inserts) {
      if (!it.url || seen.has(it.url)) continue;
      seen.add(it.url);
      requestInsertMedia({
        id: uid('im'), kind: it.kind, url: it.url,
        name: it.name || it.url, thumb: it.thumb || undefined,
      });
    }
    showToast(`Agent 已添加 ${seen.size} 个素材到对话输入框，确认后可发送`, 'success');
  }
  // Agent 联动更新了故事板：提示 + 触发左面板高亮闪烁
  if ((payload.applied_actions || 0) > 0) {
    const elapsed = ((payload.elapsed_ms || 0) / 1000).toFixed(1);
    showToast(`Agent 已联动更新 ${payload.applied_actions} 项（${elapsed}s）`, 'success');
    studioActions.markBoardApplied();
  }
  (payload.warnings || []).forEach((w) => showToast(`⚠ ${w}`, 'warning'));
}

/** 组件内使用的响应式封装 */
export function useAgentStream() {
  return { send: streamAgentChat, stop: stopAgentStream, streaming, error };
}
