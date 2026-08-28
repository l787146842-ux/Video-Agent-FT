/**
 * generation-events 总线测试（任务 #19 缺口补齐）。
 *
 * 钉死契约：
 * ① event_seq 帧级去重：键 `${task_id}:${event_seq}` 命中跳过；
 *    无该字段的帧兼容不去重；seq 回绕/后端重启重置基线；表超 500 整体清空；
 * ② manualTaskIds 事件驱动释放：终态帧到达主动 delete（后续帧恢复总线处理）；
 * ③ TTL 兜底对齐 35 分钟（15 分钟时仍登记，36 分钟后释放）。
 */
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';

let mockSseHandler: ((raw: string) => void) | null = null;

vi.mock('@/lib/reconnecting-sse', () => ({
  createReconnectingSSE: vi.fn((_url: string, onMessage: (raw: string) => void) => {
    mockSseHandler = onMessage;
    return { close: vi.fn() };
  }),
}));
vi.mock('@/stores/studio', () => ({
  state: { activeGenerations: {} },
  studioActions: {
    startGeneration: vi.fn(),
    finishGeneration: vi.fn(),
    updateDraftLocal: vi.fn(),
  },
}));
vi.mock('@/stores/studio-core', () => ({
  findDraftRecord: vi.fn(() => ({ type: 'image', draft: { tag: '' } })),
}));
vi.mock('@/stores/generation-log', () => ({
  genLogs: vi.fn(() => []),
  refreshGenLogs: vi.fn(async () => {}),
  bumpGenLogUnread: vi.fn(),
}));
vi.mock('@/api/generate', () => ({
  getActiveGenTasks: vi.fn(async () => ({ tasks: [] })),
}));

import {
  initGenerationEvents, registerManualTask, isDuplicateEventSeq, resetEventSeqDedupe,
  pruneStaleGenerations, restoreActiveGenerations,
} from '../generation-events';
import { state, studioActions } from '@/stores/studio';
import { genLogs } from '@/stores/generation-log';
import { getActiveGenTasks } from '@/api/generate';

/** 向总线注入一帧（JSON 序列化后经 SSE 回调投递） */
function emit(ev: Record<string, unknown>): void {
  if (!mockSseHandler) throw new Error('SSE handler 未登记');
  mockSseHandler(JSON.stringify(ev));
}

beforeAll(() => {
  initGenerationEvents();
});

beforeEach(() => {
  resetEventSeqDedupe();
  vi.mocked(studioActions.startGeneration).mockClear();
  vi.mocked(studioActions.finishGeneration).mockClear();
  vi.mocked(studioActions.updateDraftLocal).mockClear();
});

describe('isDuplicateEventSeq（event_seq 帧级去重表）', () => {
  it('同 task_id 同 seq 命中跳过；递增 seq 不命中', () => {
    expect(isDuplicateEventSeq('t1', 1)).toBe(false);
    expect(isDuplicateEventSeq('t1', 1)).toBe(true);
    expect(isDuplicateEventSeq('t1', 2)).toBe(false);
    // 不同 task_id 独立计数
    expect(isDuplicateEventSeq('t2', 1)).toBe(false);
  });

  it('新 seq 小于基线（回绕/后端重启）：重置基线并清该任务历史键', () => {
    isDuplicateEventSeq('tw', 5);
    isDuplicateEventSeq('tw', 6);
    // 回绕到 5：历史键已清，不判重（新帧不被旧键误杀）
    expect(isDuplicateEventSeq('tw', 5)).toBe(false);
    expect(isDuplicateEventSeq('tw', 5)).toBe(true);
  });

  it('表超 500 条整体清空回绕', () => {
    for (let i = 1; i <= 500; i += 1) isDuplicateEventSeq('big', i);
    isDuplicateEventSeq('big', 501); // 第 501 条入表后超限清空
    expect(isDuplicateEventSeq('big', 1)).toBe(false); // 清空后旧 seq 不再命中
  });
});

describe('总线 event_seq 消费（重连 replay 与增量同源双达防重）', () => {
  it('同 task_id 同 seq 重复帧只处理一次', () => {
    emit({ task_id: 'g1', event_seq: 1, status: 'started', draft_id: 'd1' });
    emit({ task_id: 'g1', event_seq: 1, status: 'started', draft_id: 'd1' });
    expect(studioActions.startGeneration).toHaveBeenCalledTimes(1);
  });

  it('无 event_seq 字段的旧帧兼容：不去重照常处理', () => {
    emit({ task_id: 'g2', status: 'started', draft_id: 'd2' });
    emit({ task_id: 'g2', status: 'started', draft_id: 'd2' });
    expect(studioActions.startGeneration).toHaveBeenCalledTimes(2);
  });
});

describe('manualTaskIds 事件驱动释放', () => {
  it('手动任务终态帧到达即释放：后续帧恢复总线处理', () => {
    registerManualTask('m1');
    // 终态帧：仍跳过总线处理（手动路径负责），但登记被移除
    emit({ task_id: 'm1', event_seq: 1, status: 'succeeded', draft_id: 'd3', result: { images: ['u'] } });
    expect(studioActions.finishGeneration).not.toHaveBeenCalled();
    // 释放后同任务新帧回归总线通道
    emit({ task_id: 'm1', event_seq: 2, status: 'started', draft_id: 'd3' });
    expect(studioActions.startGeneration).toHaveBeenCalledTimes(1);
  });

  it('TTL 兜底 35 分钟：34 分钟仍登记，36 分钟后释放', () => {
    vi.useFakeTimers();
    try {
      registerManualTask('m-ttl');
      emit({ task_id: 'm-ttl', status: 'started', draft_id: 'd4' });
      expect(studioActions.startGeneration).not.toHaveBeenCalled();
      vi.advanceTimersByTime(34 * 60 * 1000);
      emit({ task_id: 'm-ttl', status: 'started', draft_id: 'd4' });
      expect(studioActions.startGeneration).not.toHaveBeenCalled(); // 旧 15 分钟 TTL 已失效
      vi.advanceTimersByTime(2 * 60 * 1000);
      emit({ task_id: 'm-ttl', status: 'started', draft_id: 'd4' });
      expect(studioActions.startGeneration).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('pruneStaleGenerations（本地读秒与后端权威任务对账）', () => {
  it('后端已无任务的草稿立即停读秒；生成日志标 failed 时纠正标签', async () => {
    state.activeGenerations = { 'd-stale': { start: Date.now(), kind: 'image' } };
    vi.mocked(getActiveGenTasks).mockResolvedValueOnce({ tasks: [] } as never);
    // 最新生成日志为 failed：卡在「生成中」的标签纠正为「生成失败」
    vi.mocked(genLogs).mockReturnValueOnce([{ draft_id: 'd-stale', status: 'failed' }] as never);
    await pruneStaleGenerations();
    expect(studioActions.finishGeneration).toHaveBeenCalledWith('d-stale');
    expect(studioActions.updateDraftLocal).toHaveBeenCalledWith(
      'image', 'd-stale', { tag: '生成失败' },
    );
    state.activeGenerations = {};
  });

  it('后端仍在处理中的草稿不动；无活跃读秒时短路', async () => {
    state.activeGenerations = { 'd-live': { start: Date.now(), kind: 'image' } };
    vi.mocked(getActiveGenTasks).mockResolvedValueOnce({ tasks: [{ draft_id: 'd-live' }] } as never);
    await pruneStaleGenerations();
    expect(studioActions.finishGeneration).not.toHaveBeenCalled();
    state.activeGenerations = {};
    await pruneStaleGenerations(); // 无活跃读秒：短路不请求后端（无新调用）
    expect(studioActions.finishGeneration).not.toHaveBeenCalled();
  });
});

describe('restoreActiveGenerations（刷新后按后端任务回填读秒）', () => {
  it('按任务创建时间回填起点；无效草稿跳过', async () => {
    vi.mocked(getActiveGenTasks).mockResolvedValueOnce({
      tasks: [
        { draft_id: 'd-r1', created_at: 100, kind: 'video' },
        { draft_id: '', created_at: 0, kind: 'image' },
      ],
    } as never);
    await restoreActiveGenerations();
    expect(studioActions.startGeneration).toHaveBeenCalledWith('d-r1', 'video', 100000);
    expect(studioActions.startGeneration).toHaveBeenCalledTimes(1);
  });
});
