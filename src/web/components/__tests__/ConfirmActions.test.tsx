/**
 * ConfirmActions 交互测试（连点去重 + pause_response 全覆盖）。
 *
 * 钉死契约：
 * ① 暂停回应一经发出即锁，连点/双击不重复发送（防二次点击落入排队区后
 *    在任务结束后把同一回答自动重发一遍）；
 * ② 无选项确认同样携带 pause_response 结构化回携（对勾从后端权威登记派生，
 *    不再回落文本反推）；
 * ③ 选项卡发送携带机械 value（后端确定性消费）；
 * ④ 多组选项走分页向导：逐页选择、末页合并发一条（F0 安全绳扩围）；
 * ⑤ 自定义输入与卡片选择互斥，Ctrl+Enter 快捷发送；
 * ⑥ 厂商/模型维度渲染级联下拉而非选项卡（888 反馈）；
 * ⑦ 发送被拦截（返回 false）时解锁允许重试。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ConfirmActions } from '../right-panel/ConfirmActions';
import type { ChatMessage } from '@/types';

const sendMock = vi.fn();
/** sendUserMessage 返回值开关：false 模拟「被拦截（无供应商等）」 */
let sendOk = true;

vi.mock('@/lib/agent-actions', () => ({
  sendUserMessage: (input: unknown, opts?: unknown) => {
    sendMock(input, opts);
    return Promise.resolve(sendOk);
  },
}));
// 厂商/模型下拉的选项源桩（维度下拉分支不依赖真实 API 配置）
vi.mock('@/lib/providers', () => ({
  apiProvidersFor: () => [{ id: 'volc', name: '火山引擎' }],
  providerModels: () => ['doubao-seed'],
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

describe('ConfirmActions 单发语义与结构化回携', () => {
  beforeEach(() => {
    sendMock.mockClear();
    sendOk = true;
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

  it('发送被拦截（返回 false）时解锁，允许重试不卡死', async () => {
    sendOk = false;
    const { container } = render(() => <ConfirmActions message={pauseMessage()} />);
    const btn = container.querySelector('.confirm-actions .confirm-btn.primary') as HTMLButtonElement;
    await fireEvent.click(btn);
    expect(sendMock).toHaveBeenCalledTimes(1);
    // 拦截后 sent 锁释放：按钮可再次点击
    expect(btn.disabled).toBe(false);
    sendOk = true;
    await fireEvent.click(btn);
    expect(sendMock).toHaveBeenCalledTimes(2);
  });

  it('「我要调整」聚焦主输入框（焦点引导不发送）', async () => {
    const ta = document.createElement('textarea');
    ta.id = 'chatInputTextarea';
    document.body.appendChild(ta);
    try {
      const { getByText } = render(() => <ConfirmActions message={pauseMessage()} />);
      await fireEvent.click(getByText('我要调整'));
      expect(document.activeElement).toBe(ta);
      expect(sendMock).not.toHaveBeenCalled();
    } finally {
      ta.remove();
    }
  });
});

describe('ConfirmActions 分页向导（多组选项）', () => {
  beforeEach(() => {
    sendMock.mockClear();
    sendOk = true;
  });

  function groupedMessage(): ChatMessage {
    return pauseMessage([
      { label: '写实风', value: 'style_real', group: '画风' },
      { label: '水墨风', value: 'style_ink', group: '画风' },
      { label: '16:9 横屏', value: 'ratio_169', group: '画幅' },
    ]);
  }

  it('逐页选择、翻页导航，末页发送合并为一条消息（机械 value + 换行连接）', async () => {
    const { container, getByText } = render(() => <ConfirmActions message={groupedMessage()} />);
    // 第 1 页：组标题 + 页码指示；prev 首页禁用
    expect(container.querySelector('.confirm-wizard-question')?.textContent).toBe('画风');
    expect(container.querySelector('.confirm-wizard-indicator')?.textContent).toContain('1/2');
    const arrows = container.querySelectorAll('.confirm-wizard-arrow');
    expect((arrows[0] as HTMLButtonElement).disabled).toBe(true);
    // 未选择时「下一步」禁用；选中卡片后可翻页
    expect((getByText('下一步') as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.click(container.querySelectorAll('.confirm-option-card')[0]);
    await fireEvent.click(getByText('下一步'));
    // 第 2 页：选画幅后末页出现「发送」（非「下一步」）
    expect(container.querySelector('.confirm-wizard-question')?.textContent).toBe('画幅');
    expect(container.querySelector('.confirm-wizard-indicator')?.textContent).toContain('2/2');
    await fireEvent.click(container.querySelectorAll('.confirm-option-card')[0]);
    await fireEvent.click(getByText('发送'));
    expect(sendMock).toHaveBeenCalledTimes(1);
    const [text, opts] = sendMock.mock.calls[0];
    expect(text).toBe('style_real\nratio_169');
    expect(opts).toMatchObject({ pauseResponse: { pause_id: 'pause_001', value: text } });
  });

  it('翻页后 prev 箭头可回退（选择保留）', async () => {
    const { container, getByText } = render(() => <ConfirmActions message={groupedMessage()} />);
    await fireEvent.click(container.querySelectorAll('.confirm-option-card')[1]);
    await fireEvent.click(getByText('下一步'));
    const arrows = container.querySelectorAll('.confirm-wizard-arrow');
    expect((arrows[1] as HTMLButtonElement).disabled).toBe(true); // 末页 next 禁用
    await fireEvent.click(arrows[0]);
    expect(container.querySelector('.confirm-wizard-indicator')?.textContent).toContain('1/2');
    // 回退后既有选择保留（卡片 selected 态）
    expect(container.querySelectorAll('.confirm-option-card.selected').length).toBe(1);
  });

  it('厂商维度组渲染级联下拉（选厂商即可翻页，888 反馈）', async () => {
    const msg = pauseMessage([
      { label: '任意', group: '选择供应商' },
      { label: '16:9', value: 'ratio_169', group: '画幅' },
    ]);
    const { container, getByText } = render(() => <ConfirmActions message={msg} />);
    // 维度组渲染下拉框而非选项卡
    expect(container.querySelector('.confirm-option-card')).toBeNull();
    const selects = container.querySelectorAll('.confirm-select');
    expect(selects.length).toBe(2);
    // 未选厂商时「下一步」禁用
    expect((getByText('下一步') as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.change(selects[0], { target: { value: 'volc' } });
    expect((getByText('下一步') as HTMLButtonElement).disabled).toBe(false);
  });
});

describe('ConfirmActions 自定义输入（组内「其它」）', () => {
  beforeEach(() => {
    sendMock.mockClear();
    sendOk = true;
  });

  it('自定义输入与卡片选择互斥，Ctrl+Enter 快捷发送自定义内容', async () => {
    const msg = pauseMessage([
      { label: '方案一', value: 'v1' },
      { label: '方案二', value: 'v2' },
    ]);
    const { container, getByText } = render(() => <ConfirmActions message={msg} />);
    // 先选卡片
    await fireEvent.click(container.querySelectorAll('.confirm-option-card')[0]);
    expect(container.querySelectorAll('.confirm-option-card.selected').length).toBe(1);
    // 展开自定义输入框
    await fireEvent.click(getByText('其它（自定义输入）'));
    const ta = container.querySelector('.confirm-custom-input') as HTMLTextAreaElement;
    expect(ta).toBeTruthy();
    // 输入自定义内容即取消卡片选择（单选互斥）
    fireEvent.input(ta, { target: { value: '我想要别的方向' } });
    expect(container.querySelectorAll('.confirm-option-card.selected').length).toBe(0);
    // 提示语切换为自定义口径
    expect(container.querySelector('.confirm-wizard-hint')?.textContent).toBe('将发送自定义内容');
    // Ctrl+Enter 快捷发送（普通回车允许换行，不触发）
    await fireEvent.keyDown(ta, { key: 'Enter' });
    expect(sendMock).not.toHaveBeenCalled();
    await fireEvent.keyDown(ta, { key: 'Enter', ctrlKey: true });
    expect(sendMock).toHaveBeenCalledTimes(1);
    const [text, opts] = sendMock.mock.calls[0];
    expect(text).toBe('我想要别的方向');
    expect(opts).toMatchObject({ pauseResponse: { pause_id: 'pause_001', value: '我想要别的方向' } });
  });

  it('选中卡片即放弃自定义输入（反向互斥）', async () => {
    const msg = pauseMessage([{ label: '方案一', value: 'v1' }]);
    const { container, getByText } = render(() => <ConfirmActions message={msg} />);
    await fireEvent.click(getByText('其它（自定义输入）'));
    const ta = container.querySelector('.confirm-custom-input') as HTMLTextAreaElement;
    fireEvent.input(ta, { target: { value: '临时想法' } });
    // 再点卡片 → 自定义文本被清空，生效选择回到卡片
    await fireEvent.click(container.querySelector('.confirm-option-card') as HTMLButtonElement);
    expect((container.querySelector('.confirm-custom-input') as HTMLTextAreaElement).value).toBe('');
    await fireEvent.click(getByText('发送'));
    expect(sendMock.mock.calls[0][0]).toBe('v1');
  });
});
