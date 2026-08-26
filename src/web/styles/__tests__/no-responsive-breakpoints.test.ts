/**
 * 批次G 断言①（前端体验规范 §三 桌面优先 / 台账 #21）：
 * 「无 @media 响应式断点」负向扫描——扫描 src/web 全部 CSS 源，
 * 断言不存在宽度/高度类响应式断点媒体查询。
 * 豁免口径：prefers-reduced-motion / prefers-color-scheme / pointer 等
 * 动效与色彩偏好查询不是响应式断点（批次B 的 reduced-motion 条款合法存续），
 * 只拦 min-width/max-width/min-height/max-height/width/height 类断点特性。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, it, expect } from 'vitest';

/** src/web 根（本文件位于 src/web/styles/__tests__/） */
const CSS_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

function walkCss(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walkCss(full));
    else if (entry.isFile() && entry.name.endsWith('.css')) out.push(full);
  }
  return out;
}

/** 宽度/高度类断点特性（媒体查询条件中的 width/height 即断点语义） */
const BREAKPOINT_FEATURE = /(min-|max-)?(width|height)\s*:/;

describe('桌面优先：无 @media 响应式断点（负向扫描）', () => {
  it('src/web 全部 CSS 不含宽高类断点媒体查询（动效/色彩偏好豁免）', () => {
    const hits: string[] = [];
    for (const file of walkCss(CSS_ROOT)) {
      // 去注释后只取 @media 前置条件段，声明块里的 min-width 等属性不受牵连
      const text = fs.readFileSync(file, 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '');
      for (const m of text.matchAll(/@media\s*([^{]+)\{/g)) {
        if (BREAKPOINT_FEATURE.test(m[1])) {
          hits.push(`${path.relative(CSS_ROOT, file)}: @media ${m[1].trim()}`);
        }
      }
    }
    expect(hits).toEqual([]);
  });

  it('豁免口径自检：偏好类查询放行、宽高断点拦截', () => {
    expect(BREAKPOINT_FEATURE.test('(prefers-reduced-motion: reduce)')).toBe(false);
    expect(BREAKPOINT_FEATURE.test('(prefers-color-scheme: dark)')).toBe(false);
    expect(BREAKPOINT_FEATURE.test('(pointer: coarse)')).toBe(false);
    expect(BREAKPOINT_FEATURE.test('(min-width: 768px)')).toBe(true);
    expect(BREAKPOINT_FEATURE.test('(max-height: 600px)')).toBe(true);
    expect(BREAKPOINT_FEATURE.test('screen and (width: 1024px)')).toBe(true);
  });
});
