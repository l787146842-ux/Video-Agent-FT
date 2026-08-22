/**
 * hooks/use-sse.ts replay 快照 → 增量衔接测试（任务 #30 传输层补强；按主题拆分）。
 *
 * 钉死：运行中恢复 / done / error / stopped 四分支，
 * 恢复场景直接采用服务端快照（不重复消息），未知工具状态收窄。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('@/api/sse', () => ({
  startAgentTask: vi.fn(),
  fetchAgentTaskEvents: vi.fn(),
  stopAgentTask: vi.fn(),
  listAgentTasks: vi.fn(),
  postAgentTaskGuidance: vi.fn(),
}));
vi.mock('@/stores/history', () => ({ refreshHistoryStatus: vi.fn(async () => {}) }));
vi.mock('@/lib/chat-input-bridge', () => ({ requestInsertMedia: vi.fn() }));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { streamAgentChat, disconnectAgentStream, resumeAgentTasks } from '../use-sse';
import { startAgentTask, fetchAgentTaskEvents, stopAgentTask, listAgentTasks, postAgentTaskGuidance } from '@/api/sse';
import { state } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { requestInsertMedia } from '@/lib/chat-input-bridge';
import { req, sseResponse, doneFrame, spies, clearSpies, resetChatTestState } from './use-sse-testkit';

beforeEach(() => {
  disconnectAgentStream();
  resetChatTestState();
  vi.mocked(startAgentTask).mockReset().mockResolvedValue({ task_id: 't1', project_id: 'p1' });
  vi.mocked(fetchAgentTaskEvents).mockReset();
  vi.mocked(stopAgentTask).mockReset().mockResolvedValue({ ok: true, cancelled: 1 });
  vi.mocked(listAgentTasks).mockReset().mockResolvedValue([]);
  vi.mocked(postAgentTaskGuidance).mockReset().mockResolvedValue({ ok: true });
  vi.mocked(showToast).mockClear();
  vi.mocked(requestInsertMedia).mockClear();
});

afterEach(() => {
  disconnectAgentStream();
  vi.useRealTimers();
  clearSpies();
});

describe('replay 快照 → 增量衔接', () => {
  it('运行中 replay：恢复累积快照后继续收增量，工具状态收窄', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      {
        type: 'replay',
        payload: {
          status: 'running', reasoning: 'R0', text: 'T0', status_text: '恢复中', model: 'm1',
          tools: [{ id: 'tl1', name: 'gen', summary: '生成', status: 'unexpected_value' }],
        },
      },
      { type: 'delta', text: '增量' },
      doneFrame('收尾'),
    ]));
    await streamAgentChat(req);
    expect(spies.restoreStreamingState).toHaveBeenCalledWith(expect.objectContaining({
      reasoning: 'R0', text: 'T0', statusText: '恢复中', model: 'm1',
    }));
    // 未知工具状态收窄为 running（防类型退化）；tools 参数可选，缺省按空列处理
    const tools = spies.restoreStreamingState.mock.calls[0][0].tools ?? [];
    expect(tools[0].status).toBe('running');
    expect(spies.appendDelta).toHaveBeenCalledWith('增量');
    expect(spies.finishStream).toHaveBeenCalledTimes(1);
  });

  it('非恢复期 replay done（断连期间任务完成）：走 handleDone 正常收尾', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      { type: 'replay', payload: { status: 'done', done_payload: { text: '断连期完成', elapsed_ms: 1, steps: 1 } } },
    ]));
    await streamAgentChat(req);
    expect(spies.finishStream.mock.calls[0][0].text).toBe('断连期完成');
  });

  it('replay error：断连期间任务出错，按 error_payload 归类落错误', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      {
        type: 'replay',
        payload: {
          status: 'error', error: '额度用尽', project_id: 'p1',
          error_payload: { code: 'err.quota.rate_limited', kind: 'quota' },
        },
      },
    ]));
    await streamAgentChat(req);
    expect(spies.streamError.mock.calls[0][0]).toEqual(expect.objectContaining({
      code: 'err.quota.rate_limited', kind: 'quota', message: '额度用尽',
    }));
    expect(state.agentBusy).toBe(false);
  });

  it('replay stopped（非恢复场景）：按 stopped_payload 补落停止痕迹', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      { type: 'replay', payload: { status: 'stopped', project_id: 'p1', stopped_payload: { phase: 'streaming' } } },
    ]));
    await streamAgentChat(req);
    expect(spies.cancelStream.mock.calls[0][0]).toEqual({ phase: 'streaming', inflight: undefined });
  });

  it('恢复场景 replay done：直接采用服务端快照不重复消息', async () => {
    const snapshotMsg = { sender: 'agent' as const, text: '快照消息' };
    vi.mocked(listAgentTasks).mockResolvedValue([
      { task_id: 't9', project_id: 'p1', status: 'running', created_at: 1 },
    ]);
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      {
        type: 'replay',
        payload: {
          status: 'done',
          done_payload: { text: 'x', elapsed_ms: 1, steps: 1 },
          snapshot: { chatMessages: [snapshotMsg] },
        },
      },
    ]));
    await resumeAgentTasks('p1');
    expect(spies.loadMessages).toHaveBeenCalledWith([snapshotMsg]);
    expect(spies.clearStreaming).toHaveBeenCalled();
    expect(spies.finishStream).not.toHaveBeenCalled(); // 不再走增量收尾，避免消息重复
    expect(state.agentBusy).toBe(false);
  });

  it('恢复场景 replay stopped：采用已持久化的停止痕迹快照', async () => {
    const snapshotMsg = { sender: 'agent' as const, text: '已在输出阶段停止' };
    vi.mocked(listAgentTasks).mockResolvedValue([
      { task_id: 't9', project_id: 'p1', status: 'stopped', created_at: 1 },
    ]);
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      {
        type: 'replay',
        payload: { status: 'stopped', snapshot: { chatMessages: [snapshotMsg] } },
      },
    ]));
    await resumeAgentTasks('p1');
    expect(spies.loadMessages).toHaveBeenCalledWith([snapshotMsg]);
    expect(spies.cancelStream).not.toHaveBeenCalled();
  });
});
