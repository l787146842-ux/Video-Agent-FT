/**
 * hooks/use-sse.ts 增量事件路由与异常帧测试（任务 #30 传输层补强；按主题拆分）。
 *
 * 钉死：全帧型事件路由（status/delta/reasoning/tool/doc/fallback/guidance/
 * actions/task_status）、done chat_inserts 去重插入、异常帧不中断流。
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

import { streamAgentChat, disconnectAgentStream, getSseParseErrorCount } from '../use-sse';
import { startAgentTask, fetchAgentTaskEvents, stopAgentTask, listAgentTasks, postAgentTaskGuidance } from '@/api/sse';
import { chatActions } from '@/stores/chat';
import { showToast } from '@/stores/toast';
import { requestInsertMedia } from '@/lib/chat/chat-input-bridge';
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

describe('增量事件路由与异常帧', () => {
  const snapshot = {
    keyElements: [], shots: [], audioItems: [], assets: [], chatMessages: [], project_name: 'p',
  };

  it('全帧型路由：status/delta/reasoning/tool/doc/fallback/guidance/actions/task_status', async () => {
    chatActions.enqueueMessage({ id: 'q1', text: '换个风格', displayText: '换个风格', parts: [] });
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      { type: 'status', text: '正在处理…' },
      { type: 'reasoning_delta', text: '思考片段' },
      { type: 'tool_started', id: 'tl1', name: 'gen_image', summary: '生成海报', args: { prompt: '赛博海报' } },
      { type: 'tool_finished', id: 'tl1', ok: true, elapsed_ms: 900, result_summary: '出图完成' },
      { type: 'doc_written', name: '剧本.md', turn_id: 'turn-1' },
      { type: 'model_fallback', provider: 'mock', model: 'mock-chat' },
      { type: 'guidance_injected', id: 'q1', text: '换个风格' },
      { type: 'actions_applied', payload: { count: 2, state: snapshot } },
      { type: 'task_status', status: 'running' },
      { type: 'delta', text: '正文' },
      { type: 'done', payload: { text: '完成', elapsed_ms: 1, steps: 1, applied_actions: 1 } },
    ]));
    await streamAgentChat(req);

    expect(spies.setStatus).toHaveBeenCalledWith('正在处理…');
    expect(spies.appendReasoning).toHaveBeenCalledWith('思考片段');
    // 任务 #2：tool_started 的 args（后端裁剪脱敏预览）透传到 store
    expect(spies.toolStarted).toHaveBeenCalledWith('tl1', 'gen_image', '生成海报', { prompt: '赛博海报' });
    expect(spies.toolFinished).toHaveBeenCalledWith('tl1', true, 900, '出图完成', undefined);
    expect(spies.docWritten).toHaveBeenCalledWith('剧本.md', 'turn-1');
    // guidance_injected：用户气泡上屏 + 排队条目出队
    expect(spies.addMessage).toHaveBeenCalledWith({ sender: 'user', text: '换个风格' });
    expect(spies.removeQueuedMessage).toHaveBeenCalledWith('q1');
    expect(spies.appendDelta).toHaveBeenCalledWith('正文');
    expect(spies.finishStream).toHaveBeenCalledTimes(1);
  });

  it('done 携带 chat_inserts：去重后逐一插入媒体并提示', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      {
        type: 'done',
        payload: {
          text: '完成', elapsed_ms: 1, steps: 1,
          chat_inserts: [
            { kind: 'image', url: '/workspace/assets/x.png', name: 'x' },
            { kind: 'image', url: '/workspace/assets/x.png' }, // 重复 url 去重
          ],
        },
      },
    ]));
    await streamAgentChat(req);
    expect(requestInsertMedia).toHaveBeenCalledTimes(1);
    expect(showToast).toHaveBeenCalled(); // mediaInserted 提示
  });

  it('done 携带视频插入：kind=video 跳过输入框（内联卡为准），toast 计数不含视频', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      {
        type: 'done',
        payload: {
          text: '完成', elapsed_ms: 1, steps: 1,
          chat_inserts: [
            { kind: 'video', url: '/media/v.mp4', name: '开场', thumb: '/media/v.jpg' },
            { kind: 'image', url: '/workspace/assets/y.png', name: 'y' },
          ],
        },
      },
    ]));
    await streamAgentChat(req);
    // 只插入 image 项；视频由 finishStream 派生 videoCard 气泡，不双处呈现
    expect(requestInsertMedia).toHaveBeenCalledTimes(1);
    expect(requestInsertMedia).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'image', url: '/workspace/assets/y.png' }),
    );
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('1'), 'success');
  });

  it('done 仅携带视频插入：不插输入框也不弹 toast', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      {
        type: 'done',
        payload: {
          text: '完成', elapsed_ms: 1, steps: 1,
          chat_inserts: [{ kind: 'video', url: '/media/v.mp4', name: '开场' }],
        },
      },
    ]));
    await streamAgentChat(req);
    expect(requestInsertMedia).not.toHaveBeenCalled();
    expect(showToast).not.toHaveBeenCalled();
  });

  it('异常帧不中断流：JSON 解析失败计数 + 继续消费后续帧', async () => {
    const before = getSseParseErrorCount();
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      '{坏帧',   // JSON.parse 失败 → 计数不中断
      '[DONE]',  // 哨兵帧静默跳过
      doneFrame('仍然完成'),
    ]));
    await streamAgentChat(req);
    expect(getSseParseErrorCount()).toBe(before + 1);
    expect(spies.finishStream.mock.calls[0][0].text).toBe('仍然完成');
  });
});
