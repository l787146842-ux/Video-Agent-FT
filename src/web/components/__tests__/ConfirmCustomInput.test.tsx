/**
 * ConfirmCustomInput 确定性覆盖（任务#9 前端棘轮回填）。
 *
 * 背景：展开聚焦路径走 requestAnimationFrame，此前由 ConfirmActions
 * 测试顺带覆盖，命中与否随测试结束时机抖动（覆盖率 68.65↔68.67 贴线
 * 波动的唯一来源）。本文件用假计时器钉死 rAF 回调执行，覆盖不再抖动。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { createSignal } from 'solid-js';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { ConfirmCustomInput } from '../right-panel/ConfirmCustomInput';

afterEach(() => vi.useRealTimers());

describe('ConfirmCustomInput（展开/聚焦/发送口径）', () => {
  it('展开后 rAF 回调聚焦组内输入框（假计时器确定性触发）', async () => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'requestAnimationFrame', 'cancelAnimationFrame', 'Date'],
    });
    const [open, setOpen] = createSignal(false);
    const onToggle = vi.fn((v: boolean) => setOpen(v));
    const { container, getByRole } = render(() => (
      <div class="confirm-wizard">
        <ConfirmCustomInput
          open={open}
          text={() => ''}
          onToggle={onToggle}
          onText={vi.fn()}
          onSend={vi.fn()}
        />
      </div>
    ));
    await fireEvent.click(getByRole('button'));
    expect(onToggle).toHaveBeenCalledWith(true);
    const ta = container.querySelector('.confirm-custom-input') as HTMLTextAreaElement;
    expect(ta).toBeTruthy();
    // rAF 回调此刻尚未执行；推进计时器后确定性聚焦
    expect(document.activeElement).not.toBe(ta);
    vi.advanceTimersByTime(50);
    expect(document.activeElement).toBe(ta);
  });

  it('收起态不渲染输入框；有草稿文本时按钮带 active 类', () => {
    const [open, setOpen] = createSignal(false);
    const [text] = createSignal('临时草稿');
    const { container, getByRole } = render(() => (
      <ConfirmCustomInput
        open={open}
        text={text}
        onToggle={setOpen}
        onText={vi.fn()}
        onSend={vi.fn()}
      />
    ));
    expect(container.querySelector('.confirm-custom-input')).toBeNull();
    expect(getByRole('button').className).toContain('active');
  });

  it('Ctrl/Cmd+Enter 发送 trim 后文本；普通回车只换行不发送', async () => {
    const [open] = createSignal(true);
    const [text] = createSignal('  自定义内容  ');
    const onSend = vi.fn();
    const { container } = render(() => (
      <ConfirmCustomInput
        open={open}
        text={text}
        onToggle={vi.fn()}
        onText={vi.fn()}
        onSend={onSend}
      />
    ));
    const ta = container.querySelector('.confirm-custom-input') as HTMLTextAreaElement;
    await fireEvent.keyDown(ta, { key: 'Enter' });
    expect(onSend).not.toHaveBeenCalled();
    await fireEvent.keyDown(ta, { key: 'Enter', ctrlKey: true });
    expect(onSend).toHaveBeenCalledWith('自定义内容');
  });

  it('输入即上抛 onText', () => {
    const [open] = createSignal(true);
    const onText = vi.fn();
    const { container } = render(() => (
      <ConfirmCustomInput
        open={open}
        text={() => ''}
        onToggle={vi.fn()}
        onText={onText}
        onSend={vi.fn()}
      />
    ));
    const ta = container.querySelector('.confirm-custom-input') as HTMLTextAreaElement;
    fireEvent.input(ta, { target: { value: '新的方向' } });
    expect(onText).toHaveBeenCalledWith('新的方向');
  });
});
