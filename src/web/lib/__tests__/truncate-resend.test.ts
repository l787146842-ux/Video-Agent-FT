/**
 * 截断重答动作通道测试（编辑与重新生成同源）。
 *
 * 钉死 truncateResendAction 编排：
 * ① 成功 = POST /chat/truncate-resend → 本地截断 → attachStartedTask 接管
 *    既有 SSE 订阅（无新订阅逻辑）；
 * ② 忙碌守卫兜底（UI 层不挂按钮，这里拒发）；
 * ③ 后端拒绝（400/409）时本地消息列表保持原样并弹 toast；
 * ④ 请求体携带 UI 选中的 provider/model/thinking_level；
 *    响应体 model 透传给 attachStartedTask（startStream 补流式模型徽标）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/stores/agent-prefs', () => ({
  agentProvider: () => 'provA',
  agentModel: () => 'modelA',
  agentThinkingLevel: () => 'high',
}));

const TARGET = { provider: 'provA', model: 'modelA', thinking_level: 'high' };

const apiMock = vi.fn(async (_text?: string | null, _target?: object) =>
  ({ task_id: 't1', project_id: 'p1', model: 'modelA' }));
vi.mock('@/api/chat', () => ({
  truncateResend: (text?: string | null, target?: object) => apiMock(text, target),
}));

const attachMock = vi.fn(async (_started: { task_id: string; project_id: string; model?: string }) => {});
vi.mock('@/hooks/use-sse', () => ({
  attachStartedTask: (started: { task_id: string; project_id: string; model?: string }) => attachMock(started),
}));

const toastMock = vi.fn();
vi.mock('@/stores/toast', () => ({
  showToast: (msg: string, kind: string) => toastMock(msg, kind),
}));

import { truncateResendAction } from '../chat/truncate-resend';
import { chatState, chatActions } from '@/stores/chat';
import { state, studioActions } from '@/stores/studio';
import { ApiError } from '@/api/client';

describe('truncateResendAction', () => {
  beforeEach(() => {
    apiMock.mockClear();
    attachMock.mockClear();
    toastMock.mockClear();
    studioActions.setAgentBusy(false);
    chatActions.loadMessages([
      { sender: 'user', text: '第二问' },
      { sender: 'agent', text: '旧回复' },
    ]);
  });

  it('编辑（带 text）：API 带正文与模型选择 → 本地截断替换 → 接管已启动任务', async () => {
    const ok = await truncateResendAction('改写后的问题');
    expect(ok).toBe(true);
    expect(apiMock).toHaveBeenCalledWith('改写后的问题', TARGET);
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].text).toBe('改写后的问题');
    expect(attachMock).toHaveBeenCalledWith({ task_id: 't1', project_id: 'p1', model: 'modelA' });
  });

  it('重新生成（无 text）：API 收 null（仍带模型选择），本地只截断不替换', async () => {
    const ok = await truncateResendAction();
    expect(ok).toBe(true);
    expect(apiMock).toHaveBeenCalledWith(null, TARGET);
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].text).toBe('第二问');
  });

  it('忙碌中拒发（兜底守卫）：不调 API、消息列表不动', async () => {
    studioActions.setAgentBusy(true);
    const ok = await truncateResendAction('x');
    expect(ok).toBe(false);
    expect(apiMock).not.toHaveBeenCalled();
    expect(chatState.messages.length).toBe(2);
    expect(state.agentBusy).toBe(true);
  });

  it('后端拒绝（如 409 AGENT_BUSY）：本地不截断，toast 报错', async () => {
    apiMock.mockRejectedValueOnce(new ApiError(409, 'AGENT_BUSY', { code: 'err.unknown.agent_busy', kind: 'unknown', message: '忙碌中' }));
    const ok = await truncateResendAction('x');
    expect(ok).toBe(false);
    expect(chatState.messages.length).toBe(2);
    expect(toastMock).toHaveBeenCalled();
    expect(toastMock.mock.calls[0][0]).toContain('忙碌中');
    expect(attachMock).not.toHaveBeenCalled();
  });
});
