/**
 * 过程时间线纯函数域。
 *
 * model_reasoning 创作规划条目每步一条（「模型创作规划（节点内第 N 轮）」；
 * 主体回归后每轮均由模型循环产生，历史 runtime 机械直跑已退役），
 * 多轮任务下低信息密度条目堆叠淹没真实工具账目。渲染前把连续规划条目合并为
 * 「规划 N 轮 · 累计 Xs」单条（保留逐轮明细可展开）；工具/执行器条目不受影响。
 *
 * 职责切分（前端体验规范）：status 栏 = 当前正在做的一件事；
 * 时间线 = 本轮已发生的全部账目。
 */
import type { ChatMessage, TraceAction } from '@/types';
import { ledgerFromSettled } from '@/lib/turn-ledger';
import {
  TOOL_DETAIL_INTERNAL_NONE,
  TOOL_DETAIL_TIER_DEFAULT,
  TOOL_DETAIL_TIERS,
} from '@/types/api.generated';

/** 时间线单条操作条目（流式运行态与历史重建共用） */
export interface TimelineItem {
  id: string;
  summary: string;
  status: 'running' | 'done' | 'failed';
  /** 工具/操作名（分级展开判定依据；规划条目 = model_reasoning） */
  name?: string;
  elapsed_ms?: number;
  /** 运行态走秒起点 */
  started_at_ms?: number;
  /** 工具执行结果一句话摘要（live=tool_finished、历史=trace result_summary） */
  result_summary?: string;
  /** 规划级执行器标记（不产真实媒体，前端挂「规划」徽标） */
  planning?: boolean;
  /** 工具输入参数预览（后端裁剪脱敏，详情卡展开区用） */
  args?: Record<string, unknown>;
  /** 合并条目的逐轮明细（点击展开） */
  details?: TimelineItem[];
}

/** 耗时格式化：<0.1s 显示毫秒（本地状态操作很快，0.0s 看着像没计时） */
export function formatElapsed(ms: number): string {
  return ms < 100 ? `${Math.max(1, Math.round(ms))}ms` : `${(ms / 1000).toFixed(1)}s`;
}

/** result_summary 详情展开视图（纯函数，vitest 钉死）：
 * 折叠态默认一句话摘要（首句句末标点/换行切分）；其后仍有内容才可展开。
 * 无切分点的整段摘要不可展开（不挂多余按钮）。 */
export function resultSummaryView(full: string): { expandable: boolean; collapsed: string } {
  const text = (full || '').trim();
  if (!text) return { expandable: false, collapsed: '' };
  const firstLine = text.split('\n')[0];
  const m = /^.*?[。！？!?]/.exec(firstLine);
  const collapsed = m ? m[0] : firstLine;
  return { expandable: collapsed.length < text.length, collapsed };
}

/** agent_loop 规划条目的 id 前缀（llm-s{step}），合并判定唯一依据 */
const REASONING_ID_PREFIX = 'llm-s';

/** 工具详情分级（任务 #2 引入，任务 #4 元数据驱动，纯函数 vitest 钉死）：
 * expand = 可展开看输入参数预览 + 执行结果；
 * output = 仅输出留痕（不显示输入）；none = 保持一行摘要（仅内部条目）。 */
export type ToolDetailTier = 'expand' | 'output' | 'none';

/** 分级不再硬编码工具名白名单：消费生成物 TOOL_DETAIL_TIERS（后端各工具
 * detail_tier 声明经 sidecar 生成）；未声明者走默认档 output（新工具至少
 * 留输出痕迹，不再静默落入 none）；model_reasoning 等非工具内部条目经
 * TOOL_DETAIL_INTERNAL_NONE 名单登记恒定 none。 */
export function toolDetailTier(name?: string): ToolDetailTier {
  if (!name) return TOOL_DETAIL_TIER_DEFAULT;
  if ((TOOL_DETAIL_INTERNAL_NONE as readonly string[]).includes(name)) return 'none';
  return TOOL_DETAIL_TIERS[name] ?? TOOL_DETAIL_TIER_DEFAULT;
}

/** 输入参数预览单值截断长度（后端已裁剪，前端再保一道显示级上限） */
const ARG_VALUE_LIMIT = 120;

/** args → 详情卡键值条目（纯函数，vitest 钉死）：非字符串值 JSON 化，
 * 超长值截断加省略号（显示级兼容，后端已裁剪脱敏）。 */
export function argsPreviewEntries(
  args?: Record<string, unknown>,
): { key: string; value: string }[] {
  if (!args) return [];
  return Object.entries(args).map(([key, raw]) => {
    const text = typeof raw === 'string' ? raw : JSON.stringify(raw);
    return {
      key,
      value: text.length > ARG_VALUE_LIMIT ? `${text.slice(0, ARG_VALUE_LIMIT)}…` : text,
    };
  });
}

/**
 * 从已完成消息的 trace / actionLog 重建时间线数据（刷新页面后不丢）。
 * F2 阶段一：重建逻辑收敛到 lib/turn-ledger 的 settled 归一入口
 *（与 live 账本同构 LedgerItem[]）；本函数保留既有返回形态供渲染层消费。
 */
export function timelineFromMessage(
  msg: ChatMessage,
): { reasoning: string; items: TimelineItem[] } {
  const ledger = ledgerFromSettled({
    trace: msg.trace,
    actionLog: msg.actionLog,
    thinkingMs: msg.thinkingMs,
    turnId: msg.turnId,
  });
  return { reasoning: ledger.reasoning, items: ledger.items };
}

/**
 * 推导本轮完成的「大阶段」名：取 trace 条目携带的 stage（后端权威）；
 * 无 stage（旧消息）回退空串，卡片显示通用「阶段完成」。
 */
export function stageLabelFromMessage(msg: ChatMessage): string {
  const steps = msg.trace?.steps || [];
  let label = '';
  steps.forEach((s) => {
    (s.actions || []).forEach((a: TraceAction) => {
      if (a.stage) label = a.stage;
    });
  });
  return label;
}

/**
 * 合并连续规划条目为单条（纯函数，vitest 钉死）：
 * - 仅合并相邻的 model_reasoning 条目（id 前缀 llm-s），工具条目原样保留；
 * - 段内含 running 条目（流式中）时不合并，保持实时逐条可见；
 * - 合并条 status=done（全部完成才合并），耗时为逐轮之和，明细挂 details。
 */
export function consolidateTimeline(items: TimelineItem[]): TimelineItem[] {
  const out: TimelineItem[] = [];
  let run: TimelineItem[] = [];

  const flush = () => {
    if (run.length <= 1 || run.some((i) => i.status === 'running')) {
      out.push(...run);
    } else {
      const total = run.reduce((s, i) => s + (i.elapsed_ms || 0), 0);
      const failed = run.some((i) => i.status === 'failed');
      out.push({
        id: `${run[0].id}-merged`,
        summary: `模型创作 ${run.length} 步 · 累计 ${formatElapsed(total)}`,
        status: failed ? 'failed' : 'done',
        elapsed_ms: total,
        details: run,
      });
    }
    run = [];
  };

  items.forEach((item) => {
    if (item.id.startsWith(REASONING_ID_PREFIX)) {
      run.push(item);
    } else {
      flush();
      out.push(item);
    }
  });
  flush();
  return out;
}
