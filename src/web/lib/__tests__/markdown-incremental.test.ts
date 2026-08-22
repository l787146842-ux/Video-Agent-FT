import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  splitSegments, renderMarkdownIncremental, createIncrementalCache,
} from '@/lib/markdown-incremental';
import { renderMarkdown } from '@/lib/markdown';

/** renderMarkdown 调用计数（增量缓存正确性的直接证据） */
vi.mock('@/lib/markdown', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/markdown')>();
  return { ...actual, renderMarkdown: vi.fn(actual.renderMarkdown) };
});

/** 既保留真实实现输出又可计数（vitest 4 的 Mock 默认泛型不可直接调用，交叉类型补回签名） */
type RenderSpy = ((src: string) => string) & ReturnType<typeof vi.fn>;
const renderSpy = renderMarkdown as unknown as RenderSpy;

describe('splitSegments（围栏外空行切段）', () => {
  it('拼接还原原文（不变式：closed.join + tail === src）', () => {
    const src = 'para one\n\npara two\n\npara three';
    const { closed, tail } = splitSegments(src);
    expect(closed.join('') + tail).toBe(src);
  });

  it('空行分界：前段闭合含分隔符，尾段为最后一个块', () => {
    const { closed, tail } = splitSegments('para one\n\npara two');
    expect(closed).toEqual(['para one\n\n']);
    expect(tail).toBe('para two');
  });

  it('未闭合代码围栏：围栏内空行不算边界，围栏起点后全部留在尾段', () => {
    const src = 'intro\n\n```python\nline1\n\nline2';
    const { closed, tail } = splitSegments(src);
    expect(closed).toEqual(['intro\n\n']);
    expect(tail).toBe('```python\nline1\n\nline2');
  });

  it('已闭合代码围栏：闭合后的空行正常分界', () => {
    const src = 'a\n\n```js\nx\n```\n\nb';
    const { closed, tail } = splitSegments(src);
    expect(closed).toEqual(['a\n\n', '```js\nx\n```\n\n']);
    expect(tail).toBe('b');
  });

  it('波浪线围栏同规格处理（~~~ 开闭、长度匹配）', () => {
    const src = 'a\n\n~~~\nx\n\ny\n~~~\n\nb';
    const { closed, tail } = splitSegments(src);
    expect(closed).toEqual(['a\n\n', '~~~\nx\n\ny\n~~~\n\n']);
    expect(tail).toBe('b');
  });

  it('表格尾段：单换行延续的表格行留在尾段整体增量解析', () => {
    const src = 'p\n\n| h1 | h2 |\n| --- | --- |\n| v1 |';
    const { closed, tail } = splitSegments(src);
    expect(closed).toEqual(['p\n\n']);
    expect(tail).toBe('| h1 | h2 |\n| --- | --- |\n| v1 |');
  });

  it('文本以空行收尾：空行随前段闭合，尾段为空串', () => {
    const { closed, tail } = splitSegments('done\n\n');
    expect(closed).toEqual(['done\n\n']);
    expect(tail).toBe('');
  });
});

describe('renderMarkdownIncremental（段落缓存 + 尾段增量）', () => {
  beforeEach(() => {
    renderSpy.mockClear();
  });

  it('首渲后追加尾段文本：闭合段命中缓存，仅尾段重新解析', () => {
    const cache = createIncrementalCache();
    renderMarkdownIncremental('para one\n\npara two', cache);
    expect(renderSpy).toHaveBeenCalledTimes(2); // 闭合段 + 尾段
    renderMarkdownIncremental('para one\n\npara two grows', cache);
    expect(renderSpy).toHaveBeenCalledTimes(3); // 仅尾段再解析一次
    expect(cache.entries.size).toBe(1);
    expect(cache.entries.has('para one\n\n')).toBe(true);
  });

  it('流式多 tick 追加：历史段解析次数恒定（O(尾段)，不再 O(n²)）', () => {
    const cache = createIncrementalCache();
    renderMarkdownIncremental('a\n\nb\n\nc', cache); // 3 次
    const base = renderSpy.mock.calls.length;
    for (let i = 0; i < 10; i += 1) {
      renderMarkdownIncremental(`a\n\nb\n\nc${'x'.repeat(i + 1)}`, cache);
    }
    expect(renderSpy.mock.calls.length - base).toBe(10); // 每 tick 只解析尾段
  });

  it('增量结果与全量渲染一致（闭合段逐字节相同）', () => {
    const cache = createIncrementalCache();
    const src = '# 标题\n\n段落 **加粗**\n\n- 列表项';
    const full = renderMarkdownFull(src);
    expect(renderMarkdownIncremental(src, cache)).toBe(full);
  });

  it('未闭合围栏尾段每 tick 增量解析且不产生脏缓存', () => {
    const cache = createIncrementalCache();
    renderMarkdownIncremental('intro\n\n```python\nprint(1)', cache);
    expect(cache.entries.size).toBe(1); // 仅 intro 段入缓存
    renderMarkdownIncremental('intro\n\n```python\nprint(1)\nprint(2)', cache);
    expect(cache.entries.size).toBe(1);
    expect(cache.entries.has('intro\n\n')).toBe(true);
  });

  it('围栏闭合后整块转为闭合段入缓存', () => {
    const cache = createIncrementalCache();
    renderMarkdownIncremental('a\n\n```js\nx\n```\n\nb', cache);
    expect(cache.entries.has('```js\nx\n```\n\n')).toBe(true);
  });

  it('空文本清空缓存（新流不复用旧段落）', () => {
    const cache = createIncrementalCache();
    renderMarkdownIncremental('a\n\nb', cache);
    expect(cache.entries.size).toBe(1);
    renderMarkdownIncremental('', cache);
    expect(cache.entries.size).toBe(0);
  });

  it('高亮升级通知：订阅者收到回调后可重渲染', () => {
    const cache = createIncrementalCache();
    const cb = vi.fn();
    const unsub = cache.subscribe(cb);
    // 直接触发内部通知路径（模拟 enhance 回写）
    cache.entries.set('k', 'v');
    // @ts-expect-error 测试内部通知器
    cache.notify();
    expect(cb).toHaveBeenCalledTimes(1);
    unsub();
    // @ts-expect-error 同上
    cache.notify();
    expect(cb).toHaveBeenCalledTimes(1);
  });
});

/** 全量渲染对照：spy 包装的是真实实现，直接调用即得未缓存的全量输出 */
function renderMarkdownFull(src: string): string {
  return renderSpy(src) as string;
}
