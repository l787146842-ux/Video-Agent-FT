/**
 * 文档面板 store「存为文档」测试（任务 #6 C-2）。
 *
 * 钉死 defaultDocNameFor 的默认文档名派生：首行摘要名（去 markdown
 * 行首符号、截 24 字符、补 .md）；取不到摘要时回落「剧本-YYYY-MM-DD」。
 */
import { describe, expect, it } from 'vitest';
import { defaultDocNameFor } from '../docs';

const DAY = new Date(2026, 7, 23); // 2026-08-23（月份 0 基）

describe('defaultDocNameFor — 「存为文档」默认文档名', () => {
  it('取首个非空行去 markdown 行首符号作摘要名并补 .md', () => {
    expect(defaultDocNameFor('# 第一场：雨夜重逢\n\n正文……', DAY)).toBe('第一场：雨夜重逢.md');
    expect(defaultDocNameFor('\n\n> 引言一行', DAY)).toBe('引言一行.md');
  });

  it('首行超 24 字符时截断加省略号', () => {
    const long = '这是一个非常非常长的剧本首行标题，超过二十四个字符的限制';
    const name = defaultDocNameFor(long, DAY);
    expect(name).toBe(`${long.slice(0, 24)}….md`);
  });

  it('摘要行本身带 .md 后缀时不重复补', () => {
    expect(defaultDocNameFor('剧本定稿.md\n正文', DAY)).toBe('剧本定稿.md');
  });

  it('空正文/全空白回落「剧本-YYYY-MM-DD.md」', () => {
    expect(defaultDocNameFor('', DAY)).toBe('剧本-2026-08-23.md');
    expect(defaultDocNameFor('   \n\t\n', DAY)).toBe('剧本-2026-08-23.md');
    expect(defaultDocNameFor('## \n', DAY)).toBe('剧本-2026-08-23.md');
  });
});
