/**
 * 排队自动出队测试（任务 #30 E6；发送路径第四支：queued 意图的触发器）。
 *
 * 钉死：Agent 空闲且已选供应商模型时按 FIFO 自动摘队首并经统一入口
 * submitMessage('queued') 发送（携带原条目供失败回队）；
 * 忙碌 / 未选供应商模型 / 空队 三态不出队（消息留在队里不丢）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createRoot } from 'solid-js';

const prefsMock = vi.hoisted(() => ({ provider: 'mock-prov', model: 'mock-model' }));
const busyMock = vi.hoisted(() => ({ setBusy: (_v: boolean) => {} }));

vi.mock('@/lib/submit-message', () => ({
  // 受理后同步置忙（模拟真实 streamAgentChat 效果），后续拍被 agentBusy 挡住
  submitMessage: vi.fn(() => {
    busyMock.setBusy(true);
    return Promise.resolve(true);
  }),
}));
vi.mock('@/stores/agent-prefs', () => ({
  agentProvider: () => prefsMock.provider,
  agentModel: () => prefsMock.model,
}));

import { startQueuedAutosend } from '../chat-queue-autosend';
import { submitMessage } from '@/lib/submit-message';
import { chatState, chatActions } from '@/stores/chat';
import type { QueuedMessage } from '@/stores/chat';
import { studioActions } from '@/stores/studio';

busyMock.setBusy = (v: boolean) => studioActions.setAgentBusy(v);

/** 在响应式 root 内启动自动出队并等待 effect 首拍执行完 */
async function runAutosendOneTick(): Promise<void> {
  await createRoot(async (dispose) => {
    startQueuedAutosend();
    await new Promise((r) => setTimeout(r, 0));
    dispose();
  });
}

beforeEach(() => {
  prefsMock.provider = 'mock-prov';
  prefsMock.model = 'mock-model';
  chatActions.loadMessages([]);
  chatActions.clearQueuedMessages();
  studioActions.setAgentBusy(false);
  vi.mocked(submitMessage).mockClear();
});

describe('startQueuedAutosend（排队自动出队）', () => {
  it('空闲 + 有排队 + 已选模型：摘队首并走 submitMessage(queued) 携原条目', async () => {
    chatActions.enqueueMessage({ id: 'q1', text: '换个风格', displayText: '换个风格', parts: [] });
    chatActions.enqueueMessage({ id: 'q2', text: '再来一条', displayText: '再来一条', parts: [] });
    await runAutosendOneTick();
    // 一拍只摘队首一条：受理后置忙，q2 留待任务结束后按序出队
    expect(submitMessage).toHaveBeenCalledTimes(1);
    expect(submitMessage).toHaveBeenCalledWith('queued', expect.objectContaining({
      input: '换个风格',
      queuedEntry: expect.objectContaining({ id: 'q1' }),
    }));
    expect(chatState.queuedMessages.map((m) => m.id)).toEqual(['q2']);
  });

  it('富文本排队条目：优先原 parts 出队（不降级纯文本）', async () => {
    const parts = [{ type: 'text' as const, text: '看图说话' }];
    chatActions.enqueueMessage({ id: 'q1', text: '看图说话', displayText: '看图说话', parts });
    await runAutosendOneTick();
    expect(submitMessage).toHaveBeenCalledWith('queued', expect.objectContaining({ input: parts }));
  });

  it('旧格式条目（无 parts 键）：自动发送不抛错并回落纯文本', async () => {
    // localStorage 旧数据形态：无 parts 键（绕过归一化路径验证读取处双保险）
    const legacy = { id: 'q-old', text: '旧格式排队', displayText: '旧格式排队' } as unknown as QueuedMessage;
    chatActions.enqueueMessage(legacy);
    await runAutosendOneTick();
    expect(submitMessage).toHaveBeenCalledWith('queued', expect.objectContaining({
      input: '旧格式排队',
      queuedEntry: expect.objectContaining({ id: 'q-old' }),
    }));
  });

  it('Agent 忙碌中：不出队（等任务结束后再发）', async () => {
    studioActions.setAgentBusy(true);
    chatActions.enqueueMessage({ id: 'q1', text: '排队中', displayText: '排队中', parts: [] });
    await runAutosendOneTick();
    expect(submitMessage).not.toHaveBeenCalled();
    expect(chatState.queuedMessages).toHaveLength(1);
  });

  it('未选供应商/模型：不出队（消息留在队里不丢）', async () => {
    prefsMock.provider = '';
    chatActions.enqueueMessage({ id: 'q1', text: '等我选模型', displayText: '等我选模型', parts: [] });
    await runAutosendOneTick();
    expect(submitMessage).not.toHaveBeenCalled();
    expect(chatState.queuedMessages).toHaveLength(1);
  });

  it('空排队：不触发发送', async () => {
    await runAutosendOneTick();
    expect(submitMessage).not.toHaveBeenCalled();
  });
});
