/**
 * stream-finalize.ts — 流式收尾辅助（供 done/错误/停止/重连四处收尾复用）。
 *
 * - resetStreamFields：流式收尾重置（done/错误/停止/重连收尾四处同语义）；
 * - continueLastTaskSuggestion：「继续刚才的任务」本地派生（停止/报错气泡共用）；
 * - buildStopMessages：停止气泡构造（不变式：任何中断都有痕迹、都有出口）——
 *   无文本停止也落轻量系统气泡 + 继续建议；阶段标记影响措辞；
 *   在途外部生成任务登记附文案提醒（第一版不撤销）。
 */
import type { ChatMessage } from '@/types';
import { t } from '@/lib/locale';
import type { ChatState } from '@/stores/chat';

/** 流式收尾重置（done/错误/停止/重连收尾四处同语义，单一实现） */
export function resetStreamFields(s: ChatState) {
  s.isStreaming = false;
  s.streamingText = '';
  s.streamingStatus = '';
  s.streamingModel = '';
  s.streamingReasoning = '';
  s.streamingTools = [];
  s.streamingReasoningStartMs = 0;
  s.roundStep = 0;
  s.roundMax = 0;
}

/** 「继续刚才的任务」本地派生（停止/报错气泡共用单一实现）；
 * kind=retry=点击走既有机械重发，失效走 suggestedTargetIndex 既有机制 */
export const continueLastTaskSuggestion = () => [{ kind: 'retry' as const, label: t('rp.msg.continueLastTask'), value: '' }];

export type StopPhase = 'thinking' | 'tool_executing' | 'streaming';
/** 在途外部生成任务登记项（后端 /stop 响应或 stopped 事件携带） */
export interface StopInflightItem { task_id?: string; media_type?: string; summary?: string; }

interface StopBuildContext {
  /** 停止阶段（stopped 事件/停止响应下发；缺省按本地流状态推导） */
  phase?: StopPhase;
  inflight?: StopInflightItem[];
  text: string;
  model: string;
  hasRunningTool: boolean;
}

/** 构造停止痕迹消息：有文本=正文气泡 + meta 阶段标记；无文本=轻量系统气泡；均挂继续建议 */
export function buildStopMessages(ctx: StopBuildContext): ChatMessage[] {
  // 阶段推导：显式 phase 优先；缺省时按本地流状态推断
  // （有文本=输出阶段；有运行中工具=工具执行阶段；否则=思考阶段）
  const phase: StopPhase = ctx.phase
    || (ctx.text ? 'streaming' : (ctx.hasRunningTool ? 'tool_executing' : 'thinking'));
  // 在途外部生成任务提醒（如有）：供应商侧仍在继续，本次停止不撤销
  const inflightNote = (ctx.inflight && ctx.inflight.length)
    ? t('rp.msg.stoppedInflight', { n: ctx.inflight.length }) : '';
  const suggestion = continueLastTaskSuggestion();
  if (ctx.text) {
    // 已有部分输出：正文落气泡，meta 标停止阶段
    const metaParts = [t(phase === 'tool_executing' ? 'rp.msg.stoppedTool'
      : (phase === 'thinking' ? 'rp.msg.stoppedThinking' : 'rp.msg.stoppedStreaming'))];
    if (inflightNote) metaParts.push(inflightNote);
    return [{
      sender: 'agent', text: ctx.text, meta: metaParts.join(' · '),
      modelName: ctx.model || undefined, suggestedActions: suggestion,
    }];
  }
  // 无文本停止（思考/工具执行阶段）：轻量系统气泡，痕迹不缺席
  const parts = [`⏹ ${t(phase === 'tool_executing' ? 'rp.msg.stoppedToolEmpty' : 'rp.msg.stoppedThinking')}`];
  if (inflightNote) parts.push(inflightNote);
  return [{
    sender: 'agent', text: parts.join('\n'),
    modelName: ctx.model || undefined, suggestedActions: suggestion,
  }];
}
