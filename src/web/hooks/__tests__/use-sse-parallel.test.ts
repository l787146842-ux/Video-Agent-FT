/**
 * 批 6-2 多会话并行契约钉死（任务级连接注册表 + 事件按对话路由）。
 *
 * 钉死：
 * 1. 对话 A 任务运行中，对话 B 仍可提交新任务（同对话重复提交拒发）；
 * 2. 后台对话任务的事件不进聊天区（shadow 路由），忙态角标照常维护；
 * 3. 后台任务终态 → 未读角标 + toast 提示；忙态解除；
 * 4. 切回有运行中任务的对话（focusConversation）→ 重订阅 replay 恢复流式态。
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

import {
  streamAgentChat, disconnectAgentStream, resumeAgentTasks, focusConversation,
} from '../use-sse';
import { startAgentTask, fetchAgentTaskEvents, stopAgentTask, listAgentTasks, postAgentTaskGuidance } from '@/api/sse';
import { agentState, agentActions } from '@/stores/agent-state';
import { setConvState } from '@/stores/conversations';
import { showToast } from '@/stores/toast';
import { req, sseResponse, hangingResponse, doneFrame, spies, clearSpies, resetChatTestState, tick } from './use-sse-testkit';

beforeEach(() => {
  disconnectAgentStream();
  agentActions.resetBusy();
  resetChatTestState();
  vi.mocked(startAgentTask).mockReset();
  vi.mocked(fetchAgentTaskEvents).mockReset();
  vi.mocked(stopAgentTask).mockReset().mockResolvedValue({ ok: true, cancelled: 1 });
  vi.mocked(listAgentTasks).mockReset().mockResolvedValue([]);
  vi.mocked(postAgentTaskGuidance).mockReset().mockResolvedValue({ ok: true });
  vi.mocked(showToast).mockClear();
});

afterEach(() => {
  disconnectAgentStream();
  agentActions.resetBusy();
  clearSpies();
});

describe('多对话并行提交', () => {
  it('对话 A 运行中：对话 B 仍可提交；同对话重复提交拒发', async () => {
    setConvState({ list: [], activeId: 'convA' });
    vi.mocked(startAgentTask).mockResolvedValue({ task_id: 'tA', project_id: 'p1' });
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(hangingResponse());
    void streamAgentChat({ ...req, conversation_id: 'convA' });
    await tick();
    expect(agentActions.isConvBusy('convA')).toBe(true);

    // 同对话重复提交：不建第二个任务
    void streamAgentChat({ ...req, conversation_id: 'convA' });
    await tick();
    expect(vi.mocked(startAgentTask)).toHaveBeenCalledTimes(1);

    // 切到对话 B 提交：受理并建新任务
    setConvState({ list: [], activeId: 'convB' });
    vi.mocked(startAgentTask).mockResolvedValue({ task_id: 'tB', project_id: 'p1' });
    vi.mocked(fetchAgentTaskEvents)
      .mockResolvedValueOnce(hangingResponse());
    void streamAgentChat({ ...req, conversation_id: 'convB' });
    await tick();
    expect(vi.mocked(startAgentTask)).toHaveBeenCalledTimes(2);
    expect(agentActions.isConvBusy('convA')).toBe(true);
    expect(agentActions.isConvBusy('convB')).toBe(true);
  });
});

describe('后台对话事件路由（shadow）', () => {
  it('非活跃对话任务：增量不进聊天区；终态置未读并解除忙态', async () => {
    setConvState({ list: [], activeId: 'convB' });
    vi.mocked(listAgentTasks).mockResolvedValue([
      { task_id: 'tA', project_id: 'p1', conversation_id: 'convA', status: 'running', created_at: 1 },
    ]);
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      { type: 'replay', payload: { status: 'running', project_id: 'p1', reasoning: '', text: '累积正文', status_text: '运行中', tools: [] } },
      { type: 'delta', text: '后台增量' },
      doneFrame('后台完成'),
    ]));
    await resumeAgentTasks('p1');
    await tick();
    // shadow：增量与终态正文都不进聊天区
    expect(spies.appendDelta).not.toHaveBeenCalled();
    expect(spies.finishStream).not.toHaveBeenCalled();
    // 忙态解除 + 未读角标 + toast 提示
    expect(agentActions.isConvBusy('convA')).toBe(false);
    expect(agentState.unread['convA']).toBe(true);
    expect(showToast).toHaveBeenCalled();
  });

  it('活跃对话任务：照常实时渲染（live 路径不回归）', async () => {
    setConvState({ list: [], activeId: 'convA' });
    vi.mocked(startAgentTask).mockResolvedValue({ task_id: 'tA', project_id: 'p1' });
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      { type: 'delta', text: '实时增量' },
      doneFrame('完成'),
    ]));
    await streamAgentChat({ ...req, conversation_id: 'convA' });
    await tick();
    expect(spies.appendDelta).toHaveBeenCalledWith('实时增量');
    expect(spies.finishStream).toHaveBeenCalledTimes(1);
    expect(agentActions.isConvBusy('convA')).toBe(false);
  });
});

describe('切换对话聚焦（focusConversation）', () => {
  it('切到有运行中任务的对话：清未读 + 重订阅恢复流式态', async () => {
    setConvState({ list: [], activeId: 'convB' });
    vi.mocked(listAgentTasks).mockResolvedValue([
      { task_id: 'tA', project_id: 'p1', conversation_id: 'convA', status: 'running', created_at: 1 },
    ]);
    vi.mocked(fetchAgentTaskEvents)
      .mockResolvedValueOnce(sseResponse([
        { type: 'replay', payload: { status: 'running', project_id: 'p1', reasoning: '', text: '累积', status_text: '运行中', tools: [] } },
        doneFrame('完成'),
      ]));
    await resumeAgentTasks('p1');
    await tick();
    // 后台完成 → 未读置位
    expect(agentState.unread['convA']).toBe(true);

    // 再挂一个运行中任务供聚焦重订阅（fetch 挂起 = 保持运行中；
    // 挂起流下 resume 的 await 永不落，不阻塞测试主流程）
    vi.mocked(listAgentTasks).mockResolvedValue([
      { task_id: 'tA2', project_id: 'p1', conversation_id: 'convA', status: 'running', created_at: 2 },
    ]);
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(hangingResponse());
    void resumeAgentTasks('p1');
    await tick();
    expect(agentActions.isConvBusy('convA')).toBe(true);
    setConvState({ list: [], activeId: 'convA' });
    focusConversation('convA');
    await tick();
    expect(agentState.unread['convA']).toBeFalsy();
    expect(spies.restoreStreamingState).toHaveBeenCalled();
    expect(agentActions.isConvBusy('convA')).toBe(true);
  });
});
