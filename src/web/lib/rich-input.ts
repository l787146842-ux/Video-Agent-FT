/**
 * 富文本输入通用工具（contenteditable）
 *
 * 供 Agent 对话输入框（ChatInput）使用：把图片/视频/音频以「内联缩略块」
 * 形式插入到光标处，与文字自由混排；发送时序列化为有序 RichContentPart[]，
 * 让 LLM 精确识别「文字 ↔ 媒体」的对应关系。
 *
 * 设计参考中间面板 PromptEditor 的 mention-chip 方案，但序列化目标不同：
 * 这里输出带 url/kind 的结构化片段（而非 @名称 文本）。
 */
import { safeUrl, uid } from './utils';
import type { Draft, InlineMedia, MediaType, RichContentPart } from '@/types';

/** 内联缩略块 DOM 类名（序列化/样式均依赖它） */
export const INLINE_MEDIA_CLASS = 'inline-media';
/** Skill 引用块 DOM 类名（下拉「+」插入的 Skill 名称块） */
export const SKILL_CHIP_CLASS = 'skill-chip';

/**
 * 创建 Skill 引用块节点：闪电图标 + 名称的圆角块（整体选中/删除）。
 * 序列化时作为纯文本（Skill 名称）拼入消息，供后端识别与文档面板定位。
 */
export function createSkillChip(name: string): HTMLSpanElement {
  const span = document.createElement('span');
  span.className = SKILL_CHIP_CLASS;
  span.contentEditable = 'false';
  span.dataset.skillName = name;
  span.title = `Skill：${name}`;
  const icon = document.createElement('span');
  icon.className = 'skill-chip-icon';
  icon.textContent = '⚡';
  const label = document.createElement('span');
  label.className = 'skill-chip-name';
  label.textContent = name;
  span.appendChild(icon);
  span.appendChild(label);
  return span;
}

/** 判断 URL 是否为图片（扩展名 / data:image），用于视频首帧海报判定 */
export function isImageUrl(url: string): boolean {
  if (!url) return false;
  if (url.startsWith('data:image/')) return true;
  return /\.(png|jpe?g|webp|gif|bmp)(\?|#|$)/i.test(url);
}

/** 媒体类型 → 纯文本占位符（供 message 字段 / 历史 / 气泡降级显示） */
export function mediaPlaceholder(kind: MediaType, name: string): string {
  const label = kind === 'image' ? '图片' : kind === 'video' ? '视频' : '音频';
  return `[${label}:${name}]`;
}

/**
 * 创建内联缩略块节点（只显示媒体本身，不带文字标签，名称放 title 悬浮提示）。
 * - image：<img> 缩略图
 * - video：海报图（有）或 <video> 首帧（#t=0.1）+ ▶ 角标
 * - audio：音符图标块
 * 节点 contentEditable=false（整体选中/删除），dataset 携带序列化所需元数据。
 */
export function createMediaChip(media: InlineMedia): HTMLSpanElement {
  const span = document.createElement('span');
  span.className = `${INLINE_MEDIA_CLASS} inline-media-${media.kind}`;
  span.contentEditable = 'false';
  span.dataset.mediaId = media.id;
  span.dataset.kind = media.kind;
  span.dataset.url = media.url;
  span.dataset.name = media.name;
  if (media.thumb) span.dataset.thumb = media.thumb;
  span.title = media.name;

  if (media.kind === 'image') {
    const img = document.createElement('img');
    img.src = safeUrl(media.thumb || media.url);
    img.alt = media.name;
    img.className = 'inline-media-thumb';
    span.appendChild(img);
  } else if (media.kind === 'video') {
    // 有海报图（关键元素首帧）用 <img>；否则用 <video> 渲染首帧
    const poster = isImageUrl(media.thumb || '') ? safeUrl(media.thumb || '') : '';
    if (poster) {
      const img = document.createElement('img');
      img.src = poster;
      img.alt = media.name;
      img.className = 'inline-media-thumb';
      span.appendChild(img);
    } else {
      const src = safeUrl(media.url);
      if (src) {
        const video = document.createElement('video');
        video.src = src.includes('#') ? src : `${src}#t=0.1`;
        video.muted = true;
        video.playsInline = true;
        video.preload = 'metadata';
        video.className = 'inline-media-thumb';
        span.appendChild(video);
      }
    }
    const badge = document.createElement('span');
    badge.className = 'inline-media-badge';
    badge.textContent = '▶';
    span.appendChild(badge);
  } else {
    const icon = document.createElement('span');
    icon.className = 'inline-media-audio';
    icon.textContent = '♬';
    span.appendChild(icon);
  }

  return span;
}

/**
 * 读取当前选中区域（仅当其落在编辑器内部），否则返回 null。
 * 供调用方在编辑器还有焦点时持续记录光标，失焦后仍可恢复。
 */
export function getEditorSelection(editor: HTMLElement): Range | null {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return null;
  const r = sel.getRangeAt(0);
  return editor.contains(r.commonAncestorContainer) ? r.cloneRange() : null;
}

/**
 * 在当前光标处插入节点。光标来源优先级：
 * 1) 当前选中区域（在编辑器内）；
 * 2) savedRange（编辑器失焦前记忆的光标，如右击卡片后）；
 * 3) 都没有 → 追加到末尾。
 * 插入后把光标移动到节点之后，并补一个尾随空格便于继续输入。
 */
export function insertNodeAtCursor(editor: HTMLElement, node: Node, savedRange?: Range | null): void {
  const sel = window.getSelection();
  let range: Range | null = null;

  if (sel && sel.rangeCount > 0) {
    const r = sel.getRangeAt(0);
    if (editor.contains(r.commonAncestorContainer)) range = r;
  }
  // 失焦后当前选中不在编辑器内 → 恢复记忆的光标（避免 focus 后caret 跳到开头）
  if (!range && savedRange && editor.contains(savedRange.commonAncestorContainer)) {
    range = savedRange;
  }

  editor.focus();

  if (!range) {
    // 追加到末尾：确保有分隔（若末尾已有内容）
    if (editor.lastChild && editor.textContent && editor.textContent.length > 0) {
      editor.appendChild(document.createTextNode('\u00a0'));
    }
    editor.appendChild(node);
    const nr = document.createRange();
    nr.setStartAfter(node);
    nr.collapse(true);
    if (sel) {
      sel.removeAllRanges();
      sel.addRange(nr);
    }
    return;
  }

  // 恢复记忆光标后再插入（针对 savedRange 分支）
  if (sel && sel.rangeCount > 0 && sel.getRangeAt(0) !== range) {
    sel.removeAllRanges();
    sel.addRange(range);
  }
  range.deleteContents();
  range.insertNode(node);
  // 尾随不间断空格，避免光标贴住 chip 无法输入
  const space = document.createTextNode('\u00a0');
  node.parentNode?.insertBefore(space, node.nextSibling);
  const nr = document.createRange();
  nr.setStartAfter(space);
  nr.collapse(true);
  if (sel) {
    sel.removeAllRanges();
    sel.addRange(nr);
  }
}

/**
 * 在光标处插入纯文本（用于空卡片回退、外部文本注入）。
 * 光标定位逻辑同 insertNodeAtCursor（当前选中 → savedRange → 末尾）。
 */
export function insertTextAtCursor(editor: HTMLElement, text: string, savedRange?: Range | null): void {
  if (!text) return;
  const sel = window.getSelection();
  let range: Range | null = null;
  if (sel && sel.rangeCount > 0) {
    const r = sel.getRangeAt(0);
    if (editor.contains(r.commonAncestorContainer)) range = r;
  }
  if (!range && savedRange && editor.contains(savedRange.commonAncestorContainer)) {
    range = savedRange;
  }
  editor.focus();
  if (range) {
    if (sel && sel.rangeCount > 0 && sel.getRangeAt(0) !== range) {
      sel.removeAllRanges();
      sel.addRange(range);
    }
    range.deleteContents();
    const tn = document.createTextNode(text);
    range.insertNode(tn);
    const nr = document.createRange();
    nr.setStartAfter(tn);
    nr.collapse(true);
    if (sel) {
      sel.removeAllRanges();
      sel.addRange(nr);
    }
    return;
  }
  editor.appendChild(document.createTextNode(text));
}

/**
 * DOM → 有序 RichContentPart[]。
 * 遍历顶层及嵌套节点：文本节点累积为 text 片段，缩略块产出媒体片段，
 * <br>/块级元素转换行。相邻 text 片段合并，空 text 丢弃。
 */
export function serializeEditorToParts(editor: HTMLElement): RichContentPart[] {
  const parts: RichContentPart[] = [];
  let textBuf = '';

  const flushText = () => {
    // 规范化不间断空格为普通空格；保留内部换行，仅去掉首尾空白
    const t = textBuf.replace(/\u00a0/g, ' ');
    if (t.trim()) {
      parts.push({ type: 'text', text: t.replace(/^\s+|\s+$/g, '') });
    }
    textBuf = '';
  };

  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      textBuf += node.nodeValue || '';
      return;
    }
    if (!(node instanceof HTMLElement)) return;
    if (node.classList.contains(SKILL_CHIP_CLASS)) {
      // Skill 引用块 → 纯文本（名称）拼入消息，保证发送时携带 Skill 名称
      textBuf += node.dataset.skillName || '';
      return;
    }
    if (node.classList.contains(INLINE_MEDIA_CLASS)) {
      flushText();
      const kind = (node.dataset.kind || 'image') as MediaType;
      const url = node.dataset.url || '';
      const name = node.dataset.name || '';
      const thumb = node.dataset.thumb || '';
      if (!url) return;
      if (kind === 'video') {
        // 携带首帧海报图（如有），后端会一并注入 LLM 让模型「看到」视频画面
        parts.push(thumb ? { type: 'video', url, name, thumb } : { type: 'video', url, name });
      } else if (kind === 'audio') {
        parts.push({ type: 'audio', url, name });
      } else {
        parts.push({ type: 'image', url, name });
      }
      return;
    }
    if (node.tagName === 'BR') {
      textBuf += '\n';
      return;
    }
    const isBlock = /^(DIV|P|LI)$/.test(node.tagName);
    if (isBlock && textBuf && !textBuf.endsWith('\n')) textBuf += '\n';
    node.childNodes.forEach(walk);
  };

  editor.childNodes.forEach(walk);
  flushText();
  return parts;
}

/** parts → 纯文本（媒体 → [图片:名称] 占位符），供 message 字段与降级显示 */
export function partsToPlainText(parts: RichContentPart[]): string {
  return parts
    .map((p) => (p.type === 'text' ? p.text : mediaPlaceholder(p.type, p.name)))
    .join('');
}

/** 编辑器 → 纯文本（媒体 → 占位符），供输入态同步 / mention 检测 */
export function editorToPlainText(editor: HTMLElement): string {
  return partsToPlainText(serializeEditorToParts(editor));
}

/** 编辑器是否为空（无文字且无缩略块） */
export function isEditorEmpty(editor: HTMLElement): boolean {
  return serializeEditorToParts(editor).length === 0;
}

/** 聚焦并把光标移到末尾 */
export function focusEditorAtEnd(editor: HTMLElement): void {
  editor.focus();
  const sel = window.getSelection();
  if (!sel) return;
  const range = document.createRange();
  range.selectNodeContents(editor);
  range.collapse(false);
  sel.removeAllRanges();
  sel.addRange(range);
}

/**
 * 草稿 → 内联媒体（无媒体文件时返回 null，调用方回退为文本引用）。
 * 视频：url=视频文件，thumb=关键元素首帧图（如有，供显示与注入 LLM）；音频无缩略图。
 */
export function draftToInlineMedia(draft: Draft): InlineMedia | null {
  const label = draft.label || draft.id;
  if (draft.mediaType === 'video') {
    const url = draft.videoUrl || '';
    if (!url) return null;
    // 仅当 imgUrl 为真实图片时才作为海报；否则留空（显示用视频首帧）
    const poster = isImageUrl(draft.imgUrl || '') ? draft.imgUrl || '' : '';
    return {
      id: uid('im'),
      name: label,
      url,
      kind: 'video',
      thumb: poster,
    };
  }
  if (draft.mediaType === 'audio') {
    const url = draft.audioUrl || '';
    if (!url) return null;
    return { id: uid('im'), name: label, url, kind: 'audio' };
  }
  // image
  const url = draft.imgUrl || '';
  if (!url || url.includes('picsum.photos')) return null;
  return { id: uid('im'), name: label, url, kind: 'image', thumb: url };
}
