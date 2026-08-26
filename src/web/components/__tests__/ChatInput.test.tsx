/** ChatInput 交互测试：IME 组合输入保护 + Enter 发送 + 富文本序列化
 *  + 发送/停止键显隐互斥（批次G：规范 §二 / 台账 #3 补验） */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ChatInput } from '../right-panel/ChatInput';
import { studioActions } from '@/stores/studio';

const sendMock = vi.fn();

vi.mock('@/lib/agent-actions', () => ({
  // 返回 Promise<boolean>，与真实签名一致（doSend 依赖 .then 清空编辑器）
  sendUserMessage: (input: unknown) => {
    sendMock(input);
    return Promise.resolve(true);
  },
}));

vi.mock('@/hooks/use-sse', () => ({
  stopAgentStream: vi.fn(),
}));

vi.mock('@/api/upload', () => ({
  uploadFiles: vi.fn(async () => []),
}));

function getEditor(container: HTMLElement): HTMLDivElement {
  const el = container.querySelector('#chatInputTextarea');
  if (!el) throw new Error('富文本编辑器未渲染');
  return el as HTMLDivElement;
}

/** 构造一个内联缩略块节点（模拟左栏卡片右击插入的结果） */
function makeMediaChip(kind: string, url: string, name: string): HTMLSpanElement {
  const chip = document.createElement('span');
  chip.className = 'inline-media';
  chip.dataset.kind = kind;
  chip.dataset.url = url;
  chip.dataset.name = name;
  return chip;
}

describe('ChatInput 键盘发送', () => {
  beforeEach(() => {
    sendMock.mockClear();
  });

  it('普通 Enter 触发发送（纯文本序列化为单个 text part）', () => {
    const { container } = render(() => <ChatInput />);
    const editor = getEditor(container);
    editor.textContent = '你好，Agent';
    fireEvent.keyDown(editor, { key: 'Enter', shiftKey: false });
    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(sendMock).toHaveBeenCalledWith([{ type: 'text', text: '你好，Agent' }]);
  });

  it('文字与缩略块交错时，按排版顺序序列化 parts', () => {
    const { container } = render(() => <ChatInput />);
    const editor = getEditor(container);
    editor.appendChild(document.createTextNode('请看 '));
    editor.appendChild(makeMediaChip('image', '/workspace/assets/a.png', '元素A'));
    editor.appendChild(document.createTextNode(' 的画面'));
    fireEvent.keyDown(editor, { key: 'Enter', shiftKey: false });
    expect(sendMock).toHaveBeenCalledWith([
      { type: 'text', text: '请看' },
      { type: 'image', url: '/workspace/assets/a.png', name: '元素A' },
      { type: 'text', text: '的画面' },
    ]);
  });

  it('空内容 Enter 不发送', () => {
    const { container } = render(() => <ChatInput />);
    const editor = getEditor(container);
    fireEvent.keyDown(editor, { key: 'Enter', shiftKey: false });
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('IME 组合输入期间（isComposing）Enter 不发送', () => {
    const { container } = render(() => <ChatInput />);
    const editor = getEditor(container);
    editor.textContent = '你好';
    fireEvent.keyDown(editor, { key: 'Enter', isComposing: true });
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('keyCode 229（IME 处理中）Enter 不发送', () => {
    const { container } = render(() => <ChatInput />);
    const editor = getEditor(container);
    editor.textContent = '你好';
    fireEvent.keyDown(editor, { key: 'Enter', keyCode: 229 });
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('Shift+Enter 换行不发送', () => {
    const { container } = render(() => <ChatInput />);
    const editor = getEditor(container);
    editor.textContent = '你好';
    fireEvent.keyDown(editor, { key: 'Enter', shiftKey: true });
    expect(sendMock).not.toHaveBeenCalled();
  });
});

/** 发送/停止键显隐互斥（规范 §二：Agent 运行时只保留停止键，
 *  发送键仅空闲态显示；同一时刻只出现一个） */
describe('发送/停止键显隐互斥（台账 #3）', () => {
  afterEach(() => studioActions.setAgentBusy(false));

  const sendBtn = (c: HTMLElement) => c.querySelector('button.send-btn:not(.send-btn-stop)');
  const stopBtn = (c: HTMLElement) => c.querySelector('button.send-btn.send-btn-stop');

  it('空闲态：发送键显示、停止键不显示', () => {
    const { container } = render(() => <ChatInput />);
    expect(sendBtn(container)).toBeTruthy();
    expect(stopBtn(container)).toBeNull();
  });

  it('运行态：停止键显示、发送键隐藏', () => {
    const { container } = render(() => <ChatInput />);
    studioActions.setAgentBusy(true);
    expect(stopBtn(container)).toBeTruthy();
    expect(sendBtn(container)).toBeNull();
  });

  it('运行→空闲：恢复互斥发送键（两态往返不双显）', () => {
    const { container } = render(() => <ChatInput />);
    studioActions.setAgentBusy(true);
    studioActions.setAgentBusy(false);
    expect(sendBtn(container)).toBeTruthy();
    expect(stopBtn(container)).toBeNull();
  });
});
