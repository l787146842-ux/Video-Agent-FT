/**
 * 画布 postMessage 通信桥接 — 当前仅主题同步一项生效。
 *
 * 现状说明（与画布为跨源 iframe 集成，详见 docs/对画布的需求清单.md）：
 * - 发送侧：画布 theme.js 监听 'studio-theme' 消息名且不做 origin 校验，
 *   跨源可达，故主题同步是唯一实际生效的 postMessage 通道。
 * - 接收侧：画布当前从不向父窗口发送任何 postMessage（选中态只存在于
 *   画布浏览器端内存，无 API 可读，受 Rule 7 约束本项目不能改画布）。
 * - 实际的画布交互走「哑 iframe + 后端 HTTP API」（素材读写、在线探测），
 *   不存在选中跟随/节点级联动；UI 已在画布视图明示该现状。
 *
 * 曾预留的收发协议（canvas:ready / canvas:selection / studio:draft-select
 * 等）因画布侧从未实现且跨源消息会被画布丢弃，已按审查结论移除，
 * 避免代码呈现"能联动"的假象；待画布侧实现后按 docs/对画布的需求清单.md
 * 重新接入。
 */
import { state } from '@/stores/studio';

export type StudioToCanvasMessage =
  // 画布 theme.js 实际监听的消息名（当前唯一生效的发送消息）
  { type: 'studio-theme'; theme: string };

let getIframe: () => HTMLIFrameElement | undefined = () => undefined;

function canvasOrigin(): string {
  try {
    return new URL(state.canvasUrl || 'http://localhost:3000').origin;
  } catch {
    return '';
  }
}

function postToCanvas(msg: StudioToCanvasMessage): void {
  const iframe = getIframe();
  if (!iframe?.contentWindow) return;
  try {
    iframe.contentWindow.postMessage(msg, canvasOrigin() || '*');
  } catch { /* 画布未加载时静默忽略 */ }
}

/** 初始化桥接（LayoutShell 画布 iframe 就绪后调用），返回清理函数 */
export function initCanvasBridge(iframeGetter: () => HTMLIFrameElement | undefined): () => void {
  getIframe = iframeGetter;
  return () => {
    getIframe = () => undefined;
  };
}

/** 主题变更通知（画布 theme.js 监听 'studio-theme'，无 origin 校验，跨源可达） */
export function broadcastThemeChange(theme: string): void {
  postToCanvas({ type: 'studio-theme', theme });
}
