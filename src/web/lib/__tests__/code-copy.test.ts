import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { handleCodeBlockClick, copyText } from '@/lib/code-copy';
import { renderMarkdown } from '@/lib/markdown';
import { showToast } from '@/stores/toast';

vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

/** jsdom 无 Clipboard API：按用例注入桩 */
function stubClipboard(writeText: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
  });
}

function mountCodeBlock(src = '```python\nprint("hi")\n```') {
  const host = document.createElement('div');
  host.innerHTML = renderMarkdown(src);
  document.body.appendChild(host);
  let pending: Promise<void> = Promise.resolve();
  host.addEventListener('click', (e) => { pending = handleCodeBlockClick(e as MouseEvent); });
  const btn = host.querySelector('.md-codeblock-copy') as HTMLButtonElement;
  return { host, btn, click: async () => { btn.dispatchEvent(new MouseEvent('click', { bubbles: true })); await pending; } };
}

describe('markdown fence 输出结构', () => {
  afterEach(() => document.body.innerHTML = '');

  it('代码块带工具条：语言标签 + 复制按钮', () => {
    const html = renderMarkdown('```python\nx = 1\n```');
    expect(html).toContain('md-codeblock');
    expect(html).toContain('md-codeblock-lang">python');
    expect(html).toContain('md-codeblock-copy');
    expect(html).toContain('<pre><code');
  });

  it('无语言标注时标签回退「文本」', () => {
    expect(renderMarkdown('```\nplain\n```')).toContain('md-codeblock-lang">文本');
  });

  it('语言 info 串转义防注入', () => {
    const html = renderMarkdown('```"><script>alert(1)</script>\ncode\n```');
    expect(html).not.toContain('<script>alert(1)</script>');
  });
});

describe('代码块复制（事件委托）', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(showToast).mockClear();
  });
  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('点击复制：写入剪贴板的是代码原文（textContent 还原转义）', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    const { click, btn } = mountCodeBlock('```python\nprint("hi")\n```');
    await click();
    expect(writeText).toHaveBeenCalledWith('print("hi")\n');
    // 内联成功反馈：文案切换，1.6s 后还原
    expect(btn.textContent).toBe('已复制');
    expect(btn.classList.contains('is-done')).toBe(true);
    vi.advanceTimersByTime(1600);
    expect(btn.textContent).toBe('复制');
    expect(btn.classList.contains('is-done')).toBe(false);
  });

  it('多语言转义内容复制还原（&lt; 等实体不落入剪贴板）', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    const { click } = mountCodeBlock('```html\n<div class="a">x</div>\n```');
    await click();
    expect(writeText).toHaveBeenCalledWith('<div class="a">x</div>\n');
  });

  it('点击非复制按钮区域不动作', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    const { host } = mountCodeBlock();
    let pending: Promise<void> = Promise.resolve();
    host.addEventListener('click', (e) => { pending = handleCodeBlockClick(e as MouseEvent); });
    host.querySelector('.md-codeblock-lang')!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await pending;
    expect(writeText).not.toHaveBeenCalled();
  });

  it('复制失败：toast 提醒手动复制，不切成功态', async () => {
    stubClipboard(() => Promise.reject(new Error('denied')));
    // execCommand 在 jsdom 未实现 → 回落也失败
    document.execCommand = vi.fn().mockReturnValue(false);
    const { click, btn } = mountCodeBlock();
    await click();
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('复制失败'), 'warning');
    expect(btn.textContent).toBe('复制');
  });

  it('copyText：Clipboard API 拒绝时回落 execCommand', async () => {
    stubClipboard(() => Promise.reject(new Error('denied')));
    document.execCommand = vi.fn().mockReturnValue(true);
    await expect(copyText('abc')).resolves.toBe(true);
    expect(document.execCommand).toHaveBeenCalledWith('copy');
  });
});
