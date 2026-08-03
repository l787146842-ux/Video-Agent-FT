import { describe, it, expect } from 'vitest';
import { renderMarkdown } from '@/lib/markdown';

describe('renderMarkdown', () => {
  it('渲染标题与列表', () => {
    const html = renderMarkdown('# 标题\n- 项目一\n- 项目二');
    expect(html).toContain('<h1');
    expect(html).toContain('标题');
    expect(html).toContain('<ul');
    expect(html).toContain('<li>项目一</li>');
  });

  it('渲染粗体与行内代码', () => {
    const html = renderMarkdown('这是 **粗体** 和 `代码`');
    expect(html).toContain('<strong>粗体</strong>');
    expect(html).toContain('<code>代码</code>');
  });

  it('HTML 转义防注入', () => {
    const html = renderMarkdown('<script>alert(1)</script>');
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('空输入返回占位', () => {
    expect(renderMarkdown('')).toContain('暂无内容');
  });

  it('引用块渲染', () => {
    const html = renderMarkdown('> 引用内容');
    expect(html).toContain('<blockquote');
    expect(html).toContain('引用内容');
  });
});
