/**
 * Markdown 渲染器（基于 markdown-it）
 * 支持：标题/引用/列表/粗斜体/代码块/表格/链接/任务列表
 */
import MarkdownIt from 'markdown-it';

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

export function renderMarkdown(src: string): string {
  if (!src) return '<p class="opacity-50">暂无内容</p>';
  return md.render(src);
}
