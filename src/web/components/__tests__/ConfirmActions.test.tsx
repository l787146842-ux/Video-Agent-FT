/**
 * ConfirmActions 交互测试（批1 验收补测：连点去重 + pause_response 全覆盖）。
 *
 * 钉死契约：
 * ① 暂停回应一经发出即锁，连点/双击不重复发送（旧行为：第二次点击落入排队区，
 *    任务结束后把同一回答自动重发一遍）；
 * ② 无选项确认同样携带 pause_response 结构化回携（对勾从后端权威登记派生，
 *    不再回落文本反推）；
 * ③ 选项卡发送携带机械 value（后端确定性消费）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ConfirmActions } from '../right-panel/ConfirmActions';
import type { ChatMessage } from '@/types';

const sendMock = vi.fn();

vi.mock('@/lib/agent-actions', () => ({
  sendUserMessage: (input: unknown, opts?: unknown) => {
    sendMock(input, opts);
    return Promise.resolve(true);
  },
}));

function pauseMessage(options: Array<{ label: string; value?: string; group?: string }> = []): ChatMessage {
  return {
    sender: 'agent',
    text: '',
    confirm: '「剧本分析」已完成，是否进入下一阶段？',
    pauseId: 'pause_001',
    confirmOptions: options,
  };
}

describe('ConfirmActions 单发语义与结构化回携（批1）', () => {
  beforeEach(() => {
    sendMock.mockClear();
  });

  it('无选项确认携带 pause_response（结构化回携全覆盖）', async () => {
    const { getByText } = render(() => <ConfirmActions message={pauseMessage()} />);
    // rp.msg.confirmContinue 文案按钮
    const btn = getByText((_, el) => el?.tagName === 'BUTTON' && el.classList.contains('primary')) as HTMLButtonElement;
    await fireEvent.click(btn);
    expect(sendMock).toHaveBeenCalledTimes(1);
    const [text, opts] = sendMock.mock.calls[0];
    expect(typeof text).toBe('string');
    expect(opts).toMatchObject({ pauseResponse: { pause_id: 'pause_001' } });
  });

  it('连点同一确认按钮只发一次（sent 锁）', async () => {
    const { container } = render(() => <ConfirmActions message={pauseMessage()} />);
    const btn = container.querySelector('.confirm-actions .confirm-btn.primary') as HTMLButtonElement;
    expect(btn).toBeTruthy();
    await fireEvent.click(btn);
    await fireEvent.click(btn);
    await fireEvent.click(btn);
    expect(sendMock).toHaveBeenCalledTimes(1);
  });

  it('选项卡选择后发送携带机械 value，且连点不重发', async () => {
    const msg = pauseMessage([
      { label: '确认，进入「制作规格」', value: '确认，进入「制作规格」' },
      { label: '我要调整', value: '我要调整' },
    ]);
    const { container } = render(() => <ConfirmActions message={msg} />);
    // 选中第二张卡
    const cards = container.querySelectorAll('.confirm-option-card');
    expect(cards.length).toBe(2);
    await fireEvent.click(cards[1]);
    // 点发送（连点两次）
    const send = container.querySelector('.confirm-wizard-footer .confirm-btn.primary') as HTMLButtonElement;
    expect(send).toBeTruthy();
    await fireEvent.click(send);
    await fireEvent.click(send);
    expect(sendMock).toHaveBeenCalledTimes(1);
    const [text, opts] = sendMock.mock.calls[0];
    expect(text).toBe('我要调整');
    expect(opts).toMatchObject({ pauseResponse: { pause_id: 'pause_001', value: '我要调整' } });
  });
});
