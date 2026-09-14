/**
 * 分镜正文内联引用块纯工具（对齐 Flova 批）：正文里的引用 = 本镜 sceneRefs
 * 在 desc 文本中的视图。
 * - 识别：sceneRefs 解析为标题后在 desc 中出现的 → 内联块（最长优先防重叠误切）；
 * - 渲染：纯文本 ↔ DOM（块复用 mention-chip 概念图+名称 chip；编辑态块内带 ×）；
 * - 序列化：保存时块还原为纯名（desc 存储保持纯文本，不带 @ token）；
 * - 同步：编辑保存时 sceneRefs 按「旧 − 正文已消失提及 + @ 插入」派生。
 */
import { escapeRe, makeChip, type MediaKind } from '@/lib/prompt-ref-utils';
import type { ShotGroup } from '@/types';

export interface KeyElementLike {
  id?: string;
  title?: string;
  drafts?: Array<{ imgUrl?: string }>;
}

/** sceneRefs 存关键元素 id（ke-xxx）或标题；统一解析为标题（同 SceneRefsChips 口径） */
export function resolveRefTitle(ref: string, keyElements: KeyElementLike[]): string {
  const el = keyElements.find((k) => k.id === ref || k.title === ref);
  return el?.title || String(ref);
}

/** 内联块候选名：sceneRefs 解析标题、去重、按长度降序（最长优先） */
export function descChipNames(
  group: Pick<ShotGroup, 'sceneRefs'>,
  keyElements: KeyElementLike[],
): string[] {
  const titles = new Set<string>();
  (group.sceneRefs || []).forEach((r) => {
    const t = resolveRefTitle(String(r), keyElements);
    if (t) titles.add(t);
  });
  return [...titles].sort((a, b) => b.length - a.length);
}

/** 元素首张概念图（块缩略图）；无图返回 ''（渲染为纯名块，对齐 Flova pill） */
function elementThumb(title: string, keyElements: KeyElementLike[]): string {
  const el = keyElements.find((k) => k.title === title);
  return (el?.drafts || []).map((d) => d.imgUrl || '').find(Boolean) || '';
}

/** 纯文本 → 正文 DOM：命中标题渲染为 mention-chip 内联块；editable 时块内追加 ×
 *  删除钮；\n 保留在文本节点里（容器 pre-wrap 呈现分段）。 */
export function renderDescToDOM(
  el: HTMLElement,
  text: string,
  names: string[],
  keyElements: KeyElementLike[],
  editable: boolean,
): void {
  el.textContent = '';
  if (!text) return;
  if (!names.length) {
    el.textContent = text;
    return;
  }
  const re = new RegExp(`(${names.map(escapeRe).join('|')})`, 'g');
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) el.appendChild(document.createTextNode(text.slice(last, m.index)));
    const chip = makeChip(m[1], {
      url: elementThumb(m[1], keyElements),
      type: 'image' as MediaKind,
    });
    // 读态块可点跳转（覆盖 makeChip 的「点击放大」title）；编辑态块无独立动作
    chip.title = editable ? '' : '点击跳转到该关键元素';
    if (editable) {
      const x = document.createElement('span');
      x.className = 'desc-ref-remove';
      x.title = '移除该引用';
      x.textContent = '×';
      chip.appendChild(x);
    }
    el.appendChild(chip);
    last = m.index + m[0].length;
  }
  if (last < text.length) el.appendChild(document.createTextNode(text.slice(last)));
}

/** 正文 DOM → 纯文本（保存口径）：块还原为纯名（不带 @），块级边界还原 \n */
export function serializeDescDOM(root: HTMLElement): string {
  let out = '';
  let firstBlock = true;
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      // 不间断空格（chip 后的占位）规范化为普通空格，保证存储文本干净
      out += (node.nodeValue || '').replace(/\u00a0/g, ' ');
      return;
    }
    if (!(node instanceof HTMLElement)) return;
    if (node.classList.contains('mention-chip')) {
      out += node.dataset.name || '';
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

/** 编辑保存时 sceneRefs 同步：新 = 旧 − 正文已消失提及的引用 + @ 插入的标题。
 *  无增删返回 null（调用方不必写库）。 */
export function syncSceneRefsAfterEdit(
  prevRefs: string[],
  serializedText: string,
  insertedTitles: string[],
  keyElements: KeyElementLike[],
): string[] | null {
  const kept = prevRefs.filter((r) =>
    serializedText.includes(resolveRefTitle(String(r), keyElements)));
  const keptTitles = new Set(kept.map((r) => resolveRefTitle(String(r), keyElements)));
  const added = insertedTitles.filter((t) => !keptTitles.has(t));
  if (kept.length === prevRefs.length && !added.length) return null;
  return [...kept, ...added];
}
