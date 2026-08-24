/**
 * turn-ledger.ts — 轮次账本归一（F2 阶段一：数据模型统一）。
 *
 * 现状双轨：流式期数据（streamingTools/streamingReasoning/streamingStatus）
 * 与完成后数据（message.trace 重建）是两套模型，渲染层各走一路。
 * 本模块把两侧归一为同一 LedgerItem[] 账本模型：
 * - ledgerFromLive：live 归一入口（SSE 增量累积 / replay 快照恢复同走）；
 * - ledgerFromSettled：settled 归一入口（刷新/历史从 trace/actionLog 重建）；
 * - settleLedger：相位翻转（live→settled，复用同一批条目，不二次构造）。
 * 两入口输出同构 TurnLedger，渲染层单一消费面。
 */
import type { AgentTrace, TraceAction } from '@/types';

/** settled 账本消费面（消息侧字段子集，避免归一域反向依赖完整 ChatMessage） */
export interface SettledLedgerSource {
  ledger?: TurnLedger;
  trace?: AgentTrace;
  actionLog?: string[];
  thinkingMs?: number;
  turnId?: string;
}

/** 轮次相位：live=流式累积中；settled=已完成（含停止/出错后的定型） */
export type TurnPhase = 'live' | 'settled';

/** 账本单条（live 运行态与 settled 重建共用同一形态） */
export interface LedgerItem {
  id: string;
  summary: string;
  status: 'running' | 'done' | 'failed';
  /** 工具/操作名（分级展开判定依据；规划条目 = model_reasoning） */
  name?: string;
  elapsed_ms?: number;
  /** 运行态走秒计时起点（replay 无原始起点时以恢复时刻为准） */
  started_at_ms?: number;
  /** 执行结果一句话摘要（live=tool_finished、settled=trace result_summary） */
  result_summary?: string;
  /** 规划级执行器标记（不产真实媒体，前端挂「规划」徽标） */
  planning?: boolean;
  /** 工具输入参数预览（后端裁剪脱敏，详情卡展开区用） */
  args?: Record<string, unknown>;
}

/** 轮次账本：live 期累积的单一数据体，完成即相位翻转随消息入库 */
export interface TurnLedger {
  phase: TurnPhase;
  turnId?: string;
  /** 深度思考累积文本（仅展示，不进下次上下文） */
  reasoning: string;
  items: LedgerItem[];
  /** live 期状态栏文案（= 当前正在做的一件事） */
  statusText: string;
  /** 深度思考起点（首条 reasoning 增量记录；0 = 无） */
  reasoningStartMs: number;
  /** 深度思考终点（随每条增量推进；角标只算思考区间） */
  reasoningEndMs: number;
  /** settled 期深度思考总耗时（完成后角标展示） */
  thinkingMs?: number;
}

/** 空账本（startStream/收尾重置用；statusText 可带连接中文案） */
export function emptyLedger(statusText = ''): TurnLedger {
  return {
    phase: 'live',
    turnId: undefined,
    reasoning: '',
    items: [],
    statusText,
    reasoningStartMs: 0,
    reasoningEndMs: 0,
    thinkingMs: undefined,
  };
}

/** live 归一入口输入（SSE 累积态 / replay 快照同形） */
export interface LiveLedgerInput {
  tools?: Array<Partial<LedgerItem>>;
  reasoning?: string;
  statusText?: string;
  turnId?: string;
  /** 恢复基准时刻（running 条目无起点 / 有思考无起点时以此为准） */
  now?: number;
}

/** live 归一：把流式累积/replay 快照收敛为 TurnLedger（status 白名单收窄防退化） */
export function ledgerFromLive(input: LiveLedgerInput = {}): TurnLedger {
  const now = input.now ?? Date.now();
  const reasoning = input.reasoning || '';
  const items: LedgerItem[] = (input.tools || []).map((tl) => ({
    id: tl.id || '',
    name: tl.name || undefined,
    summary: tl.summary || tl.name || '',
    status: tl.status === 'done' || tl.status === 'failed' ? tl.status : 'running',
    elapsed_ms: tl.elapsed_ms ?? undefined,
    started_at_ms: tl.started_at_ms ?? now,
    result_summary: tl.result_summary || undefined,
    planning: tl.planning ?? undefined,
    args: tl.args,
  }));
  return {
    phase: 'live',
    turnId: input.turnId,
    reasoning,
    items,
    statusText: input.statusText || '',
    // 重连无原始思考起点：已有 reasoning 时以恢复时刻为起点继续计时
    reasoningStartMs: reasoning ? now : 0,
    reasoningEndMs: reasoning ? now : 0,
    thinkingMs: undefined,
  };
}

/** settled 归一入口输入（消息 trace/actionLog，刷新与历史同源） */
export interface SettledLedgerInput {
  trace?: AgentTrace;
  actionLog?: string[];
  thinkingMs?: number;
  turnId?: string;
}

/** settled 归一：从 trace/actionLog 重建账本（与 live 输出同构）。
 * trace.steps[].actions 优先；旧消息无 actions 时 actionLog 兜底。 */
export function ledgerFromSettled(input: SettledLedgerInput): TurnLedger {
  const steps = input.trace?.steps || [];
  const reasoning = steps
    .map((s) => s.reasoning || '')
    .filter(Boolean)
    .join('\n');
  const items: LedgerItem[] = [];
  steps.forEach((s) => {
    (s.actions || []).forEach((a: TraceAction, i: number) => {
      // 规划条目与 live 事件同构 id 规则（llm-s{step}），重建也能命中合并降噪
      const id = a.name === 'model_reasoning' ? `llm-s${s.step}` : `t-${s.step}-${i}`;
      items.push({
        id,
        name: a.name,
        summary: a.summary || a.name,
        status: a.ok ? 'done' : 'failed',
        elapsed_ms: a.elapsed_ms,
        result_summary: a.result_summary || undefined,
        planning: a.planning || undefined,
        args: a.args,
      });
    });
  });
  if (!items.length && (input.actionLog || []).length) {
    (input.actionLog || []).forEach((op, i) => {
      items.push({ id: `l-${i}`, summary: op, status: 'done' });
    });
  }
  return {
    phase: 'settled',
    turnId: input.turnId,
    reasoning,
    items,
    statusText: '',
    reasoningStartMs: 0,
    reasoningEndMs: 0,
    thinkingMs: input.thinkingMs || undefined,
  };
}

/** 相位翻转：live→settled。逐条浅拷贝复用同一批账目（不二次构造时间线数据）。
 * settled 轮次不存在 running 条目（未完成项落 done）——与 trace 重建
 * 「完成后不再出现旋转图标」的不变式对齐。 */
export function settleLedger(
  live: TurnLedger,
  opts: { thinkingMs?: number; turnId?: string } = {},
): TurnLedger {
  return {
    phase: 'settled',
    turnId: opts.turnId ?? live.turnId,
    reasoning: live.reasoning,
    items: live.items.map((it) => ({
      ...it,
      status: it.status === 'running' ? 'done' as const : it.status,
    })),
    statusText: '',
    reasoningStartMs: live.reasoningStartMs,
    reasoningEndMs: live.reasoningEndMs,
    thinkingMs: opts.thinkingMs || undefined,
  };
}

/**
 * settled 账本消费面（F2 阶段二，渲染层单一入口）：优先消费 finishStream
 * 相位翻转后随消息入库的账本；账本无账目无思考（纯文本轮未走工具事件，
 * 翻转为空账本）或历史/刷新消息无本地账本时，回落 ledgerFromSettled
 * （trace/actionLog 同一归一入口，action_log 兜底路径不丢）。
 *
 * 一致性回落：trace 是服务端权威源——当本地账本条目数少于 trace 动作
 * 总数（SSE 事件丢失等边缘）时改走 ledgerFromSettled(trace) 重建，
 * 防时间线条目变少；不动 finishStream 主链（仅消费面重建）。
 */
export function settledLedgerForMessage(src: SettledLedgerSource): TurnLedger {
  const led = src.ledger;
  if (led && (led.items.length > 0 || led.reasoning)) {
    const traceActions = (src.trace?.steps || [])
      .reduce((n, s) => n + ((s.actions || []).length), 0);
    if (traceActions === 0 || led.items.length >= traceActions) return led;
    // 账本条目不足于服务端 trace → 回落权威源重建
  }
  return ledgerFromSettled({
    trace: src.trace,
    actionLog: src.actionLog,
    thinkingMs: src.thinkingMs,
    turnId: src.turnId,
  });
}
