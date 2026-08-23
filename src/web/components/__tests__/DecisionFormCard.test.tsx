/**
 * DecisionFormCard 结构化决策表单测试（任务 #3 A-2）。
 *
 * 钉死契约：
 * ① schema→表单数据驱动：text/number/select 三形态按 fields 渲染；
 * ② 提交走既有恢复通道：序列化「字段: 值」逐行发送 + pause_response 结构化回携；
 * ③ 必填未填禁提交；单发语义（sent 锁，连点不重发）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DecisionFormCard, decisionFormFields } from '../right-panel/DecisionFormCard';
import type { ChatMessage } from '@/types';

const sendMock = vi.fn();

vi.mock('@/lib/agent-actions', () => ({
  sendUserMessage: (input: unknown, opts?: unknown) => {
    sendMock(input, opts);
    return Promise.resolve(true);
  },
}));

/** 「几个分镜？画幅选哪个？」典型多字段参数决策 */
function formMessage(overrides?: Partial<ChatMessage>): ChatMessage {
  return {
    sender: 'agent',
    text: '',
    confirm: '进入分镜设计前需要确认几个参数',
    pauseId: 'pause_d1',
    decisionForm: {
      token: 'decision:run_1',
      node_id: 'storyboard_shots',
      message: '进入分镜设计前需要确认几个参数',
      schema: {
        type: 'decision',
        fields: [
          { key: 'shots', label: '几个分镜？', type: 'number', default: 8 },
          {
            key: 'ratio', label: '画幅选哪个？', type: 'select',
            options: [{ label: '16:9 横屏', value: '16:9' }, { label: '9:16 竖屏', value: '9:16' }],
          },
          { key: 'note', label: '补充说明', type: 'text', required: false },
        ],
      },
      options: [],
    },
    ...overrides,
  };
}

describe('DecisionFormCard 渲染（schema→表单数据驱动）', () => {
  beforeEach(() => sendMock.mockClear());

  it('按 schema.fields 渲染 number/select/text 三形态与默认值', () => {
    const { container } = render(() => <DecisionFormCard message={formMessage()} />);
    expect(container.querySelector('[data-testid="decision-form-card"]')).toBeTruthy();
    const number = container.querySelector('input[type="number"]') as HTMLInputElement;
    const text = container.querySelector('input[type="text"]') as HTMLInputElement;
    const select = container.querySelector('select') as HTMLSelectElement;
    expect(number).toBeTruthy();
    expect(number.value).toBe('8'); // schema default 入输入框
    expect(text).toBeTruthy();
    expect(select).toBeTruthy();
    expect(Array.from(select.options).map((o) => o.value)).toEqual(['', '16:9', '9:16']);
  });

  it('decisionFormFields 过滤无 key 字段（导出判定与挂载条件同源）', () => {
    const msg = formMessage();
    msg.decisionForm!.schema!.fields!.push({ key: '  ' } as never);
    expect(decisionFormFields(msg)).toHaveLength(3);
  });

  it('无 fields 的 decisionForm 不渲染表单（回落 ConfirmActions 口径）', () => {
    const msg = formMessage();
    msg.decisionForm = { token: 't', schema: {} };
    expect(decisionFormFields(msg)).toHaveLength(0);
  });
});

describe('DecisionFormCard 提交（既有恢复通道 + 留痕）', () => {
  beforeEach(() => sendMock.mockClear());

  it('序列化「字段: 值」逐行发送，携带 pause_response 结构化回携', async () => {
    const { container } = render(() => <DecisionFormCard message={formMessage()} />);
    const select = container.querySelector('select') as HTMLSelectElement;
    await fireEvent.change(select, { target: { value: '9:16' } });
    const btn = container.querySelector('.confirm-btn.primary') as HTMLButtonElement;
    await fireEvent.click(btn);
    expect(sendMock).toHaveBeenCalledTimes(1);
    const [text, opts] = sendMock.mock.calls[0];
    // 必填字段逐行序列化；可选字段未填不阻塞（空值行同样如实留痕）
    expect(text).toContain('几个分镜？: 8');
    expect(text).toContain('画幅选哪个？: 9:16');
    expect(opts).toMatchObject({ pauseResponse: { pause_id: 'pause_d1', value: text } });
  });

  it('必填未填禁提交；连点只发一次（sent 锁）', async () => {
    const { container } = render(() => <DecisionFormCard message={formMessage()} />);
    const btn = container.querySelector('.confirm-btn.primary') as HTMLButtonElement;
    // select 未选 → 必填缺失 → 禁用
    expect(btn.disabled).toBe(true);
    const select = container.querySelector('select') as HTMLSelectElement;
    await fireEvent.change(select, { target: { value: '16:9' } });
    expect(btn.disabled).toBe(false);
    await fireEvent.click(btn);
    await fireEvent.click(btn);
    await fireEvent.click(btn);
    expect(sendMock).toHaveBeenCalledTimes(1);
  });

  it('无 pauseId 时不带 pause_response（普通消息通道留痕）', async () => {
    const msg = formMessage({ pauseId: undefined });
    const { container } = render(() => <DecisionFormCard message={msg} />);
    const select = container.querySelector('select') as HTMLSelectElement;
    await fireEvent.change(select, { target: { value: '16:9' } });
    await fireEvent.click(container.querySelector('.confirm-btn.primary') as HTMLButtonElement);
    const [, opts] = sendMock.mock.calls[0];
    expect(opts).toBeUndefined();
  });
});
