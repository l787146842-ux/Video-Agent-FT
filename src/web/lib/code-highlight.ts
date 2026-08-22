/**
 * 代码高亮：highlight.js 核心 + 常用语言子集，按需加载。
 *
 * 包体策略：本模块只被 `import('@/lib/code-highlight')` 动态引用，
 * hljs core（~12KB gzip）+ 8 门常用语言定义被打成独立 chunk，
 * 首屏与流式首渲染不加载；首次出现代码块时才拉取并补刷高亮。
 * 未注册语言不高亮（保持转义后的纯文本，语义不受影响）。
 */
import hljs from 'highlight.js/lib/core';
import javascript from 'highlight.js/lib/languages/javascript';
import typescript from 'highlight.js/lib/languages/typescript';
import python from 'highlight.js/lib/languages/python';
import json from 'highlight.js/lib/languages/json';
import bash from 'highlight.js/lib/languages/bash';
import css from 'highlight.js/lib/languages/css';
import xml from 'highlight.js/lib/languages/xml';
import markdownLang from 'highlight.js/lib/languages/markdown';

// 模块被动态 import 时即完成语言注册（注册本身零成本，语法表懒到 chunk 里）
hljs.registerLanguage('javascript', javascript);
hljs.registerLanguage('js', javascript);
hljs.registerLanguage('typescript', typescript);
hljs.registerLanguage('ts', typescript);
hljs.registerLanguage('python', python);
hljs.registerLanguage('json', json);
hljs.registerLanguage('bash', bash);
hljs.registerLanguage('shell', bash);
hljs.registerLanguage('css', css);
hljs.registerLanguage('xml', xml);
hljs.registerLanguage('html', xml);
hljs.registerLanguage('markdown', markdownLang);
hljs.registerLanguage('md', markdownLang);

let ready: Promise<void> | null = null;

/** 高亮器就绪（当前实现注册即就绪；保留异步签名便于将来换 shiki 等真异步方案） */
export function loadHighlighter(): Promise<void> {
  if (!ready) ready = Promise.resolve();
  return ready;
}

/** 取 fence 输出的 class="language-xxx" 语言名 */
function langOfClass(className: string): string {
  const m = /language-([\w+-]+)/.exec(className || '');
  return m ? m[1] : '';
}

/** 对子树内未处理的 pre>code 就地高亮（data-hl 防重复；失败回落纯文本） */
function enhanceRoot(root: ParentNode): void {
  root.querySelectorAll('pre > code').forEach((node) => {
    const code = node as HTMLElement;
    if (code.dataset.hl) return;
    code.dataset.hl = '1'; // 先行标记：异常/未注册语言不反复重试
    const lang = langOfClass(code.className);
    if (!lang || !hljs.getLanguage(lang)) return;
    try {
      code.innerHTML = hljs.highlight(code.textContent || '', { language: lang }).value;
    } catch {
      /* 语法表异常：保留转义纯文本 */
    }
  });
}

/** DOM 就地高亮（流式尾段/最终消息渲染后调用；内部等待 chunk 加载） */
export async function highlightBlocks(root: ParentNode): Promise<void> {
  if (!root.querySelector('pre > code:not([data-hl])')) return;
  await loadHighlighter();
  enhanceRoot(root);
}

/** HTML 字符串高亮（增量渲染的已闭合段落缓存升级用：一次高亮，永久命中缓存） */
export async function enhanceHtmlString(html: string): Promise<string> {
  await loadHighlighter();
  const tpl = document.createElement('template');
  tpl.innerHTML = html;
  enhanceRoot(tpl.content);
  return tpl.innerHTML;
}
