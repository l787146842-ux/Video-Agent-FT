/**
 * 画布 postMessage 双向通信桥接
 *
 * 【协议现状 — 2026-08 审查确认，详见 docs/对画布的需求清单.md】
 * 本项目与画布（画布）为跨源 iframe 集成，postMessage 协议大部分为【预留协议】：
 *
 * 接收方向（CanvasToStudioMessage）：
 * - canvas:ready / canvas:selection / canvas:node-select / canvas:node-update
 *   画布当前【从未发送】这些消息。监听代码保留——属预留协议，画布未来实现后零改动生效。
 *   选中态读取受 Rule 7 限制（选中仅存于画布浏览器端内存，无 API），只能等画布侧广播。
 *
 * 发送方向（StudioToCanvasMessage）：
 * - 'studio-theme'：画布 theme.js 实际监听的消息名（无 origin 校验，跨源可达）——【唯一当前生效】
 * - studio:draft-select / studio:state-sync：画布画布页不认识这两个消息名，
 *   且其 message 监听对跨源消息直接丢弃（event.origin !== location.origin 时 return），
 *   当前发送无效，保留为预留协议，待画布支持后生效。
 */
import { state, setState, findDraftRecord } from '@/stores/studio';
import { applyCanvasSelection, clearCanvasSelection } from '@/stores/canvas';

export type CanvasToStudioMessage =
  | { type: 'canvas:node-select'; nodeId: string }
  | { type: 'canvas:node-update'; nodeId: string; data: Record<string, unknown> }
  | { type: 'canvas:selection'; items: Array<{ url?: string; name?: string; kind?: string; nodeId?: string }> }
  | { type: 'canvas:ready' };

export type StudioToCanvasMessage =
  // 画布 theme.js 实际监听的消息名（当前唯一生效的发送消息）
  | { type: 'studio-theme'; theme: string }
  // 以下为预留协议：画布当前不认识且会丢弃跨源消息，待其支持后生效
  | { type: 'studio:draft-select'; draftId: string; draftType: string }
  | { type: 'studio:state-sync'; groups: unknown[] };

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

function allGroups(): unknown[] {
  return [...state.keyElements, ...state.shots, ...state.audioItems];
}

function handleCanvasMessage(event: MessageEvent): void {
  const origin = canvasOrigin();
  if (origin && event.origin !== origin) return;
  const data = event.data as CanvasToStudioMessage | undefined;
  if (!data || typeof data.type !== 'string') return;

  switch (data.type) {
    case 'canvas:ready':
      // 画布 iframe 重新加载后其内存中的选中态已丢失，清除过期选中缓存
      clearCanvasSelection();
      postToCanvas({ type: 'studio:state-sync', groups: allGroups() });
      break;
    case 'canvas:selection': {
      // 画布上报的选中图片（Rule7：只消费画布的公开 postMessage，不读其内部状态）。
      // 相对地址（/assets/...）统一补全为画布源绝对地址，并按 URL 去重。
      const origin = canvasOrigin();
      const seen = new Set<string>();
      const items = (Array.isArray(data.items) ? data.items : [])
        .map((it) => {
          let url = String(it?.url || '').trim();
          if (url && !/^(https?:|data:|blob:)/i.test(url) && origin) {
            url = `${origin}${url.startsWith('/') ? '' : '/'}${url}`;
          }
          return url ? { url, name: it?.name || 'image', kind: it?.kind, nodeId: it?.nodeId } : null;
        })
        .filter((it): it is NonNullable<typeof it> => {
          if (!it || seen.has(it.url)) return false;
          seen.add(it.url);
          return true;
        });
      applyCanvasSelection(items);
      break;
    }
    case 'canvas:node-select': {
      // 在故事板中查找关联草稿并选中
      for (const group of [...state.keyElements, ...state.shots, ...state.audioItems]) {
        const draft = group.drafts?.find(
          (d) => d.id === data.nodeId
            || (d as unknown as Record<string, unknown>).canvasNodeId === data.nodeId,
        );
        if (draft) {
          setState('selectedDraftId', draft.id);
          break;
        }
      }
      break;
    }
    case 'canvas:node-update':
      // 预留：画布节点数据更新时同步故事板
      break;
  }
}

/** 初始化桥接（CanvasView onMount 调用），返回清理函数 */
export function initCanvasBridge(iframeGetter: () => HTMLIFrameElement | undefined): () => void {
  getIframe = iframeGetter;
  window.addEventListener('message', handleCanvasMessage);
  return () => {
    window.removeEventListener('message', handleCanvasMessage);
    getIframe = () => undefined;
  };
}

/** 草稿选中时通知画布 */
export function notifyDraftSelected(draftId: string, draftType: string): void {
  postToCanvas({ type: 'studio:draft-select', draftId, draftType });
}

/** 状态变更广播（供 effect 调用） */
export function broadcastStateSync(): void {
  postToCanvas({ type: 'studio:state-sync', groups: allGroups() });
}

/** 主题变更通知（画布 theme.js 监听 'studio-theme'，无 origin 校验，跨源可达） */
export function broadcastThemeChange(theme: string): void {
  postToCanvas({ type: 'studio-theme', theme });
}

/** 供选中草稿查找复用 */
export { findDraftRecord };
