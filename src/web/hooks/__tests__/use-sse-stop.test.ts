/**
 * hooks/use-sse.ts 引导登记与停止测试（任务 #30 传输层补强；按主题拆分）。
 *
 * 钉死：轮间引导登记（POST /guidance）与失败静默回落、停止按钮
 * /stop 竞速收尾、无活动任务停止、resume 早退。
 *
 * H2 回归（前端审核缺口：思考阶段点停止 = 静默丢弃）：
 * 端到端断言——无任何文本输出时点停止，消息流里必须出现可见的
 * 停止终态气泡（「已在思考阶段停止（未产生内容）」）+「继续刚才的任务」建议。
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
vi.mock('@/lib/chat/chat-input-bridge', () => ({ requestInsertMedia: vi.fn() }));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { streamAgentChat, disconnectAgentStream, stopAgentStream, sendGuidanceToTask, resumeAgentTasks } from '../use-sse';
import {
  startAgentTask, fetchAgentTaskEvents, stopAgentTask, listAgentTasks, postAgentTaskGuidance,
} from '@/api/sse';
import { chatState } from '@/stores/chat';
import { agentState } from '@/stores/agent-state';
import { showToast } from '@/stores/toast';
import { requestInsertMedia } from '@/lib/chat/chat-input-bridge';
import { req, hangingResponse, spies, clearSpies, resetChatTestState, tick } from './use-sse-testkit';

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

describe('引导登记（轮间注入）', () => {
  it('任务运行中登记引导：POST /guidance 携带任务 id 与排队 id', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(hangingResponse());
    void streamAgentChat(req);
    await tick();
    sendGuidanceToTask('q1', '加个彩蛋');
    expect(postAgentTaskGuidance).toHaveBeenCalledWith('t1', 'q1', '加个彩蛋');
    // 登记失败静默回落自动出队（不抛不 toast）
    vi.mocked(postAgentTaskGuidance).mockRejectedValueOnce(new Error('task gone'));
    sendGuidanceToTask('q2', '再来一条');
    await tick();
    expect(postAgentTaskGuidance).toHaveBeenCalledTimes(2);
  });

  it('无活动任务 / 空文本：不登记', () => {
    sendGuidanceToTask('q1', '没有任务');
    sendGuidanceToTask('q1', '   ');
    expect(postAgentTaskGuidance).not.toHaveBeenCalled();
  });
});

describe('停止按钮与终态痕迹', () => {
  it('停止按钮：等待 /stop 响应拿在途登记后交 cancelStream 并复位', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(hangingResponse());
    vi.mocked(stopAgentTask).mockResolvedValue({
      ok: true, cancelled: 1, inflight: [{ task_id: 'g1', media_type: 'image', summary: '海报' }],
    });
    void streamAgentChat(req);
    await tick();
    await stopAgentStream();
    expect(stopAgentTask).toHaveBeenCalledWith('t1');
    expect(spies.cancelStream).toHaveBeenCalledWith({
      inflight: [{ task_id: 'g1', media_type: 'image', summary: '海报' }],
    });
    expect(agentState.agentBusy).toBe(false);
  });

  it('无活动任务时点停止：仍落 cancelStream（本地推导阶段）', async () => {
    await stopAgentStream();
    expect(spies.cancelStream).toHaveBeenCalledWith({ inflight: undefined });
    expect(stopAgentTask).not.toHaveBeenCalled();
  });

  // ---------- H2 回归：思考中停止不得静默丢弃（可见终态） ----------
  it('H2：思考中（无任何文本输出）点停止 → 消息流落可见停止气泡 + 继续建议', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(hangingResponse());
    void streamAgentChat(req);
    await tick(); // 进入忙碌态，未收到任何 delta（仍在思考）
    await stopAgentStream();
    // cancelStream 收到无 phase 推导 → 本地无文本无工具 = thinking
    expect(spies.cancelStream).toHaveBeenCalledWith({ inflight: undefined });
    // 端到端可见性：消息流末尾是停止痕迹气泡，不是静默丢弃
    const last = chatState.messages[chatState.messages.length - 1];
    expect(last).toBeTruthy();
    expect(last.text).toContain('已在思考阶段停止（未产生内容）');
    expect(last.suggestedActions?.[0]).toEqual(expect.objectContaining({
      kind: 'retry', label: '继续刚才的任务',
    }));
    expect(chatState.isStreaming).toBe(false);
    expect(agentState.agentBusy).toBe(false);
  });

  it('resumeAgentTasks：无运行任务不建订阅；空 projectId 早退', async () => {
    await resumeAgentTasks('');
    await resumeAgentTasks('p1'); // listAgentTasks → []
    expect(fetchAgentTaskEvents).not.toHaveBeenCalled();
  });
});
