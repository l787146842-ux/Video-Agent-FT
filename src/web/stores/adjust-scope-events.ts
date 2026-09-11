/**
 * 微调真子对话线程视图模型与事件归约（批 S3，自 stores/adjust-scopes.ts 拆出，
 * 前端文件行数红线 250）。纯逻辑：类型 + emptyStreaming + done 气泡构造 +
 * applyScopeEvent 归约（在 produce 内就地改写草稿）；不触 store/不发请求。
 */
import type { ChatMessage, SseDonePayload } from '@/types';
import { buildDoneMeta } from './chat/done-message';
import { t } from '@/lib/locale';

/** 微调目标定位（与后端 scope 同形：kind+cat+group_id+draft_id 为幂等键） */
export interface AdjustScopeTarget {
  kind: 'adjust';
  cat: string;
  group_id: string;
  draft_id: string;
  label: string;
}

export interface ScopeToolEntry {
  id: string;
  name: string;
  summary: string;
  status: 'running' | 'done' | 'failed';
  startedAtMs: number;
  elapsedMs?: number;
  resultSummary?: string;
}

/** 当前轮流式累积视图（浮窗渲染：逐字回复/思考/状态/工具步骤/轮次进度） */
export interface ScopeStreamingView {
  active: boolean;
  text: string;
  reasoning: string;
  statusText: string;
  tools: ScopeToolEntry[];
}

export type ScopeThreadStatus = 'idle' | 'starting' | 'running' | 'error';

/** 线程参考素材引用（二期子对话批 3）：绑线程对话体 scopeRefs，不进全局
 *  assets/uploadedDocs；物理文件存共享素材目录（移除只解引用，逻辑清物理不清） */
export interface ScopeRef { id: string; name: string; kind: string; url: string }

export interface ScopeThread {
  scope: AdjustScopeTarget;
  convId: string;
  /** 浮窗是否弹出（提交后自动置真；关闭仅置假，线程存活，批 S4 消费） */
  open: boolean;
  messages: ChatMessage[];
  /** 运行中任务（'' = 空闲） */
  taskId: string;
  status: ScopeThreadStatus;
  errorText: string;
  streaming: ScopeStreamingView;
  /** 待发引用暂存（上传后未发送；sendAdjust 携带后并入 scopeRefs） */
  pendingRefs: ScopeRef[];
  /** 已绑线程引用（后端回带重建；随重生成持续注入） */
  scopeRefs: ScopeRef[];
}

/** scope 事件（事件路由写入的唯一形态；与 SSE 事件一一对应） */
export type ScopeEvent =
  | { kind: 'delta'; text: string }
  | { kind: 'reasoning'; text: string }
  | { kind: 'status'; text: string }
  | { kind: 'tool_started'; id: string; name: string; summary: string }
  | { kind: 'tool_finished'; id: string; ok: boolean; elapsedMs: number; resultSummary?: string }
  | { kind: 'message'; message: ChatMessage }
  | { kind: 'replay'; snapshot: { text?: string; reasoning?: string; statusText?: string; tools?: ScopeToolEntry[] } }
  | { kind: 'done'; payload: SseDonePayload }
  | { kind: 'error'; message: string }
  | { kind: 'stopped' };

export const emptyStreaming = (): ScopeStreamingView => (
  { active: false, text: '', reasoning: '', statusText: '', tools: [] }
);

/** done 终态气泡（复用主聊天 meta 构造；图卡/视频卡自 chat_inserts 派生） */
export function buildScopeDoneMessage(payload: SseDonePayload): ChatMessage {
  const inserts = payload.chat_inserts || [];
  const imageUrls = inserts.filter((i) => i.kind === 'image' && i.url).map((i) => i.url as string);
  const videoItems = inserts.filter((i) => i.kind === 'video' && i.url)
    .map((i) => ({ url: i.url as string, name: i.name, thumb: i.thumb }));
  return {
    sender: 'agent',
    text: (payload.text || '').trim() || t('rp.msg.emptyReply'),
    meta: buildDoneMeta(payload),
    // turn_id 随消息入库：done 幂等守卫判重键（同主聊天 finishStream 口径）
    turnId: payload.turn_id || undefined,
    appliedActions: payload.applied_actions || 0,
    actionLog: (payload.action_log || []).length ? payload.action_log : undefined,
    warnings: (payload.warnings || []).length ? payload.warnings : undefined,
    imageCard: imageUrls.length ? { image_urls: imageUrls } : undefined,
    videoCard: videoItems.length ? { items: videoItems } : undefined,
  };
}

/** 事件归约：就地改写线程草稿（调用方置于 produce 内） */
export function applyScopeEvent(th: ScopeThread, ev: ScopeEvent): void {
  const st = th.streaming;
  switch (ev.kind) {
    case 'delta': st.active = true; st.text += ev.text; break;
    case 'reasoning': st.active = true; st.reasoning += ev.text; break;
    case 'status': st.active = true; st.statusText = ev.text; break;
    case 'tool_started': {
      st.active = true;
      const hit = st.tools.find((x) => x.id === ev.id);
      if (hit) { hit.name = ev.name; hit.summary = ev.summary; hit.status = 'running'; }
      else st.tools.push({ id: ev.id, name: ev.name, summary: ev.summary, status: 'running', startedAtMs: Date.now() });
      break;
    }
    case 'tool_finished': {
      const hit = st.tools.find((x) => x.id === ev.id);
      if (hit) {
        hit.status = ev.ok ? 'done' : 'failed';
        hit.elapsedMs = ev.elapsedMs;
        hit.resultSummary = ev.resultSummary;
      } else {
        st.tools.push({
          id: ev.id, name: '', summary: '', status: ev.ok ? 'done' : 'failed',
          startedAtMs: Date.now(), elapsedMs: ev.elapsedMs, resultSummary: ev.resultSummary,
        });
      }
      break;
    }
    case 'message': th.messages.push(ev.message); break;
    case 'replay':
      st.active = true;
      st.text = ev.snapshot.text || '';
      st.reasoning = ev.snapshot.reasoning || '';
      st.statusText = ev.snapshot.statusText || '';
      st.tools = ev.snapshot.tools || [];
      break;
    case 'done': {
      // turn_id 幂等守卫：终态帧可能同源双达（replay done 与增量 done，
      // 同主聊天 finishStream 口径），同 turnId 的 done 气泡（唯一携 meta）
      // 已落账则不重复追加（任务 #19 截图「同段重复两条」根因）
      const doneTurnId = ev.payload.turn_id || undefined;
      const dup = doneTurnId !== undefined && th.messages.some(
        (m) => m.sender === 'agent' && m.turnId === doneTurnId && m.meta !== undefined,
      );
      if (!dup) th.messages.push(buildScopeDoneMessage(ev.payload));
      th.streaming = emptyStreaming();
      th.status = 'idle';
      th.taskId = '';
      break;
    }
    case 'error':
      th.messages.push({ sender: 'agent', text: ev.message });
      th.streaming = emptyStreaming();
      th.status = 'error';
      th.taskId = '';
      th.errorText = ev.message;
      break;
    case 'stopped':
      th.messages.push({ sender: 'agent', text: t('rp.adjust.stopped') });
      th.streaming = emptyStreaming();
      th.status = 'idle';
      th.taskId = '';
      break;
    default: break;
  }
}
