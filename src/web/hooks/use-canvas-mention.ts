import { createSignal, createResource, createEffect, onCleanup } from 'solid-js';
import { fetchCanvasNodeImages, type CanvasNodeImageItem } from '@/api/canvas';
import {
  startCanvasSelectionPolling, stopCanvasSelectionPolling, canvasSelection,
} from '@/stores/canvas';

/**
 * @ 提及画布图片系统：管理提及弹层状态、候选列表与触发检测。
 * 选中后的「插入」动作由调用方负责（涉及编辑器特定的缩略块构建）。
 *
 * 选中态联动：弹层打开期间轮询 /api/canvas/selection（离线/不支持自动停），
 * 当前选中的图片节点上浮到候选列表头部。
 */
export function useCanvasMention() {
  const [mentionActive, setMentionActive] = createSignal(false);
  const [mentionQuery, setMentionQuery] = createSignal('');
  const [mentionIdx, setMentionIdx] = createSignal(0);

  // 弹层打开→开始轮询选中态；关闭→停（轮询内部遇离线/不支持也会自停）
  createEffect(() => {
    if (mentionActive()) startCanvasSelectionPolling();
    else stopCanvasSelectionPolling();
  });

  // 组件卸载时强制停轮询：selectionTimer 为模块级全局，弹层激活中卸载时
  // effect 不会重跑，不停会泄漏 1.5s 定时器与请求
  onCleanup(() => stopCanvasSelectionPolling());

  /** 选中态中的图片节点 → @ 候选项（与全量节点图片同构，便于反向选中回链） */
  function selectionImageItems(): CanvasNodeImageItem[] {
    const sel = canvasSelection();
    if (!sel.supported || sel.nodes.length === 0) return [];
    const items: CanvasNodeImageItem[] = [];
    sel.nodes.forEach((n, i) => {
      if (n.type !== 'image') return;
      const url = String(n.metadata?.content || '');
      if (!/^https?:/.test(url)) return;
      items.push({
        id: `node-${n.id}-${i}`,
        name: n.title || `image-${i + 1}`,
        url,
        thumb: url,
        category: '画布选中',
      });
    });
    return items;
  }

  /** 获取画布节点图片——只读当前画布内的图片，而非全部素材库。
   * source 为 mentionActive：仅在弹层激活时拉取，fetcher 内不再重复读信号 */
  const [canvasNodeImages] = createResource(
    () => mentionActive(),
    () => fetchCanvasNodeImages(),
    { initialValue: { items: [] as CanvasNodeImageItem[], canvas_online: true } },
  );

  /** 按 mentionQuery 过滤候选（选中态图片去重后上浮头部） */
  const mentionItems = () => {
    const source = canvasNodeImages()?.items ?? [];
    const selected = selectionImageItems()
      .filter((s) => !source.some((it) => it.url === s.url));
    const merged = [...selected, ...source];
    const q = mentionQuery().toLowerCase();
    if (!q) return merged.slice(0, 20);
    return merged.filter((it) => it.name.toLowerCase().includes(q)).slice(0, 20);
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
