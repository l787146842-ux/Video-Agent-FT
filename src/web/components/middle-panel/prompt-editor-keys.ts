/**
 * 提示词编辑器键盘处理——自 PromptEditor.tsx 切出。
 * @ 提及弹层导航（上下/Enter 选中/Escape 关闭）+ @ 缩略块删除
 * （Backspace/Delete 紧邻 chip 时整体删除，视频 chip 等原生难删）。
 */
import type { usePromptMention } from '@/hooks/use-prompt-mention';

type MentionApi = ReturnType<typeof usePromptMention>;

/** @ 弹层导航：弹层打开时消费上下/Enter/Escape；返回是否已消费该按键 */
function handleMentionKeys(e: KeyboardEvent, mention: MentionApi): boolean {
  if (!mention.mentionActive()) return false;
  const list = mention.mentionItems();
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    mention.setMentionIdx((i) => (i + 1) % Math.max(1, list.length));
    return true;
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault();
    mention.setMentionIdx((i) => (i - 1 + list.length) % Math.max(1, list.length));
    return true;
  }
  if (e.key === 'Enter' && list.length > 0) {
    e.preventDefault();
    const idx = mention.mentionIdx();
    if (idx >= 0 && idx < list.length) mention.insertMentionChip(list[idx]);
    return true;
  }
  if (e.key === 'Escape') {
    e.preventDefault();
    mention.closeMention();
    return true;
  }
  return false;
}

/** 取光标紧邻的 @ 缩略块（Backspace 看前一节点，Delete 看当前节点） */
function adjacentChip(e: KeyboardEvent): HTMLElement | null {
  const sel = window.getSelection();
  if (!sel || !sel.isCollapsed || !sel.rangeCount) return null;
  const range = sel.getRangeAt(0);
  const node = range.startContainer;
  if (node.nodeType === Node.TEXT_NODE) {
    if (e.key === 'Backspace' && range.startOffset === 0) {
      const prev = node.previousSibling as HTMLElement | null;
      if (prev && prev.classList && prev.classList.contains('mention-chip')) return prev;
    }
    return null;
  }
  const idx2 = e.key === 'Backspace' ? range.startOffset - 1 : range.startOffset;
  const child = (node as HTMLElement).childNodes
    ? ((node as HTMLElement).childNodes[idx2] as HTMLElement | undefined)
    : undefined;
  if (child && child.classList && child.classList.contains('mention-chip')) return child;
  return null;
}

/** 编辑器 keydown 入口：先弹层导航，再 chip 整体删除（删除成功回刷草稿） */
export function promptEditorKeyDown(
  e: KeyboardEvent,
  mention: MentionApi,
  syncPrompt: () => void,
) {
  if (handleMentionKeys(e, mention)) return;
  // @ 缩略块删除：Backspace/Delete 紧邻 chip 时整体删除（视频 chip 等原生难删）
  if (e.key === 'Backspace' || e.key === 'Delete') {
    const chip = adjacentChip(e);
    if (chip) {
      e.preventDefault();
      chip.remove();
      syncPrompt();
    }
  }
}
