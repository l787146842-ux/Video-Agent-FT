/**
 * 聊天输入编辑区核心逻辑（从 ChatInput 拆出，控制组件行数）：
 * contenteditable 光标记忆、桥接插入请求消费、@ 提及替换、文本回填与发送序列化。
 * 纯逻辑无 JSX，渲染在 ChatInputEditor 组件；DOM 结构与行为零变化。
 */
import { createEffect, onMount, onCleanup } from 'solid-js';
import { chatActions } from '@/stores/chat';
import { showToast } from '@/stores/toast';
import { uid } from '@/lib/utils';
import {
  createMediaChip, createSkillChip, insertNodeAtCursor, insertTextAtCursor,
  serializeEditorToParts, editorToPlainText, getEditorSelection,
} from '@/lib/rich-input';
import { insertRequestCount, takeInsertRequests } from '@/lib/chat-input-bridge';
import { t } from '@/lib/locale';
import { useCanvasMention } from '@/hooks/use-canvas-mention';
import type { CanvasNodeImageItem } from '@/api/canvas';
import type { InlineMedia } from '@/types';

export function useChatEditor() {
  let editorEl: HTMLDivElement | undefined;
  /** 记忆的编辑器内光标（失焦后右击卡片插入时恢复，保证插在光标处而非开头） */
  let savedRange: Range | null = null;

  const mention = useCanvasMention();

  /** 供编辑器 div 的 ref 回写（组件侧 ref={h.setEditor}） */
  const setEditor = (el: HTMLDivElement) => { editorEl = el; };

  /** 持续记录编辑器内的光标位置（selectionchange 全局监听） */
  function captureSelection() {
    const el = editorEl;
    if (!el) return;
    const r = getEditorSelection(el);
    if (r) savedRange = r;
  }
  onMount(() => document.addEventListener('selectionchange', captureSelection));
  onCleanup(() => document.removeEventListener('selectionchange', captureSelection));

  /** 插入一个内联媒体缩略块到当前光标处，并同步纯文本状态 */
  function insertMedia(media: InlineMedia) {
    const el = editorEl;
    if (!el) return;
    insertNodeAtCursor(el, createMediaChip(media), savedRange);
    chatActions.setInput(editorToPlainText(el));
  }

  /**
   * 消费左栏卡片右击 / Skill 下拉「+」发来的插入请求：
   * 媒体 → 缩略块，Skill → 引用块（图标+名称），文本 → 直接插入，
   * 均落在记忆的光标处（无光标时追加到末尾）。
   */
  createEffect(() => {
    if (insertRequestCount() === 0) return;
    const reqs = takeInsertRequests();
    const el = editorEl;
    if (!el || reqs.length === 0) return;
    for (const req of reqs) {
      if (req.kind === 'media') {
        insertNodeAtCursor(el, createMediaChip(req.media), savedRange);
      } else if (req.kind === 'skill') {
        // 同名 Skill 块已存在时不重复插入
        const exists = Array.from(el.querySelectorAll('.skill-chip'))
          .some((n) => (n as HTMLElement).dataset.skillName === req.name);
        if (!exists) insertNodeAtCursor(el, createSkillChip(req.name), savedRange);
      } else if (req.kind === 'edit_backfill') {
        // 用户气泡「编辑」回填：与排队消息编辑同款换行追加语义
        backfillText(req.text);
      } else {
        insertTextAtCursor(el, req.text, savedRange);
      }
    }
    chatActions.setInput(editorToPlainText(el));
  });

  /** 双击缩略块：图片/视频放大预览（音频无画面，不处理） */
  function handleChipDblClick(e: MouseEvent) {
    const chip = (e.target as HTMLElement).closest('.inline-media') as HTMLElement | null;
    if (!chip) return;
    const url = chip.dataset.url || '';
    const kind = chip.dataset.kind || 'image';
    if (url && kind !== 'audio') return { url, kind };
    return null;
  }

  /** 选中一个 @ 图片：把光标处的 @query 替换为内联缩略块 */
  function selectMentionItem(item: CanvasNodeImageItem) {
    const el = editorEl;
    const sel = window.getSelection();
    if (!el || !sel || !sel.rangeCount) { mention.closeMention(); return; }
    const range = sel.getRangeAt(0);
    const node = range.startContainer;
    const offset = range.startOffset;
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.nodeValue || '';
      const before = text.slice(0, offset);
      const m = /@[^\s@]*$/.exec(before);
      if (m && node.parentNode) {
        node.nodeValue = before.slice(0, before.length - m[0].length);
        const afterText = text.slice(offset);
        const chip = createMediaChip({
          id: uid('im'), name: item.name, url: item.url,
          kind: 'image', thumb: item.thumb || item.url,
        });
        const space = document.createTextNode('\u00a0');
        const parent = node.parentNode;
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
    mention.closeMention();
    chatActions.setInput(editorToPlainText(el));
    showToast(t('rp.input.added', { name: item.name }), 'success');
  }

  function handleInput() {
    const el = editorEl;
    if (!el) return;
    chatActions.setInput(editorToPlainText(el));
    mention.detectMention();
  }

  /** 文本回填输入框（单一实现）：换行追加、不冲掉正在输入的内容；
   * 排队消息「编辑」与用户气泡「编辑」（edit_backfill 桥接请求）共用同款语义 */
  function backfillText(text: string) {
    const el = editorEl;
    if (!el || !text) return;
    insertTextAtCursor(el, (el.textContent ? '\n' : '') + text, savedRange);
    chatActions.setInput(editorToPlainText(el));
    el.focus();
  }

  /** @ 菜单键盘导航；返回 true 表示已消费按键（发送侧不再处理） */
  function handleMentionKeys(e: KeyboardEvent): boolean {
    if (!mention.mentionActive()) return false;
    const items = mention.mentionItems();
    if (e.key === 'ArrowDown') { e.preventDefault(); mention.setMentionIdx((i) => (i + 1) % items.length); return true; }
    if (e.key === 'ArrowUp') { e.preventDefault(); mention.setMentionIdx((i) => (i - 1 + items.length) % items.length); return true; }
    if (e.key === 'Enter' && items.length > 0) {
      e.preventDefault();
      const idx = mention.mentionIdx();
      if (idx >= 0 && idx < items.length) selectMentionItem(items[idx]);
      return true;
    }
    if (e.key === 'Escape') { e.preventDefault(); mention.closeMention(); return true; }
    return false;
  }

  /** 序列化编辑器为有序 parts（文字与缩略块按排版顺序） */
  const serializeParts = () => {
    const el = editorEl;
    return el ? serializeEditorToParts(el) : [];
  };

  /** 发送成功后清空编辑器与纯文本状态 */
  function clearEditor() {
    const el = editorEl;
    if (!el) return;
    el.innerHTML = '';
    chatActions.setInput('');
  }

  return {
    setEditor, mention, insertMedia, handleChipDblClick, selectMentionItem,
    handleInput, backfillText, handleMentionKeys, serializeParts, clearEditor,
  };
}
