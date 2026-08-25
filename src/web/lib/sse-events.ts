/**
 * SSE 事件路由层（自 hooks/use-sse.ts 抽出的纯逻辑）：消费 SseEvent，
 * 写侧效果全部经注入的 fx，归属/终态清理经 ctx 回调；不做 I/O、不持连接状态。
 * 顺序铁律：终态路径经 ctx.finalize 收尾——先复位忙态、置空归属、再关订阅，
 * 顺序搞反会产生假错误气泡（见 lib/sse-connection.finalizeTerminal 注释）。
 */
import type { SseEvent, SseDonePayload, ServerStateSnapshot, InlineMedia } from '@/types';
import type { chatActions } from '@/stores/chat';
import type { ToastLevel } from '@/stores/toast';
import { sseErrorPayload, normalizeKind } from '@/lib/error-payload';
import { resolveErrorMessage } from '@/lib/i18n';
import { t, tDynamic } from '@/lib/locale';
import { parseRoundParams } from '@/lib/storyboard-progress';
import { uid } from '@/lib/utils';

/** 事件路由所需的 chat store 写面（结构类型，hooks 层直接注入 chatActions） */
export type SseChatFx = Pick<typeof chatActions,
  | 'startStream' | 'streamError' | 'setStatus' | 'setRoundProgress' | 'appendDelta'
  | 'appendReasoning' | 'toolStarted' | 'toolFinished' | 'docWritten' | 'addMessage'
  | 'removeQueuedMessage' | 'restoreStreamingState' | 'clearStreaming' | 'loadMessages'
  | 'applyDecisionForm' | 'finishStream' | 'cancelStream'>;

/** 响应式/跨 store 副作用注入面（本模块不 import 任何 store 运行时） */
export interface SseEventFx {
  chat: SseChatFx;
  setStreaming(v: boolean): void;
  setAgentBusy(v: boolean): void;
  setErrorText(msg: string | null): void;
  /** 故事板 + 会话快照整板同步（studio/conv 双 store 同写） */
  syncSnapshot(snapshot: ServerStateSnapshot): void;
  markBoardApplied(): void;
  applyFallbackModel(provider: string | undefined, model: string | undefined): void;
  toast(msg: string, level: ToastLevel): void;
  insertMedia(media: InlineMedia): void;
  refreshHistory(): void;
  /** 读时间注入（运行中工具秒起点兜底），测试可钉死 */
  now(): number;
}
/** 连接状态机注入的运行时上下文（归属判定/终态清理） */
export interface SseEventCtx {
  fx: SseEventFx;
  /** 恢复订阅中（resumeAgentTasks 路径；replay 终态直接采用快照） */
  isRecovering(): boolean;
  /** 归属仍在（stopped 迟到帧防重复气泡守卫） */
  hasOwnership(): boolean;
  /** 终态清理：复位忙态 → 置空归属 → 关订阅（不传 key 时按归属项目清） */
  finalize(projectKey?: string): void;
}

/** done 终态：落气泡 + 快照同步 + 媒体插入归并，最后终态清理 */
export function finishSseDone(payload: SseDonePayload, ctx: SseEventCtx): void {
  const { fx } = ctx;
  fx.chat.finishStream(payload);
  if (payload.state) fx.syncSnapshot(payload.state);
  void fx.refreshHistory();
  const inserts = payload.chat_inserts || [];
  if (inserts.length) {
    const seen = new Set<string>();
    for (const it of inserts) {
      // 视频项不进输入框：内联预览卡为准（finishStream 派生 videoCard 气泡），防双渲染
      if (it.kind === 'video') continue;
      if (!it.url || seen.has(it.url)) continue;
      seen.add(it.url);
      fx.insertMedia({
        id: uid('im'), kind: it.kind, url: it.url,
        name: it.name || it.url, thumb: it.thumb || undefined,
      });
    }
    // toast 计数只算实际插入项（不含视频）；无插入不弹
    if (seen.size) fx.toast(t('rp.msg.mediaInserted', { count: seen.size }), 'success');
  }
  if ((payload.applied_actions || 0) > 0) fx.markBoardApplied();
  // toast 收敛：操作数已由阶段卡徽标/meta 展示、警告已常驻消息内，不再重复弹
  ctx.finalize();
}

/** SSE 帧流解析：data: 帧 → onEvent；异常帧不中断流（静默吞错曾掩盖契约漂移），
 * 每遇异常帧回调 onParseError（累计计数与告警在连接状态机侧） */
export async function parseSseStream(
  res: Response,
  onEvent: (ev: SseEvent) => void,
  onParseError: () => void,
): Promise<void> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 2);
      if (!raw.startsWith('data:')) continue;
      const jsonStr = raw.slice(5).trim();
      if (jsonStr === '[DONE]') continue;
      try {
        onEvent(JSON.parse(jsonStr) as SseEvent);
      } catch {
        onParseError();
      }
    }
  }
}

/** 路由一帧 SSE 事件到注入副作用（replay 快照 → 增量的恢复顺序在此） */
export function routeSseEvent(ev: SseEvent, ctx: SseEventCtx): void {
  const { fx } = ctx;
  switch (ev.type) {
    case 'replay': {
      const p = ev.payload;
      if (!p) break;
      // 断连期间发生过降级：重连即把选择器补跳到实际生效的组合
      if (p.fallback?.model) fx.applyFallbackModel(p.fallback.provider, p.fallback.model);
      // 任务已结束（断连期间完成）：直接采用服务端快照，避免消息重复
      if (p.status === 'done' && p.done_payload) {
        if (ctx.isRecovering()) {
          if (p.snapshot) fx.syncSnapshot(p.snapshot);
          if (p.snapshot?.chatMessages) fx.chat.loadMessages(p.snapshot.chatMessages);
          // 持久化消息不携 decisionForm，replay 同源重建结构化决策表单
          if (p.workflow?.pending_decision_payload) {
            fx.chat.applyDecisionForm(p.workflow.pending_decision_payload);
          }
          fx.chat.clearStreaming();
          ctx.finalize(p.project_id);
          fx.toast(t('rp.task.done'), 'success');
        } else {
          finishSseDone(p.done_payload, ctx);
        }
        break;
      }
      if (p.status === 'error') {
        // replay 同源下发 error_payload（code/kind/raw），
        // 旧记录无此字段时归 unknown（映射表仍能给出默认 affordance）
        const rp = p.error_payload;
        fx.chat.streamError({
          code: rp?.code || 'err.unknown',
          kind: normalizeKind(rp?.kind),
          message: p.error || '任务已中断',
          raw: rp?.raw || undefined,
        });
        ctx.finalize(p.project_id);
        break;
      }
      // 停止终态 replay（刷新/重连后恢复停止痕迹）
      if (p.status === 'stopped') {
        if (ctx.isRecovering() && p.snapshot?.chatMessages) {
          // 恢复场景：后端已把停止痕迹消息持久化进历史，直接采用快照
          fx.syncSnapshot(p.snapshot);
          fx.chat.loadMessages(p.snapshot.chatMessages);
          fx.chat.clearStreaming();
        } else {
          // 非恢复场景：本地未落气泡，按 stopped_payload 补落（阶段 + 在途登记）
          const sp = p.stopped_payload;
          fx.chat.cancelStream({ phase: sp?.phase, inflight: sp?.inflight });
        }
        ctx.finalize(p.project_id);
        break;
      }
      // 运行中：恢复累积状态后继续收实时增量
      // Rule2 v6：断连期间文档卡补渲染（瞬态 SSE 不得作为唯一可见性）
      (p.docs || []).forEach((n) => fx.chat.docWritten(n));
      fx.chat.restoreStreamingState({
        reasoning: p.reasoning || '',
        text: p.text || '',
        statusText: p.status_text || t('rp.streaming.processing'),
        tools: (p.tools || []).map((tool) => ({
          id: tool.id || '',
          name: tool.name || '',
          summary: tool.summary || '',
          status: (
            tool.status === 'running' || tool.status === 'done' || tool.status === 'failed'
              ? tool.status
              : 'running'
          ),
          elapsed_ms: tool.elapsed_ms ?? undefined,
          result_summary: tool.result_summary || '',
          // 重连 replay 后规划级徽标不丢
          planning: tool.planning ?? undefined,
          // 运行中走秒起点（replay 无原始起点时以恢复时刻为准）
          started_at_ms: tool.started_at_ms ?? fx.now(),
        })),
        model: p.model || '',
      });
      if (p.snapshot) fx.syncSnapshot(p.snapshot);
      // 运行中重连同样重建待回应决策表单（token 幂等不双挂）
      if (p.workflow?.pending_decision_payload) {
        fx.chat.applyDecisionForm(p.workflow.pending_decision_payload);
      }
      break;
    }
    case 'status': {
      // 后端下发 key 为运行时字符串，走 tDynamic（动态键回退链）；
      // 轮次进度参数同步进 store，供阶段进度条结构化消费
      const round = parseRoundParams(ev.key, ev.params);
      if (round) fx.chat.setRoundProgress(round.step, round.max);
      const keyed = ev.key ? tDynamic(ev.key, ev.params) : '';
      fx.chat.setStatus(keyed && keyed !== ev.key ? keyed : (ev.text || ''));
      break;
    }
    case 'delta': fx.chat.appendDelta(ev.text || ''); break;
    case 'reasoning_delta': fx.chat.appendReasoning(ev.text || ''); break;
    case 'tool_started': fx.chat.toolStarted(ev.id, ev.name, ev.summary, ev.args); break;
    case 'tool_finished':
      fx.chat.toolFinished(ev.id, ev.ok, ev.elapsed_ms || 0, ev.result_summary, ev.planning);
      break;
    case 'doc_written': // 携带后端打戳的 turn_id，即显卡与 done 主消息严格同组
      if (ev.name) fx.chat.docWritten(ev.name, ev.turn_id);
      break;
    case 'model_fallback': // 降级即时联动：切换时刻就跳选择器，不等整轮成功
      fx.applyFallbackModel(ev.provider, ev.model);
      break;
    case 'guidance_injected': // 轮间注入成功：渲染用户气泡并从排队区移除对应条目
      if (ev.text) fx.chat.addMessage({ sender: 'user', text: ev.text });
      if (ev.id) fx.chat.removeQueuedMessage(ev.id);
      break;
    case 'actions_applied': {
      const snapshot = ev.payload?.state;
      if (snapshot) {
        fx.syncSnapshot(snapshot);
        fx.markBoardApplied();
      }
      break;
    }
    case 'done': finishSseDone(ev.payload, ctx); break;
    // 任务状态变更（cancelled 等）：后端下发后即关流，流结束走连接状态机正常收尾
    case 'task_status': break;
    case 'stopped': {
      // 停止终态：协作式取消检查点命中，落停止痕迹后关流收尾；
      // 归属守卫：用户已点停止按钮时本地已落气泡并置空归属，此处防重复气泡
      if (!ctx.hasOwnership()) break;
      fx.chat.cancelStream({ phase: ev.phase, inflight: ev.inflight });
      ctx.finalize();
      break;
    }
    case 'error': {
      // 错误事件 → ErrorPayload（与 HTTP 失败共用 lib/error-payload 解析器）；
      // 旧事件（仅 error_code）的 i18n 翻译通道保留作 message 兜底
      const payload = sseErrorPayload(ev);
      const msg = ev.code ? payload.message : resolveErrorMessage(ev.error_code, payload.message);
      fx.setErrorText(msg);
      // 上游原始报文随错误消息下发，前端折叠展示
      fx.chat.streamError({ ...payload, message: msg });
      ctx.finalize();
      break;
    }
    default: break;
  }
}
