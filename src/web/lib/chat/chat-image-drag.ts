/**
 * 聊天消息图片拖拽逻辑（拖进文件夹/桌面 + pointer 事件拖进画布）。
 * 从 ChatMessageItem 拆出以保持主组件精简（架构铁律 10.1：单文件 ≤ 250 行）。
 */
import { fetchImageAsFile } from '@/api/client';
import { dropImageToCanvas } from '@/api/canvas';
import { startCanvasImageDrag, endCanvasImageDrag, canvasImageDrag } from '@/stores/canvas';
import { showToast } from '@/stores/toast';

/** 转为绝对 URL（后端返回的 /workspace/... 相对路径在 DownloadURL 等场景必须用绝对地址） */
export function absUrl(url: string): string {
  try {
    return new URL(url, window.location.href).href;
  } catch {
    return url;
  }
}

export interface ImageDragHandlers {
  /** HTML5 dragstart：仅供拖进文件夹/桌面（DownloadURL） */
  handleImageDragStart: (e: DragEvent, imageUrl: string, fname: string) => void;
  /** pointerdown：阈值触发后拖进画布（解决滚动容器与 HTML5 drag 冲突） */
  onThumbPointerDown: (e: PointerEvent, imageUrl: string, fname: string) => void;
  /** 预取拖拽用 File（供拖进文件夹） */
  prefetchDragFile: (imageUrl: string, fname: string) => void;
  /** 本次按压是否已发生拖拽位移（用于区分点击看原图 vs 拖拽） */
  wasMoved: () => boolean;
}

export function createImageDrag(): ImageDragHandlers {
  const dragFileCache = new Map<string, File>();
  let ptrStart: { x: number; y: number } | null = null;
  let ptrDragActive = false;
  let ptrImageUrl = '';
  let ptrFname = '';
  let ptrMoved = false;

  function prefetchDragFile(imageUrl: string, fname: string) {
    if (dragFileCache.has(imageUrl)) return;
    void fetchImageAsFile(absUrl(imageUrl), fname).then((file) => {
      if (file) dragFileCache.set(imageUrl, file);
    });
  }

  function handleImageDragStart(e: DragEvent, imageUrl: string, fname: string) {
    const dt = e.dataTransfer;
    if (!dt) return;
    dt.effectAllowed = 'copy';
    const absolute = absUrl(imageUrl);
    const cached = dragFileCache.get(imageUrl);
    const mime = cached?.type || 'image/png';
    try { dt.setData('DownloadURL', `${mime}:${fname}:${absolute}`); } catch { /* 部分浏览器不支持 */ }
    if (cached) { try { dt.items.add(cached); } catch { /* 忽略 */ } }
    dt.setData('text/uri-list', absolute);
    dt.setData('text/plain', absolute);
    startCanvasImageDrag({ url: absolute, name: fname });
  }

  function onDocPointerMove(e: PointerEvent) {
    if (!ptrStart) return;
    const dx = e.clientX - ptrStart.x;
    const dy = e.clientY - ptrStart.y;
    if (!ptrDragActive && Math.sqrt(dx * dx + dy * dy) > 10) {
      // 超过阈值，激活画布拖放模式
      ptrDragActive = true;
      ptrMoved = true;
      startCanvasImageDrag({ url: absUrl(ptrImageUrl), name: ptrFname });
    }
  }

  function onDocPointerUp(e: PointerEvent) {
    document.removeEventListener('pointermove', onDocPointerMove);
    document.removeEventListener('pointerup', onDocPointerUp);
    if (ptrDragActive) {
      // 判断落点是否在画布区域（agent 面板左侧）
      const agentPanel = document.querySelector('.canvas-agent-overlay');
      const agentRect = agentPanel?.getBoundingClientRect();
      const inAgentPanel = agentRect
        && e.clientX >= agentRect.left && e.clientX <= agentRect.right
        && e.clientY >= agentRect.top && e.clientY <= agentRect.bottom;
      const canvasView = document.querySelector('.canvas-view');
      const inCanvasView = !!canvasView && !inAgentPanel;

      if (inCanvasView) {
        // 落点在画布区域，调用 API 写入
        const rect = canvasView!.getBoundingClientRect();
        const drag = canvasImageDrag();
        if (drag) {
          void dropImageToCanvas({
            url: drag.url,
            name: drag.name,
            drop: { x: e.clientX - rect.left, y: e.clientY - rect.top },
            view: { width: rect.width, height: rect.height },
          }).then((res) => {
            showToast(`已添加到画布「${res.canvas_title}」`, 'success');
          }).catch((err) => {
            showToast(`添加到画布失败：${(err as Error).message}`, 'error');
          });
        }
      }
      endCanvasImageDrag();
    }
    ptrStart = null;
    ptrDragActive = false;
  }

  function onThumbPointerDown(e: PointerEvent, imageUrl: string, fname: string) {
    if (e.button !== 0) return; // 仅左键
    ptrStart = { x: e.clientX, y: e.clientY };
    ptrDragActive = false;
    ptrMoved = false;
    ptrImageUrl = imageUrl;
    ptrFname = fname;
    prefetchDragFile(imageUrl, fname);
    document.addEventListener('pointermove', onDocPointerMove);
    document.addEventListener('pointerup', onDocPointerUp);
  }

  return {
    handleImageDragStart,
    onThumbPointerDown,
    prefetchDragFile,
    wasMoved: () => ptrMoved,
  };
}
