import { createSignal } from 'solid-js';
import {
  fetchCanvasList, fetchCanvasSelection,
  type CanvasSelectionResult,
} from '@/api/canvas';
import type { InfiniteCanvasEmbedConfig } from '@/api/providers';

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
 * 画布子应用同域挂载路径。
 * L1 起画布由本项目 FastAPI 直出（vendors/infinite-canvas 构建产物），
 * iframe 与外层同源，跨域墙消失；外部站点不再参与嵌入。
 */
const CANVAS_APP_PATH = '/canvas-app';

/** 画布站点地址（提示文案用）：同域挂载的绝对地址 */
export function canvasSiteUrl(): string {
  return `${window.location.origin}${CANVAS_APP_PATH}`;
}

/**
 * 画布 iframe 引导地址：/canvas-app/#agentUrl={canvas-agent}&agentToken={token}，
 * 参数来自后端 /api/config 下发（对端 readAgentUrlBootstrap 解析 hash）。
 */
export const [canvasEmbed, setCanvasEmbed] = createSignal<InfiniteCanvasEmbedConfig | undefined>(undefined);
export function canvasIframeSrc(): string {
  const emb = canvasEmbed();
  if (emb?.agent_url) {
    return `${CANVAS_APP_PATH}/#agentUrl=${encodeURIComponent(emb.agent_url)}&agentToken=${encodeURIComponent(emb.agent_token)}`;
  }
  return `${CANVAS_APP_PATH}/`;
}

/**
 * 单次画布可达探测。
 * 走本项目后端 GET /api/canvas/list，不依赖 postMessage 握手（画布不发消息，Rule 7）。
 * 口径：只认 canvas_reachable（画布站点可达即可嵌入加载）；canvas_online 含
 * “画布页已连 canvas-agent”语义，画布页尚未接入时画布仍能正常渲染，
 * 不得据此报“画布加载失败”（老后端无该字段时回落到旧口径）。
 */
async function probeCanvasOnce(): Promise<boolean> {
  try {
    const res = await fetchCanvasList();
    if (typeof res.canvas_reachable === 'boolean') return res.canvas_reachable;
    return res.canvas_online !== false;
  } catch {
    return false;
  }
}

/** 轮询节奏：1s 一轮、最多 12 轮（覆盖画布站点冷启动/重连窗口） */
const PROBE_INTERVAL_MS = 1000;
const PROBE_MAX_ATTEMPTS = 12;
let probeSeq = 0;

/**
 * 画布加载探测（进入画布/手动重试时调用）：失败不再一次定终局。
 * 每轮探一次，期间任一轮可达即自动收起覆盖层；连续两轮（约 1s）不可达才点亮，
 * 避免画布站点冷启动窗口内闪报错误。
 */
export async function probeCanvasOnline(): Promise<boolean> {
  const seq = ++probeSeq;
  let errorShown = false;
  for (let attempt = 0; attempt < PROBE_MAX_ATTEMPTS; attempt += 1) {
    const online = await probeCanvasOnce();
    if (seq !== probeSeq) return false; // 已被新一轮探测（或卸载）取代
    if (online) {
      setCanvasError(false);
      return true;
    }
    if (attempt >= 1 && !errorShown) {
      errorShown = true;
      setCanvasError(true);
    }
    if (attempt < PROBE_MAX_ATTEMPTS - 1) {
      await new Promise((r) => setTimeout(r, PROBE_INTERVAL_MS));
      if (seq !== probeSeq) return false;
    }
  }
  return false;
}

/** 停止在途探测（路由卸载时调用，防旧轮次回写覆盖层） */
export function stopCanvasProbe() {
  probeSeq += 1;
}

/** 重新加载画布 iframe：改 src 触发重新导航（不依赖读取 contentWindow） */
export function reloadCanvasIframe() {
  const el = iframeEl;
  if (!el) return;
  el.removeAttribute('src');
  requestAnimationFrame(() => { el.src = canvasIframeSrc(); });
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
