import { createSignal } from 'solid-js';
import {
  fetchCanvasList, fetchCanvasSelection,
  type CanvasSelectionResult,
} from '@/api/canvas';
import type { InfiniteCanvasEmbedConfig } from '@/api/providers';
import { state } from '@/stores/studio';

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

/** 画布站点地址（离线提示文案用）：取嵌入配置，未就绪时兜底默认站点 */
export function canvasSiteUrl(): string {
  return canvasEmbed()?.canvas_url || state.canvasUrl || 'http://127.0.0.1:3000';
}

/**
 * 画布 iframe 引导地址：{画布站点}/#agentUrl={canvas-agent}&agentToken={token}，
 * 参数来自后端 /api/config 下发（对端 readAgentUrlBootstrap 解析 hash）；
 * 嵌入配置未就绪时兜底默认站点直嵌。
 */
export const [canvasEmbed, setCanvasEmbed] = createSignal<InfiniteCanvasEmbedConfig | undefined>(undefined);
export function canvasIframeSrc(): string {
  const emb = canvasEmbed();
  if (emb?.canvas_url) {
    const base = emb.canvas_url.replace(/\/$/, '');
    return `${base}/#agentUrl=${encodeURIComponent(emb.agent_url)}&agentToken=${encodeURIComponent(emb.agent_token)}`;
  }
  return state.canvasUrl || 'http://127.0.0.1:3000';
}

/**
 * 探测画布服务是否在线。
 * 走本项目后端 GET /api/canvas/list（其返回 canvas_online 标志），
 * 不依赖 postMessage 握手（画布当前不发送任何消息，Rule 7 不可改）。
 * 离线或请求失败时置 canvasError=true，驱动 CanvasView 的错误覆盖层。
 * 传入 graceRetryMs 时，首次探测离线先宽限等待再重探一次：
 * 画布编辑器客户端尚未接入 canvas-agent 时后端健康探针会短暂误报离线。
 */
export async function probeCanvasOnline(graceRetryMs = 0): Promise<boolean> {
  const probeOnce = async (): Promise<boolean> => {
    try {
      const res = await fetchCanvasList();
      return res.canvas_online !== false;
    } catch {
      return false;
    }
  };
  let online = await probeOnce();
  if (!online && graceRetryMs > 0) {
    await new Promise((r) => setTimeout(r, graceRetryMs));
    online = await probeOnce();
  }
  setCanvasError(!online);
  return online;
}

/** 覆盖层拖拽中标志（拖拽时禁用 iframe pointer-events 防止吐掉 mousemove） */
export const [canvasOverlayDragging, setCanvasOverlayDragging] = createSignal(false);

// ---------- 选中态轮询（@ 菜单激活期间订阅 /api/canvas/selection） ----------

// Q16 裁决 2026-09-01：按需轮询已是现状（仅 @ 面板激活期间启停、离线自停），
// 频率由 1500ms 降至 500ms——激活窗口短暂，高频换选中态变化的即时响应。
const SELECTION_POLL_MS = 500;
const EMPTY_SELECTION: CanvasSelectionResult = { supported: false, nodes: [], canvas_online: false };

export const [canvasSelection, setCanvasSelection] = createSignal<CanvasSelectionResult>(EMPTY_SELECTION);
let selectionTimer: ReturnType<typeof setInterval> | undefined;

async function pollOnceSelection(): Promise<boolean> {
  try {
    const res = await fetchCanvasSelection();
    setCanvasSelection(res);
    // 画布离线或后端不支持 → 停轮询，避免空转请求
    return res.canvas_online !== false && res.supported === true;
  } catch {
    setCanvasSelection(EMPTY_SELECTION);
    return false;
  }
}

/** 启动选中态轮询（幂等）；首次探测即离线/不支持则不进入定时器 */
export function startCanvasSelectionPolling() {
  if (selectionTimer !== undefined) return;
  void pollOnceSelection().then((keep) => {
    if (!keep || selectionTimer !== undefined) return;
    selectionTimer = setInterval(() => {
      void pollOnceSelection().then((ok) => { if (!ok) stopCanvasSelectionPolling(); });
    }, SELECTION_POLL_MS);
  });
}

export function stopCanvasSelectionPolling() {
  if (selectionTimer !== undefined) {
    clearInterval(selectionTimer);
    selectionTimer = undefined;
  }
}

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
