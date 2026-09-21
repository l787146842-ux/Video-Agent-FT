/**
 * 统一发送入口 submitMessage 四 intent 差异测试（任务 #30 发送路径收敛）。
 *
 * 钉死：
 * - new：序列化/校验/请求拼装单点（空内容、缺供应商拦截）；
 * - resend：富文本重发优先原 parts、纯文本回落；
 * - guidance：只登记运行中任务轮间注入 + 移队首，不新建任务；
 * - queued：出队按序发送；校验被拦截时原条目回队首不丢失。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { RichContentPart } from '@/types';

const prefsMock = vi.hoisted(() => ({ provider: 'mock-prov', model: 'mock-model' }));

vi.mock('@/hooks/use-sse', () => ({
  streamAgentChat: vi.fn(async () => {}),
  sendGuidanceToTask: vi.fn(),
}));
vi.mock('@/stores/agent-prefs', () => ({
  agentProvider: () => prefsMock.provider,
  agentModel: () => prefsMock.model,
  agentSkill: () => undefined,
  agentAssetMode: () => 'bound',
  agentThinkingLevel: () => '',
}));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { submitMessage, normalizeParts } from '../submit-message';
import { streamAgentChat, sendGuidanceToTask } from '@/hooks/use-sse';
import { chatState, chatActions, type QueuedMessage } from '@/stores/chat';
import { studioActions } from '@/stores/studio';
import { agentActions } from '@/stores/agent-state';
import { showToast } from '@/stores/toast';

function makeEntry(id: string, text: string, parts: RichContentPart[] = []): QueuedMessage {
  return { id, text, displayText: text, parts };
}

beforeEach(() => {
  prefsMock.provider = 'mock-prov';
  prefsMock.model = 'mock-model';
  chatActions.loadMessages([]);
  chatActions.clearQueuedMessages();
  chatActions.setInput('');
  agentActions.setAgentBusy(false);
  studioActions.setPendingAttachments([]);
  vi.mocked(streamAgentChat).mockClear();
  vi.mocked(sendGuidanceToTask).mockClear();
  vi.mocked(showToast).mockClear();
});

describe('submitMessage 序列化与校验（四路径单点）', () => {
  it('normalizeParts：字符串 → 单 text part；空白丢弃；空 text 片段过滤', () => {
    expect(normalizeParts('你好')).toEqual([{ type: 'text', text: '你好' }]);
    expect(normalizeParts('   ')).toEqual([]);
    expect(normalizeParts([
      { type: 'text', text: ' ' },
      { type: 'image', url: '/a.png', name: '图' },
      { type: 'text', text: '看这张' },
    ])).toEqual([
      { type: 'image', url: '/a.png', name: '图' },
      { type: 'text', text: '看这张' },
    ]);
  });

  it('new：受理发送 → 用户气泡上屏 + 请求拼装 + 输入清空', async () => {
    chatActions.setInput('草稿输入');
    const ok = await submitMessage('new', { input: '帮我写开场' });
    expect(ok).toBe(true);
    expect(chatState.messages).toHaveLength(1);
    expect(chatState.messages[0].sender).toBe('user');
    expect(chatState.inputText).toBe('');
    expect(streamAgentChat).toHaveBeenCalledTimes(1);
    const req = vi.mocked(streamAgentChat).mock.calls[0][0];
    expect(req.message).toBe('帮我写开场');
    expect(req.provider).toBe('mock-prov');
    expect(req.model).toBe('mock-model');
    expect(req.content_parts).toEqual([{ type: 'text', text: '帮我写开场' }]);
  });

  it('new：暂停回应即时回填 pauseAnswered*（A 批：气泡问答回执实时可渲染）', async () => {
    await submitMessage('new', {
      input: '16:9\n不显名',
      pauseResponse: {
        pause_id: 'p1', value: '16:9\n不显名',
        answers: [
          { id: 'ratio', selected: ['16:9'] },
          { id: 'naming', selected: ['不显名'] },
        ],
      },
    });
    const local = chatState.messages[0];
    expect(local.pauseAnsweredId).toBe('p1');
    expect(local.pauseAnsweredValue).toBe('16:9\n不显名');
    expect(local.pauseAnsweredAnswers).toEqual([
      { id: 'ratio', selected: ['16:9'] },
      { id: 'naming', selected: ['不显名'] },
    ]);
    // 请求体照旧携带 pause_response（后端消费链零改动）
    const req = vi.mocked(streamAgentChat).mock.calls[0][0];
    expect(req.pause_response?.pause_id).toBe('p1');
  });

  it('new：普通消息不产生 pauseAnswered* 字段（旧路径零变化）', async () => {
    await submitMessage('new', { input: '随便聊聊' });
    expect('pauseAnsweredId' in chatState.messages[0]).toBe(false);
    expect('pauseAnsweredAnswers' in chatState.messages[0]).toBe(false);
  });

  it('空内容拦截（不建任务、不进气泡）', async () => {
    expect(await submitMessage('new', { input: '   ' })).toBe(false);
    expect(streamAgentChat).not.toHaveBeenCalled();
    expect(chatState.messages).toHaveLength(0);
  });

  it('未选供应商/模型拦截并提示', async () => {
    prefsMock.provider = '';
    const ok = await submitMessage('new', { input: '你好' });
    expect(ok).toBe(false);
    expect(streamAgentChat).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalled();
  });
});

describe("intent='new' 忙碌排队判定", () => {
  it('忙碌中发送 → 入队 + 登记引导，不新建任务', async () => {
    agentActions.setAgentBusy(true);
    const ok = await submitMessage('new', { input: '换个风格' });
    expect(ok).toBe(true);
    expect(streamAgentChat).not.toHaveBeenCalled();
    expect(chatState.queuedMessages).toHaveLength(1);
    expect(chatState.queuedMessages[0].text).toBe('换个风格');
    expect(sendGuidanceToTask).toHaveBeenCalledWith(chatState.queuedMessages[0].id, '换个风格');
  });

  it('忙碌中暂停回应拒收（不得排队重发双发）', async () => {
    agentActions.setAgentBusy(true);
    const ok = await submitMessage('new', {
      input: '选A', pauseResponse: { pause_id: 'p1', value: 'A' },
    });
    expect(ok).toBe(false);
    expect(chatState.queuedMessages).toHaveLength(0);
  });
});

describe("intent='resend' 机械重发", () => {
  it('富文本重发：原 parts 含内联附件原样透传（不降级纯文本）', async () => {
    const parts: RichContentPart[] = [
      { type: 'text', text: '请看' },
      { type: 'image', url: '/workspace/assets/a.png', name: '元素A' },
    ];
    const ok = await submitMessage('resend', { input: parts });
    expect(ok).toBe(true);
    const req = vi.mocked(streamAgentChat).mock.calls[0][0];
    expect(req.content_parts).toEqual(parts);
    // 媒体占位进纯文本正文（历史/message 字段语义不变）
    expect(req.message).toContain('请看');
    expect(req.message).toContain('元素A');
    // 内联媒体随附件上行
    expect(req.attachments?.some((a) => a.url === '/workspace/assets/a.png')).toBe(true);
  });

  it('纯文本重发：字符串走同一序列化', async () => {
    await submitMessage('resend', { input: '原始问题' });
    const req = vi.mocked(streamAgentChat).mock.calls[0][0];
    expect(req.message).toBe('原始问题');
    expect(req.content_parts).toEqual([{ type: 'text', text: '原始问题' }]);
  });
});

describe("intent='guidance' 引导注入时机", () => {
  it('只登记运行中任务轮间注入 + 移队首，不新建任务', async () => {
    const e1 = makeEntry('q1', '第一条');
    const e2 = makeEntry('q2', '第二条');
    chatActions.enqueueMessage(e1);
    chatActions.enqueueMessage(e2);
    const ok = await submitMessage('guidance', { input: e2.text, queuedEntry: e2 });
    expect(ok).toBe(true);
    // 引导的条目移到队首（任务结束后优先出队）
    expect(chatState.queuedMessages[0].id).toBe('q2');
    expect(sendGuidanceToTask).toHaveBeenCalledWith('q2', '第二条');
    // 引导不新建任务、不新增气泡
    expect(streamAgentChat).not.toHaveBeenCalled();
    expect(chatState.messages).toHaveLength(0);
  });

  it('无排队条目的 guidance 直接拒收', async () => {
    expect(await submitMessage('guidance', { input: 'x' })).toBe(false);
    expect(sendGuidanceToTask).not.toHaveBeenCalled();
  });
});

describe("intent='queued' 排队出队顺序与失败回队", () => {
  it('出队按序发送：先队首后次条（FIFO）', async () => {
    const e1 = makeEntry('q1', '先发的', [{ type: 'text', text: '先发的' }]);
    const e2 = makeEntry('q2', '后发的', [{ type: 'text', text: '后发的' }]);
    chatActions.enqueueMessage(e1);
    chatActions.enqueueMessage(e2);

    // 自动出队第一拍：摘队首 → 统一入口发送
    chatActions.removeQueuedMessage('q1');
    expect(await submitMessage('queued', { input: e1.parts, queuedEntry: e1 })).toBe(true);
    expect(vi.mocked(streamAgentChat).mock.calls[0][0].message).toBe('先发的');

    // 第二拍：剩下的队首按序发出
    chatActions.removeQueuedMessage('q2');
    expect(await submitMessage('queued', { input: e2.parts, queuedEntry: e2 })).toBe(true);
    expect(vi.mocked(streamAgentChat).mock.calls[1][0].message).toBe('后发的');
  });

  it('校验被拦截（缺供应商）：原条目放回队首，id 与顺序不丢', async () => {
    const e1 = makeEntry('q1', '不能丢的消息', [{ type: 'text', text: '不能丢的消息' }]);
    chatActions.enqueueMessage(e1);
    chatActions.removeQueuedMessage('q1');
    prefsMock.provider = '';

    const ok = await submitMessage('queued', { input: e1.parts, queuedEntry: e1 });
    expect(ok).toBe(false);
    expect(streamAgentChat).not.toHaveBeenCalled();
    // 回队首：原 id 保留，消息不丢
    expect(chatState.queuedMessages).toHaveLength(1);
    expect(chatState.queuedMessages[0].id).toBe('q1');
  });

  it('空正文出队同样回队首（不得静默丢消息）', async () => {
    const e1 = makeEntry('q1', '', []);
    chatActions.enqueueMessage(e1);
    chatActions.removeQueuedMessage('q1');
    expect(await submitMessage('queued', { input: '', queuedEntry: e1 })).toBe(false);
    expect(chatState.queuedMessages[0].id).toBe('q1');
  });
});
