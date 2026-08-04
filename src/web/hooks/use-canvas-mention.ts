import { createSignal, createResource } from 'solid-js';
import { fetchCanvasNodeImages, type CanvasNodeImageItem } from '@/api/canvas';

/**
 * @ 提及画布图片系统：管理提及弹层状态、候选列表与触发检测。
 * 选中后的「插入」动作由调用方负责（涉及编辑器特定的缩略块构建）。
 */
export function useCanvasMention() {
  const [mentionActive, setMentionActive] = createSignal(false);
  const [mentionQuery, setMentionQuery] = createSignal('');
  const [mentionIdx, setMentionIdx] = createSignal(0);

  /** 获取画布节点图片——只读当前画布内的图片，而非全部素材库。
   * source 为 mentionActive：仅在弹层激活时拉取，fetcher 内不再重复读信号 */
  const [canvasNodeImages] = createResource(
    () => mentionActive(),
    () => fetchCanvasNodeImages(),
    { initialValue: { items: [] as CanvasNodeImageItem[], canvas_online: true } },
  );

  /** 按 mentionQuery 过滤候选 */
  const mentionItems = () => {
    const source = canvasNodeImages()?.items ?? [];
    const q = mentionQuery().toLowerCase();
    if (!q) return source.slice(0, 20);
    return source.filter((it) => it.name.toLowerCase().includes(q)).slice(0, 20);
  };

  function closeMention() {
    setMentionActive(false);
    setMentionQuery('');
    setMentionIdx(0);
  }

  /** 根据当前光标所在文本节点检测 @ 触发 */
  function detectMention() {
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
    const m = /@([^\s@]*)$/.exec(before);
    if (m) {
      const charBefore = before.slice(0, before.length - m[0].length).slice(-1);
      // 行首 / 空白 / 标点后可触发；ASCII 字母数字后跳过（避免邮箱/URL 误触发）
      if (!charBefore || /[\s（(\[{,:;]/.test(charBefore)) {
        setMentionActive(true);
        setMentionQuery(m[1]);
        setMentionIdx(0);
        return;
      }
    }
    if (mentionActive()) closeMention();
  }

  return {
    mentionActive,
    mentionQuery,
    mentionIdx,
    setMentionIdx,
    canvasNodeImages,
    mentionItems,
    closeMention,
    detectMention,
  };
}
