/**
 * 过程时间线纯函数域（批 2 时间线降噪）。
 *
 * model_reasoning 创作规划条目每步一条（「模型创作规划（节点内第 N 轮）」；
 * 主体回归后每轮均由模型循环产生，历史 runtime 机械直跑已退役），
 * 多轮任务下低信息密度条目堆叠淹没真实工具账目。渲染前把连续规划条目合并为
 * 「规划 N 轮 · 累计 Xs」单条（保留逐轮明细可展开）；工具/执行器条目不受影响。
 *
 * 职责切分（前端体验规范）：status 栏 = 当前正在做的一件事；
 * 时间线 = 本轮已发生的全部账目。
 */

/** 时间线单条操作条目（流式运行态与历史重建共用） */
export interface TimelineItem {
  id: string;
  summary: string;
  status: 'running' | 'done' | 'failed';
  elapsed_ms?: number;
  /** 运行态走秒起点 */
  started_at_ms?: number;
  /** 工具执行结果一句话摘要（批2 透明度：live=tool_finished、历史=trace result_summary） */
  result_summary?: string;
  /** 审核整改批 2：规划级执行器标记（不产真实媒体，前端挂「规划」徽标） */
  planning?: boolean;
  /** 合并条目的逐轮明细（点击展开） */
  details?: TimelineItem[];
}

/** 耗时格式化：<0.1s 显示毫秒（本地状态操作很快，0.0s 看着像没计时） */
export function formatElapsed(ms: number): string {
  return ms < 100 ? `${Math.max(1, Math.round(ms))}ms` : `${(ms / 1000).toFixed(1)}s`;
}

/** agent_loop 规划条目的 id 前缀（llm-s{step}），合并判定唯一依据 */
const REASONING_ID_PREFIX = 'llm-s';

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
