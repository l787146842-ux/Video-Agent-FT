/** ChatInput 交互测试：IME 组合输入保护 + Enter 发送 + 富文本序列化 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ChatInput } from '../right-panel/ChatInput';

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
