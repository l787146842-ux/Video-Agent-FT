/**
 * 提示词编辑器 @提及 hook（从 PromptEditor.tsx 拆出）
 *
 * 职责：检测光标处 @ 触发、候选列表（参考素材栏 + 全故事板媒体）、
 * 选中后把 @query 替换为缩略块 chip，并自动把素材纳入参考栏。
 */
import { createSignal } from 'solid-js';
import { state, studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { storyboardMediaList } from '@/lib/prompt-mentions';
import {
  makeChip, refAssetName, refAssetType, type MediaKind,
} from '@/lib/prompt-ref-utils';
import type { DraftRecord } from '@/types';

/** @提及候选项（参考素材栏 + 全故事板媒体统一结构） */
export interface MentionItem { url: string; name: string; type: MediaKind; category?: 'keyElement' | 'shot' | 'audio' }

export interface PromptMentionOptions {
  /** contenteditable 编辑器元素 */
  editor: () => HTMLElement | undefined;
  /** 当前草稿（用于自动纳入参考栏） */
  rec: () => DraftRecord | undefined;
  /** 当前草稿参考素材 URL 列表 */
  refAssets: () => string[];
  /** 参考素材上限（shot=2 / 其他=5） */
  maxRefs: () => number;
  /** 编辑器内容变化后同步到草稿（重新序列化） */
  syncPrompt: () => void;
}

export function usePromptMention(opts: PromptMentionOptions) {
  const [mentionActive, setMentionActive] = createSignal(false);
  const [mentionQuery, setMentionQuery] = createSignal('');
  const [mentionIdx, setMentionIdx] = createSignal(0);
  // 弹层 fixed 坐标（锚定在光标处，避免被滚动容器裁剪）
  const [mentionPos, setMentionPos] = createSignal<{ bottom: number; left: number; width: number } | null>(null);

  /** 以光标位置计算弹层 fixed 坐标 */
  function updateMentionPos() {
    const sel = window.getSelection();
    let rect: DOMRect | null = null;
    if (sel && sel.rangeCount) rect = sel.getRangeAt(0).getBoundingClientRect();
    const editorEl = opts.editor();
    if (!rect || (rect.top === 0 && rect.bottom === 0 && rect.left === 0)) {
      rect = editorEl ? editorEl.getBoundingClientRect() : null;
    }
    if (!rect) return;
    setMentionPos({
      bottom: window.innerHeight - rect.top + 6,
      left: rect.left,
      width: 600,
    });
  }

  /** 上区：故事板素材（带分类，供面板分区/搜索） */
  const boardItems = (): MentionItem[] => {
    const q = mentionQuery().toLowerCase();
    const list: MentionItem[] = storyboardMediaList().map((b) => ({
      url: b.url, name: b.name, type: b.kind, category: b.category,
    }));
    if (!q) return list;
    return list.filter((it) => it.name.toLowerCase().includes(q));
  };

  /** 下区：当前草稿参考素材栏 */
  const refItems = (): MentionItem[] => {
    const q = mentionQuery().toLowerCase();
    const list: MentionItem[] = [];
    const seen = new Set<string>();
    opts.refAssets().forEach((url, i) => {
      if (seen.has(url)) return;
      seen.add(url);
      list.push({ url, name: refAssetName(url, i, state.keyElements), type: refAssetType(url, state.keyElements) });
    });
    if (!q) return list;
    return list.filter((it) => it.name.toLowerCase().includes(q));
  };

  /** 键盘导航用合并列表（参考栏优先 + 故事板，URL 去重） */
  const mentionItems = (): MentionItem[] => {
    const seen = new Set<string>();
    const merged: MentionItem[] = [];
    for (const it of [...refItems(), ...boardItems()]) {
      if (seen.has(it.url)) continue;
      seen.add(it.url);
      merged.push(it);
    }
    return merged;
  };

  function closeMention() {
    setMentionActive(false);
    setMentionQuery('');
    setMentionIdx(0);
  }

  /** 根据当前光标所在文本节点检测 @ 触发（兼容半角@与全角＠） */
  function detectMention() {
    // 参考栏与故事板都没有可引用媒体时才直接关闭
    if (!opts.refAssets().length && !storyboardMediaList().length) {
      if (mentionActive()) closeMention();
      return;
    }
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !sel.isCollapsed) {
      if (mentionActive()) closeMention();
      return;
    }
    const node = sel.anchorNode;
    const offset = sel.anchorOffset;
    if (!node || node.nodeType !== Node.TEXT_NODE) {
      if (mentionActive()) closeMention();
      return;
    }
    const before = (node.nodeValue || '').slice(0, offset);
    const m = /[@＠]([^\s@＠]*)$/.exec(before);
    if (m) {
      const charBeforeAt = before.slice(0, before.length - m[0].length).slice(-1);
      // 中文/空白/标点后均可触发；仅在 ASCII 字母数字后跳过（避免邮箱/URL 误触发）
      if (!charBeforeAt || !/[A-Za-z0-9]/.test(charBeforeAt)) {
        const wasActive = mentionActive();
        setMentionActive(true);
        setMentionQuery(m[1]);
        setMentionIdx(0);
        if (!wasActive) updateMentionPos();
        return;
      }
    }
    if (mentionActive()) closeMention();
  }

  /** 选中提及项：把光标处的 @query 替换为缩略块 chip；
   *  若素材不在参考栏且还有空位，自动纳入参考素材（保证生成时随请求发送） */
  function insertMentionChip(item: MentionItem) {
    const r = opts.rec();
    if (r && item.url && !(r.draft.refAssets || []).includes(item.url)) {
      const refs = r.draft.refAssets || [];
      if (refs.length < opts.maxRefs()) {
        studioActions.updateDraftLocal(r.type, r.draft.id, { refAssets: [...refs, item.url] });
      } else {
        showToast(`参考素材栏已满（${opts.maxRefs()} 个）：生成时将优先发送已有参考，该提及仅保留文字`, 'warning');
      }
    }
    const el = opts.editor();
    const sel = window.getSelection();
    if (!el || !sel || !sel.rangeCount) { closeMention(); return; }
    const range = sel.getRangeAt(0);
    const node = range.startContainer;
    const offset = range.startOffset;
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.nodeValue || '';
      const before = text.slice(0, offset);
      const m = /[@＠][^\s@＠]*$/.exec(before);
      if (m) {
        const atStart = before.length - m[0].length;
        node.nodeValue = before.slice(0, atStart);
        const afterText = text.slice(offset);
        const chip = makeChip(item.name, { url: item.url, type: item.type });
        const space = document.createTextNode('\u00a0');
        const parent = node.parentNode;
        if (parent) {
          parent.insertBefore(chip, node.nextSibling);
          parent.insertBefore(space, chip.nextSibling);
          if (afterText) parent.insertBefore(document.createTextNode(afterText), space.nextSibling);
          const nr = document.createRange();
          nr.setStartAfter(space);
          nr.collapse(true);
          sel.removeAllRanges();
          sel.addRange(nr);
        }
      }
    }
    closeMention();
    opts.syncPrompt();
  }

  return {
    mentionActive, mentionQuery, setMentionQuery, mentionIdx, setMentionIdx, mentionPos,
    mentionItems, boardItems, refItems, closeMention, detectMention, insertMentionChip,
  };
}
