import {
  createSignal, createEffect, onMount, Show,
} from 'solid-js';
import {
  FiChevronLeft, FiChevronRight, FiImage, FiRefreshCw,
} from 'solid-icons/fi';
import { state } from '@/stores/studio';
import { useSplitter } from '@/hooks/use-splitter';
import RightPanel from '@/components/right-panel/RightPanel';
import {
  getCanvasIframe, canvasError, setCanvasError, setCanvasOverlayDragging,
  canvasImageDrag, endCanvasImageDrag, probeCanvasOnline,
} from '@/stores/canvas';
import { showToast } from '@/stores/toast';
import { dropImageToCanvas } from '@/api/canvas';

/**
 * 画布模式（路由 /canvas）
 * iframe 已持久化在 LayoutShell（不随路由卸载，保留画布状态）。
 * 本组件仅渲染：错误覆盖层 + 图片拖放层 + 右侧 Agent 面板覆盖层。
 *
 * P2-3 样式评估结论：覆盖层保持不透明悬浮（box-shadow 已具备悬浮感）——
 * 聊天长文本在半透明底上可读性明显下降，故不采用 backdrop 半透明。
 */
const KEY_OVERLAY_COLLAPSED = 'canvasAgentOverlayCollapsed';

export default function CanvasView() {
  // 收起状态记忆：从 localStorage 恢复用户上次偏好（P2-3）
  const [collapsed, setCollapsedRaw] = createSignal(
    localStorage.getItem(KEY_OVERLAY_COLLAPSED) === '1',
  );
  const setCollapsed = (v: boolean) => {
    localStorage.setItem(KEY_OVERLAY_COLLAPSED, v ? '1' : '0');
    setCollapsedRaw(v);
  };
  const [dropping, setDropping] = createSignal(false);
  const panelSplit = useSplitter(360, { min: 280, max: 700, invert: true, storageKey: 'splitCanvasPanel' });

  // 拖拽时禁用 iframe pointer-events，防止 iframe 吐掉 mousemove 事件
  createEffect(() => setCanvasOverlayDragging(panelSplit.dragging()));

  // 进入画布视图时探测画布服务在线状态（离线则显示错误覆盖层，而非永久空白 iframe）
  onMount(() => { void probeCanvasOnline(); });

  /**
   * 对话栏图片拖进画布：原生拖拽事件无法投递进跨域 iframe（实证），
   * 故用本站放置层捕获落点，再经后端走熊布公开 HTTP API 写入图片节点。
   */
  async function handleDropImage(e: DragEvent) {
    e.preventDefault();
    const drag = canvasImageDrag();
    if (!drag || dropping()) return;
    setDropping(true);
    try {
      const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
      const res = await dropImageToCanvas({
        url: drag.url,
        name: drag.name,
        drop: { x: e.clientX - rect.left, y: e.clientY - rect.top },
        view: { width: rect.width, height: rect.height },
      });
      showToast(`已添加到画布「${res.canvas_title}」`, 'success');
    } catch (err) {
      showToast(`添加到画布失败：${(err as Error).message}`, 'error');
    } finally {
      setDropping(false);
      endCanvasImageDrag();
    }
  }

  function retryLoad() {
    setCanvasError(false);
    try {
      getCanvasIframe()?.contentWindow?.location.reload();
    } catch { /* 忽略跨域异常 */ }
    // 重新探测：服务仍离线时覆盖层立即回来，避免空白等待
    void probeCanvasOnline();
  }

  function dismissError() {
    setCanvasError(false);
  }

  return (
    <div class="canvas-view">
      {/* 对话栏图片拖放层（拖拽图片时显示，松手经 HTTP API 写入画布） */}
      <Show when={canvasImageDrag()}>
        <div
          class="canvas-drop-overlay"
          onDragOver={(e) => {
            e.preventDefault();
            if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
          }}
          onDrop={(e) => void handleDropImage(e)}
        >
          <div class="canvas-drop-hint">
            <FiImage size={22} />
            <span>{dropping() ? '正在添加到画布…' : '松开鼠标，将图片添加到画布'}</span>
          </div>
        </div>
      </Show>

      {/* 加载失败覆盖层 */}
      <Show when={canvasError()}>
        <div class="canvas-fallback">
          <FiImage size={48} />
          <p>画布加载失败</p>
          <p class="canvas-fallback-hint">
            检查熊布画布是否在 <code>{state.canvasUrl}</code> 启动，
            且 X-Frame-Options 允许被嵌入
          </p>
          <div class="canvas-fallback-actions">
            <button type="button" class="btn-primary" onClick={retryLoad}>
              <FiRefreshCw size={13} /> 重试
            </button>
            <button type="button" class="btn-secondary" onClick={dismissError}>
              继续等待
            </button>
          </div>
        </div>
      </Show>

      {/* 右侧 Agent 覆盖层 */}
      <aside
        class="canvas-agent-overlay"
        classList={{ collapsed: collapsed() }}
        style={{ width: `${panelSplit.size()}px` }}
      >
        <button
          type="button"
          class="agent-toggle-btn"
          title="收缩/展开 Agent"
          onClick={() => setCollapsed(!collapsed())}
        >
          {collapsed() ? <FiChevronLeft size={14} /> : <FiChevronRight size={14} />}
        </button>

        <Show when={!collapsed()}>
          <div
            class="canvas-agent-drag"
            onMouseDown={(e) => panelSplit.onMouseDown(e)}
          />
          <div class="h-full w-full overflow-hidden">
            <RightPanel />
          </div>
        </Show>
      </aside>
    </div>
  );
}
