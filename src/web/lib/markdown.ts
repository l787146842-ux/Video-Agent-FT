/**
 * Markdown 渲染器（基于 markdown-it）
 * 支持：标题/引用/列表/粗斜体/代码块/表格/链接/任务列表
 * 代码块增强：fence 输出包一层 .md-codeblock（语言标签 + 复制按钮），
 * 高亮由 lib/code-highlight 按需动态 import 后补刷（不阻塞首渲染，可 code-split）。
 */
import MarkdownIt from 'markdown-it';
import { t } from '@/lib/locale';

const md = new MarkdownIt({
  html: false,        // 禁止原始 HTML（防 XSS）
  linkify: true,      // 自动识别 URL
  typographer: true,  // 智能引号等排版优化
  breaks: true,       // 换行符转 <br>
});

// 链接安全：新窗口打开 + noopener
const defaultLinkOpen = md.renderer.rules.link_open || function (tokens, idx, options, _env, self) {
  return self.renderToken(tokens, idx, options);
};
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  const token = tokens[idx];
  token.attrSet('target', '_blank');
  token.attrSet('rel', 'noopener noreferrer');
  return defaultLinkOpen(tokens, idx, options, env, self);
};

// 代码块包装：语言标签 + 复制按钮（事件委托见 lib/code-copy，innerHTML 重刷不丢交互）；
// pre/code 仍走默认 fence 渲染（内容转义行为不变），info 串经 escapeHtml 防注入
const defaultFence = md.renderer.rules.fence || function (tokens, idx, options, _env, self) {
  return self.renderToken(tokens, idx, options);
};
md.renderer.rules.fence = (tokens, idx, options, env, self) => {
  const inner = defaultFence(tokens, idx, options, env, self);
  const lang = (tokens[idx].info || '').trim().split(/\s+/)[0] || '';
  const label = md.utils.escapeHtml(lang || t('rp.code.langPlain'));
  return `<div class="md-codeblock"><div class="md-codeblock-bar">`
    + `<span class="md-codeblock-lang">${label}</span>`
    + `<button type="button" class="md-codeblock-copy">${md.utils.escapeHtml(t('rp.code.copy'))}</button>`
    + `</div>${inner}</div>`;
};

export function renderMarkdown(src: string): string {
  if (!src) return '<p class="opacity-50">暂无内容</p>';
  return md.render(src);
}
