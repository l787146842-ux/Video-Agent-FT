import { describe, it, expect } from 'vitest';
import { consolidateTimeline, formatElapsed, type TimelineItem } from '../timeline';

/** 批 2 时间线降噪：连续规划条目合并（纯函数钉死） */

const reasoning = (step: number, ms: number, status: TimelineItem['status'] = 'done'): TimelineItem => ({
  id: `llm-s${step}`,
  summary: `模型创作规划（节点内第 ${step} 轮）`,
  status,
  elapsed_ms: ms,
});
const tool = (id: string, ms: number): TimelineItem => ({
  id, summary: `工具 ${id}`, status: 'done', elapsed_ms: ms,
});

describe('consolidateTimeline 规划条目合并', () => {
  it('连续多条规划条目合并为单条（N 轮 + 累计耗时 + 明细保留）', () => {
    const out = consolidateTimeline([reasoning(1, 1200), reasoning(2, 800), reasoning(3, 1000)]);
    expect(out.length).toBe(1);
    expect(out[0].summary).toBe('模型创作 3 步 · 累计 3.0s');
    expect(out[0].elapsed_ms).toBe(3000);
    expect(out[0].details?.length).toBe(3);
  });

  it('工具条目不被合并且切断规划段', () => {
    const out = consolidateTimeline([
      reasoning(1, 500), tool('t1', 100), reasoning(2, 500), reasoning(3, 500),
    ]);
    expect(out.length).toBe(3);
    expect(out[0].id).toBe('llm-s1'); // 单条不合并
    expect(out[1].id).toBe('t1');
    expect(out[2].details?.length).toBe(2);
  });

  it('单条规划不合并（无信息增益）', () => {
    const out = consolidateTimeline([reasoning(1, 900)]);
    expect(out.length).toBe(1);
    expect(out[0].id).toBe('llm-s1');
    expect(out[0].details).toBeUndefined();
  });

  it('段内含 running 条目（流式中）不合并，保持实时逐条可见', () => {
    const out = consolidateTimeline([reasoning(1, 700), reasoning(2, 0, 'running')]);
    expect(out.length).toBe(2);
    expect(out[1].status).toBe('running');
  });

  it('空列表返回空列表', () => {
    expect(consolidateTimeline([])).toEqual([]);
  });
});

describe('formatElapsed', () => {
  it('<100ms 显示毫秒且至少 1ms', () => {
    expect(formatElapsed(0)).toBe('1ms');
    expect(formatElapsed(60)).toBe('60ms');
  });
  it('>=100ms 显示秒（一位小数）', () => {
    expect(formatElapsed(1200)).toBe('1.2s');
  });
});
