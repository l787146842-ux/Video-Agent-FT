/**
 * 微调真子对话线程注册表单测（批 S3）：
 * ① openThread 幂等装载（在途去重 + 历史落视图 + 失败返回 false）；
 * ② sendAdjust 拒重复提交 + 请求形态（线程定向/瘦身/不带主对话附件技能）；
 * ③ appendEvent 推进（delta/工具/终态落消息与状态翻转）；
 * ④ 主标签栏双保险：已知线程对话不进对话清单（方案风险表「单测钉死三处一致」）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/api/conversations', () => ({ getOrCreateAdjustThread: vi.fn() }));
vi.mock('@/hooks/use-sse', () => ({ streamAgentChat: vi.fn(async () => {}) }));
vi.mock('@/stores/agent-prefs', () => ({ agentProvider: () => 'provA', agentModel: () => 'model-A' }));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { getOrCreateAdjustThread } from '@/api/conversations';
import { streamAgentChat } from '@/hooks/use-sse';
import { showToast } from '@/stores/toast';
import {
  adjustScopes, adjustScopeActions, threadConvIdOf, threadKeyOfConvId, isScopedConvId,
  type AdjustScopeTarget,
} from '../adjust-scopes';
import { agentActions } from '../agent-state';
import { convActions, convState } from '../conversations';

const target: AdjustScopeTarget = {
  kind: 'adjust', cat: 'keyElement', group_id: 'g1', draft_id: 'd1', label: '月球 第 1-1 卡',
};

beforeEach(() => {
  adjustScopeActions.reset();
  agentActions.resetBusy();
  vi.mocked(getOrCreateAdjustThread).mockReset();
  vi.mocked(streamAgentChat).mockReset().mockResolvedValue(undefined);
  vi.mocked(showToast).mockClear();
});

describe('openThread 幂等装载', () => {
  it('装载历史并置 open；并发调用只打一次幂等接口', async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({
      conversation_id: 'convT', messages: [{ sender: 'user', text: '历史消息' }],
    });
    const [a, b] = await Promise.all([adjustScopeActions.openThread(target), adjustScopeActions.openThread(target)]);
    expect(a).toBe(true);
    expect(b).toBe(true);
    expect(vi.mocked(getOrCreateAdjustThread)).toHaveBeenCalledTimes(1);
    expect(adjustScopes['d1'].convId).toBe('convT');
    expect(adjustScopes['d1'].open).toBe(true);
    expect(adjustScopes['d1'].messages).toHaveLength(1);
    expect(threadConvIdOf('d1')).toBe('convT');
    expect(threadKeyOfConvId('convT')).toBe('d1');
    expect(isScopedConvId('convT')).toBe(true);
  });

  it('接口失败返回 false（入口据此回落），不落登记', async () => {
    vi.mocked(getOrCreateAdjustThread).mockRejectedValue(new Error('404'));
    expect(await adjustScopeActions.openThread(target)).toBe(false);
    expect(adjustScopes['d1']).toBeUndefined();
  });

  it('契约字段缺失（无 conversation_id）同样视为不可用', async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({ conversation_id: '', messages: [] });
    expect(await adjustScopeActions.openThread(target)).toBe(false);
  });
});

describe('sendAdjust 提交与拒重复', () => {
  it('用户气泡落线程 + 瘦身请求定向线程（不带主对话附件/媒体/技能字段）', async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({ conversation_id: 'convT', messages: [] });
    vi.mocked(streamAgentChat).mockImplementation(async (_req, opts) => {
      opts?.onTaskStarted?.('tX', 'p1');
    });
    await adjustScopeActions.openThread(target);
    expect(adjustScopeActions.sendAdjust(target, '改亮一点')).toBe(true);

    expect(vi.mocked(streamAgentChat)).toHaveBeenCalledTimes(1);
    const [reqArg, optsArg] = vi.mocked(streamAgentChat).mock.calls[0];
    expect(optsArg).toMatchObject({ scope: true });
    expect(reqArg).toMatchObject({
      message: '改亮一点',
      conversation_id: 'convT',
      selected_draft_id: 'd1',
      selected_type: 'keyElement',
      provider: 'provA',
      model: 'model-A',
    });
    expect(reqArg?.adjust_scope).toMatchObject({ kind: 'adjust', cat: 'keyElement', group_id: 'g1', draft_id: 'd1' });
    // 瘦身：不携主对话附件/媒体清单/技能（历史由服务端装载为准）
    expect(reqArg?.attachments).toBeUndefined();
    expect(reqArg?.images).toBeUndefined();
    expect(reqArg?.videos).toBeUndefined();
    expect(reqArg?.content_parts).toBeUndefined();
    expect(reqArg?.skill_slug).toBeUndefined();
    // taskId 登记 + 用户气泡落线程 + 浮窗自动弹（=open）
    expect(adjustScopes['d1'].taskId).toBe('tX');
    expect(adjustScopes['d1'].status).toBe('running');
    expect(adjustScopes['d1'].open).toBe(true);
    expect(adjustScopes['d1'].messages.some((m) => m.sender === 'user' && m.text === '改亮一点')).toBe(true);
    expect(agentActions.isConvBusy('convT')).toBe(false); // 忙态登记归 use-sse 侧，store 不代登
  });

  it('同目标运行中拒重复提交（不建第二个任务 + toast 提示）', async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({ conversation_id: 'convT', messages: [] });
    vi.mocked(streamAgentChat).mockImplementation(async (_req, opts) => {
      opts?.onTaskStarted?.('tX', 'p1');
    });
    await adjustScopeActions.openThread(target);
    expect(adjustScopeActions.sendAdjust(target, '第一条')).toBe(true);
    expect(adjustScopeActions.sendAdjust(target, '第二条')).toBe(false);
    expect(vi.mocked(streamAgentChat)).toHaveBeenCalledTimes(1);
    expect(showToast).toHaveBeenCalled();
  });

  it('线程未就绪（未 openThread）拒提交', () => {
    expect(adjustScopeActions.sendAdjust(target, '空跑')).toBe(false);
    expect(streamAgentChat).not.toHaveBeenCalled();
  });
});

describe('appendEvent 推进线程视图', () => {
  beforeEach(async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({ conversation_id: 'convT', messages: [] });
    await adjustScopeActions.openThread(target);
  });

  it('delta/status/工具步骤推进流式视图', () => {
    adjustScopeActions.appendEvent('d1', { kind: 'delta', text: '你好' });
    adjustScopeActions.appendEvent('d1', { kind: 'delta', text: '，改好了' });
    adjustScopeActions.appendEvent('d1', { kind: 'status', text: '正在处理…' });
    adjustScopeActions.appendEvent('d1', { kind: 'tool_started', id: 'tl1', name: 'patch', summary: '改卡' });
    adjustScopeActions.appendEvent('d1', { kind: 'tool_finished', id: 'tl1', ok: true, elapsedMs: 120, resultSummary: '已改' });
    const st = adjustScopes['d1'].streaming;
    expect(st.text).toBe('你好，改好了');
    expect(st.statusText).toBe('正在处理…');
    expect(st.tools).toHaveLength(1);
    expect(st.tools[0]).toMatchObject({ id: 'tl1', status: 'done', elapsedMs: 120, resultSummary: '已改' });
  });

  it('done 终态：落 agent 消息（含图卡派生）+ 状态翻转空闲', () => {
    adjustScopeActions.registerTask('d1', 'tX');
    adjustScopeActions.appendEvent('d1', { kind: 'delta', text: '累积中' });
    adjustScopeActions.appendEvent('d1', {
      kind: 'done',
      payload: {
        text: '微调完成', elapsed_ms: 100, steps: 1, applied_actions: 1,
        chat_inserts: [{ kind: 'image', url: '/workspace/assets/a.png', name: 'a.png' }],
      },
    });
    const th = adjustScopes['d1'];
    expect(th.status).toBe('idle');
    expect(th.taskId).toBe('');
    expect(th.streaming.text).toBe('');
    const last = th.messages[th.messages.length - 1];
    expect(last.sender).toBe('agent');
    expect(last.text).toBe('微调完成');
    expect(last.imageCard?.image_urls).toEqual(['/workspace/assets/a.png']);
  });

  it('同轮 done 同源双达只落一次气泡（turn_id 幂等守卫，任务 #19）', () => {
    adjustScopeActions.registerTask('d1', 'tX');
    const payload = {
      text: '微调完成', elapsed_ms: 100, steps: 1, applied_actions: 1, turn_id: 'turn-9',
    };
    adjustScopeActions.appendEvent('d1', { kind: 'done', payload });
    // replay done 与增量 done 同源双达：同 turn_id 的终态帧重复派发
    adjustScopeActions.appendEvent('d1', { kind: 'done', payload });
    const agentDones = adjustScopes['d1'].messages.filter(
      (m) => m.sender === 'agent' && m.turnId === 'turn-9',
    );
    expect(agentDones).toHaveLength(1);
    expect(adjustScopes['d1'].status).toBe('idle');
  });

  it('error 终态：错误落线程消息并置 error 状态', () => {
    adjustScopeActions.appendEvent('d1', { kind: 'error', message: '出错了' });
    const th = adjustScopes['d1'];
    expect(th.status).toBe('error');
    expect(th.messages[th.messages.length - 1].text).toBe('出错了');
  });

  it('reasoning/round/message/replay 推进；stopped 落停止气泡并翻空闲', () => {
    adjustScopeActions.registerTask('d1', 'tX');
    adjustScopeActions.appendEvent('d1', { kind: 'reasoning', text: '思考中' });
    adjustScopeActions.appendEvent('d1', { kind: 'round', step: 1, max: 3 });
    adjustScopeActions.appendEvent('d1', { kind: 'message', message: { sender: 'agent', text: '插入消息' } });
    expect(adjustScopes['d1'].streaming.reasoning).toBe('思考中');
    expect(adjustScopes['d1'].streaming.roundStep).toBe(1);
    expect(adjustScopes['d1'].streaming.roundMax).toBe(3);
    expect(adjustScopes['d1'].messages.some((m) => m.text === '插入消息')).toBe(true);
    // replay 快照覆盖式装载（重连/惰性订阅恢复口径）
    adjustScopeActions.appendEvent('d1', {
      kind: 'replay', snapshot: { text: '快照文本', statusText: '恢复中', tools: [] },
    });
    expect(adjustScopes['d1'].streaming.text).toBe('快照文本');
    expect(adjustScopes['d1'].streaming.statusText).toBe('恢复中');
    // 孤儿 tool_finished（无对应 started）补录条目不崩；同名工具重复 started 就地刷新
    adjustScopeActions.appendEvent('d1', { kind: 'tool_finished', id: 'tlOrphan', ok: false, elapsedMs: 5 });
    adjustScopeActions.appendEvent('d1', { kind: 'tool_started', id: 'tlOrphan', name: 'patch', summary: '重试' });
    const tools = adjustScopes['d1'].streaming.tools;
    expect(tools.find((x) => x.id === 'tlOrphan')).toMatchObject({ status: 'running', name: 'patch' });
    adjustScopeActions.appendEvent('d1', { kind: 'stopped' });
    const th = adjustScopes['d1'];
    expect(th.status).toBe('idle');
    expect(th.taskId).toBe('');
    expect(th.streaming.active).toBe(false);
    expect(th.messages[th.messages.length - 1].sender).toBe('agent');
  });
});

describe('主标签栏双保险', () => {
  it('已知线程对话被过滤出对话清单（后端已过滤，前端再拦一道）', async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({ conversation_id: 'convT', messages: [] });
    await adjustScopeActions.openThread(target);
    convActions.syncFromServer({
      conversations: [
        { id: 'convMain', title: '会话 1' },
        { id: 'convT', title: '微调 | 月球' },
      ],
      activeConversationId: 'convMain',
    });
    expect(convState.list.map((c) => c.id)).toEqual(['convMain']);
  });
});
