import { createSignal } from 'solid-js';
import { fetchCanvasList } from '@/api/canvas';

/**
 * 画布 iframe 共享状态
 * iframe 常驻于 LayoutShell（不随路由卸载），CanvasView 仅渲染覆盖层。
 * 此模块桥接两者之间的通信。
 */

/** 画布 iframe 元素引用（LayoutShell 设置） */
let iframeEl: HTMLIFrameElement | undefined;
export function setCanvasIframe(el: HTMLIFrameElement | undefined) {
  iframeEl = el;
}
export function getCanvasIframe() {
  return iframeEl;
}

/** 画布加载失败标志 */
export const [canvasError, setCanvasError] = createSignal(false);

/**
 * 探测画布服务是否在线。
 * 走本项目后端 GET /api/canvas/list（其返回 canvas_online 标志），
 * 不依赖 postMessage 握手（画布当前不发送任何消息，Rule 7 不可改）。
 * 离线或请求失败时置 canvasError=true，驱动 CanvasView 的错误覆盖层。
 */
export async function probeCanvasOnline(): Promise<boolean> {
  try {
    const res = await fetchCanvasList();
    const online = res.canvas_online !== false;
    setCanvasError(!online);
    return online;
  } catch {
    setCanvasError(true);
    return false;
  }
}

/** 覆盖层拖拽中标志（拖拽时禁用 iframe pointer-events 防止吐掉 mousemove） */
export const [canvasOverlayDragging, setCanvasOverlayDragging] = createSignal(false);

/** 对话栏图片拖入画布：拖拽中的图片信息。
 * 浏览器原生拖拽无法投递进跨域 iframe（实证结论），
 * 故拖拽期间由 CanvasView 显示自有放置层，落点经 HTTP API 写入画布节点。 */
export interface CanvasImageDragInfo {
  /** 图片绝对 URL（本站 /workspace/... 已转为绝对地址） */
  url: string;
  /** 文件名 */
  name: string;
}
export const [canvasImageDrag, setCanvasImageDrag] = createSignal<CanvasImageDragInfo | null>(null);
export function startCanvasImageDrag(info: CanvasImageDragInfo) {
  setCanvasImageDrag(info);
}
export function endCanvasImageDrag() {
  setCanvasImageDrag(null);
}
