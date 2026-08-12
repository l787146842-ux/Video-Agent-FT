/**
 * Prompt 编辑器参考素材纯工具函数（从 PromptEditor.tsx 拆出，无组件依赖）
 *
 * 职责：
 * - 参考素材显示名/类型/绑定元素回查
 * - @提及 缩略块 chip 的 DOM 创建与 纯文本 <-> DOM 互转
 */
import { safeUrl } from '@/lib/utils';
import { storyboardMediaMap } from '@/lib/prompt-mentions';
import type { MediaType } from '@/types';

export type MediaKind = MediaType;

/** 分镜：参考图回查所属关键元素（显示标题 chips，不可删） */
export function boundAssetTitle(url: string, keyElements: Array<{ title: string; drafts?: Array<{ imgUrl?: string }> }>): string | null {
  for (const el of keyElements) {
    const hit = (el.drafts || []).find((d) => d.imgUrl === url);
    if (hit) return el.title;
  }
  return null;
}

/** 判断参考素材的媒体类型（优先回查关键元素草稿，其次按扩展名） */
export function refAssetType(url: string, keyElements: Array<{ drafts?: Array<{ imgUrl?: string; videoUrl?: string; audioUrl?: string }> }>): MediaKind {
  for (const g of keyElements) {
    for (const d of g.drafts || []) {
      if (d.imgUrl === url) return 'image';
      if (d.videoUrl === url) return 'video';
      if (d.audioUrl === url) return 'audio';
    }
  }
  if (/\.(mp4|webm|mov|m4v)(\?|#|$)/i.test(url)) return 'video';
  if (/\.(mp3|wav|ogg|m4a|flac|aac)(\?|#|$)/i.test(url)) return 'audio';
  return 'image';
}

/** 参考素材显示名（关键元素用分组标题，否则取文件名） */
export function refAssetName(url: string, idx: number, keyElements: Array<{ title: string; drafts?: Array<{ imgUrl?: string; videoUrl?: string; audioUrl?: string }> }>): string {
  for (const g of keyElements) {
    for (const d of g.drafts || []) {
      if (d.imgUrl === url || d.videoUrl === url || d.audioUrl === url) {
        return g.title;
      }
    }
  }
  const fname = url.split('/').pop()?.split('?')[0]?.split('#')[0];
  if (fname && fname.length <= 32) return fname;
  return `参考素材${idx + 1}`;
}

/** 视频缩略：定位到 0.1s 首帧 */
export function videoThumb(url: string): string {
  const u = safeUrl(url);
  return u.includes('#') ? u : `${u}#t=0.1`;
}

/** 名称 → 素材信息 映射（用于把纯文本 @名称 渲染为缩略块）。
 *  参考素材栏优先，另并入全故事板媒体（关键元素/分镜/音频），
 *  保证 @ 引用的故事板素材即使不在参考栏也能渲染为 chip。 */
export function buildRefAssetMap(
  refAssets: string[],
  keyElements: Array<{ title: string; drafts?: Array<{ imgUrl?: string; videoUrl?: string; audioUrl?: string }> }>,
): Record<string, { url: string; type: MediaKind }> {
  const map: Record<string, { url: string; type: MediaKind }> = {};
  for (const [name, info] of Object.entries(storyboardMediaMap())) {
    map[name] = { url: info.url, type: info.kind };
  }
  refAssets.forEach((url, i) => {
    const name = refAssetName(url, i, keyElements);
    map[name] = { url, type: refAssetType(url, keyElements) };
  });
  return map;
}

export function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** 创建一个 @提及 缩略块 chip（图片缩略图 / 视频首帧 / 音频图标）。
 *  dataset 携带 url/kind，供编辑器点击 chip 放大预览。 */
export function makeChip(name: string, info: { url: string; type: MediaKind }): HTMLSpanElement {
  const span = document.createElement('span');
  span.className = 'mention-chip';
  span.contentEditable = 'false';
  span.dataset.name = name;
  span.dataset.url = info.url || '';
  span.dataset.kind = info.type;
  span.title = '点击放大查看';
  if (info.type === 'image' && info.url) {
    const img = document.createElement('img');
    img.src = safeUrl(info.url);
    img.alt = name;
    span.appendChild(img);
  } else if (info.type === 'video' && info.url) {
    // 视频首帧缩略（#t=0.1 定位首帧）
    const vid = document.createElement('video');
    vid.src = videoThumb(info.url);
    vid.muted = true;
    vid.setAttribute('playsinline', '');
    vid.setAttribute('preload', 'metadata');
    span.appendChild(vid);
  } else {
    const icon = document.createElement('span');
    icon.className = 'mention-chip-icon';
    icon.textContent = info.type === 'video' ? '▶' : '♬';
    span.appendChild(icon);
  }
  const label = document.createElement('span');
  label.className = 'mention-chip-name';
  label.textContent = name;
  span.appendChild(label);
  return span;
}

/** 纯文本 → DOM（把匹配参考素材的 @名称 渲染为缩略块） */
export function renderPromptToDOM(
  el: HTMLElement,
  text: string,
  refMap: Record<string, { url: string; type: MediaKind }>,
): void {
  el.textContent = '';
  const names = Object.keys(refMap).sort((a, b) => b.length - a.length);
  if (!text) return;
  if (!names.length) {
    el.textContent = text;
    return;
  }
  const re = new RegExp(`[@＠](${names.map(escapeRe).join('|')})`, 'g');
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) el.appendChild(document.createTextNode(text.slice(last, m.index)));
    el.appendChild(makeChip(m[1], refMap[m[1]]));
    last = m.index + m[0].length;
  }
  if (last < text.length) el.appendChild(document.createTextNode(text.slice(last)));
}

/** DOM → 纯文本（缩略块还原为 @名称，供存储与发送给模型） */
export function serializeDOMToText(root: HTMLElement): string {
  let out = '';
  let firstBlock = true;
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      // 不间断空格（chip 后的占位）规范化为普通空格，保证存储/发送文本干净
      out += (node.nodeValue || '').replace(/\u00a0/g, ' ');
      return;
    }
    if (!(node instanceof HTMLElement)) return;
    if (node.classList.contains('mention-chip')) {
      out += `@${node.dataset.name || node.textContent || ''}`;
      return;
    }
    if (node.tagName === 'BR') { out += '\n'; return; }
    const isBlock = /^(DIV|P|LI)$/.test(node.tagName);
    if (isBlock && !firstBlock && out && !out.endsWith('\n')) out += '\n';
    firstBlock = false;
    node.childNodes.forEach(walk);
  };
  root.childNodes.forEach(walk);
  return out;
}
