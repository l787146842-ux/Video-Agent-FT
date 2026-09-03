/**
 * 任务 #8 机械断言（前端体验规范 §一 品牌与视觉 / §二 故事板微调框）：
 * 台账 #1/#2/#9(CSS 形态) 的 CSS 源码契约扫描。
 *
 * 口径说明：这三条均为纯样式条款，jsdom 不加载外部 CSS、无法算出计算样式，
 * 故沿用台账 #21（no-responsive-breakpoints）既有范式——直接扫描 CSS 源，
 * 把强制条款锁成源码契约（选择器改名/声明删改即红）。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, it, expect } from 'vitest';

/** src/web 根（本文件位于 src/web/styles/__tests__/） */
const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

function readSrc(rel: string): string {
  return fs.readFileSync(path.join(WEB_ROOT, rel), 'utf-8');
}

/** 去注释后，提取「以该选择器开头的一行」对应的声明块（行首锚定排除
 *  `html.light .xxx` 等派生选择器；支持多行规则，按花括号配对走位） */
function ruleBlock(cssRaw: string, selectorLine: RegExp): string {
  const css = cssRaw.replace(/\/\*[\s\S]*?\*\//g, '');
  const m = selectorLine.exec(css);
  if (!m) return '';
  const start = css.indexOf('{', m.index);
  let depth = 0;
  for (let i = start; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    else if (css[i] === '}') {
      depth -= 1;
      if (depth === 0) return css.slice(start + 1, i);
    }
  }
  return '';
}

/** 从 transition 声明中取指定属性的过渡时长（毫秒），未声明返回 null */
function transitionMs(block: string, prop: string): number | null {
  const m = block.match(/transition:\s*([^;]+);/);
  if (!m) return null;
  const part = m[1].split(',').map((s) => s.trim()).find((p) => p.startsWith(prop));
  if (!part) return null;
  const dur = part.match(/([0-9.]+)(ms|s)\b/);
  if (!dur) return null;
  return dur[2] === 'ms' ? Number(dur[1]) : Number(dur[1]) * 1000;
}

describe('台账 #1：品牌「飞天」字体栈/白色/22px/不加斜切/禁旧名', () => {
  const layoutCss = readSrc('styles/layout.css');
  const tokensCss = readSrc('styles/tokens.css');
  const brand = ruleBlock(layoutCss, /^[ \t]*\.brand-art[ \t]*\{/m);

  it('.brand-art 存在且为毛笔行楷字体栈（Xingkai/KaiTi + cursive 兜底）', () => {
    expect(brand).not.toBe('');
    const family = brand.match(/font-family:\s*([^;]+);/)?.[1] || '';
    expect(family).toContain("'Xingkai SC'");
    expect(family).toContain("'KaiTi'");
    expect(family).toMatch(/cursive\s*$/);
  });

  it('品牌字 22px：font-size 取 --font-4xl 令牌，令牌值锁定 22px', () => {
    expect(brand).toMatch(/font-size:\s*var\(--font-4xl\)/);
    expect(tokensCss).toMatch(/--font-4xl:\s*22px;/);
  });

  it('品牌字白色：color 取 --color-white 令牌，令牌值锁定 #fff', () => {
    // 亮色主题下 html.light .brand-art 转深色是源码内声明的可见性豁免（白底白字不可见），
    // 本条只锁暗色基准态。
    expect(brand).toMatch(/color:\s*var\(--color-white\)/);
    expect(tokensCss).toMatch(/--color-white:\s*#fff;/);
  });

  it('不加人工斜切（无 skew 变换）', () => {
    expect(brand).not.toMatch(/skew/);
  });

  it('品牌文案固定为「飞天」且全局唯一（禁止复活旧品牌名/改名）', () => {
    const header = readSrc('components/layout/Header.tsx');
    expect(header).toMatch(/class="brand-name brand-art">\s*飞天\s*<\/span>/);
    expect((header.match(/brand-name/g) || [])).toHaveLength(1);
  });
});

describe('台账 #2：顶部导航按钮绝对居中（两侧内容增减不得偏移）', () => {
  const layoutCss = readSrc('styles/layout.css');
  const nav = ruleBlock(layoutCss, /^[ \t]*\.studio-nav-links[ \t]*\{/m);
  const header = ruleBlock(layoutCss, /^[ \t]*\.studio-header[ \t]*\{/m);

  it('导航容器走绝对定位 + left:50% + translate(-50%) 居中契约', () => {
    expect(nav).not.toBe('');
    expect(nav).toMatch(/position:\s*absolute/);
    expect(nav).toMatch(/left:\s*50%/);
    expect(nav).toMatch(/transform:\s*translate\(-50%,\s*-50%\)/);
  });

  it('Header 为居中锚点（position: relative，否则绝对定位脱离顶栏）', () => {
    expect(header).toMatch(/position:\s*relative/);
  });
});

describe('台账 #9（CSS 形态）：微调框缓缓浮现，禁止瞬时弹出', () => {
  const leftCss = readSrc('styles/left-panel.css');
  const box = ruleBlock(leftCss, /^[ \t]*\.card-adjust-box[ \t]*\{/m);
  const open = ruleBlock(leftCss, /^[ \t]*\.card-adjust-box\.open[,\s]/m);

  it('收起态默认不可见（opacity:0 / max-height:0）', () => {
    expect(box).not.toBe('');
    expect(box).toMatch(/opacity:\s*0/);
    expect(box).toMatch(/max-height:\s*0/);
  });

  it('展开走 CSS transition：opacity 与 max-height 均有非零时长', () => {
    const opacityMs = transitionMs(box, 'opacity');
    const maxHeightMs = transitionMs(box, 'max-height');
    expect(opacityMs).not.toBeNull();
    expect(maxHeightMs).not.toBeNull();
    expect(opacityMs).toBeGreaterThan(0);
    expect(maxHeightMs).toBeGreaterThan(0);
  });

  it('open 态可见（与收起态形成渐现两相）', () => {
    expect(open).not.toBe('');
    expect(open).toMatch(/opacity:\s*1/);
  });
});

describe('D-09：作废暂停卡（expired 旧卡）去翡翠绿改中性灰 + 标题删除线', () => {
  const cardsCss = readSrc('styles/chat-cards.css');
  const voidCard = ruleBlock(cardsCss, /^[ \t]*\.stage-card-void[ \t]*\{/m);
  const voidTitle = ruleBlock(cardsCss, /^[ \t]*\.stage-card-void \.stage-card-title[ \t]*\{/m);
  // 去翡翠绿：对勾图标与标题共用一条降饱和分组规则（--text-dim）
  const voidDim = ruleBlock(cardsCss, /^[ \t]*\.stage-card-void \.stage-check,/m);

  it('.stage-card-void 根规则存在且边框改中性 --border-color（不再翡翠绿）', () => {
    expect(voidCard).not.toBe('');
    expect(voidCard).toMatch(/border-color:\s*var\(--border-color\)/);
    // 作废态不得沿用阶段卡翡翠绿族 token
    expect(voidCard).not.toMatch(/--color-stage/);
  });

  it('.stage-card-void 标题打删除线（作废/失效的通用视觉记号）', () => {
    expect(voidTitle).not.toBe('');
    expect(voidTitle).toMatch(/text-decoration:\s*line-through/);
  });

  it('作废态对勾图标/标题降饱和为 --text-dim（去翡翠绿、走语义色 token）', () => {
    expect(voidDim).not.toBe('');
    expect(voidDim).toMatch(/color:\s*var\(--text-dim\)/);
    expect(voidDim).not.toMatch(/--color-stage/);
  });
});
