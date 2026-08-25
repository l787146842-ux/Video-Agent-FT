/**
 * 导出下拉按钮：导出到文件夹（浏览器下载）/ 导出到画布（手动画布选择器）
 * ——自 ParamBase 切出（任务 #15 白名单清偿），行为零变更。
 */
import { For, createSignal, createEffect, createResource, onCleanup } from 'solid-js';
import { FiDownload, FiGrid, FiChevronUp, FiChevronRight } from 'solid-icons/fi';
import { findDraftRecord, state } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { dropImageToCanvas, fetchCanvasList, type CanvasListItem } from '@/api/canvas';
import { fetchMediaBlob } from '@/api/client';
import { safeUrl } from '@/lib/utils';
import { btnSecondary } from './ParamBase';

export function ExportButton() {
  const [open, setOpen] = createSignal(false);
  const [canvasSubOpen, setCanvasSubOpen] = createSignal(false);
  let wrapRef: HTMLDivElement | undefined;

  // 加载画布列表（仅在展开子菜单时加载）
  const [canvasListData] = createResource(
    canvasSubOpen,
    async (active) => active ? await fetchCanvasList() : null,
  );

  function close() { setOpen(false); setCanvasSubOpen(false); }

  function onDocClick(e: MouseEvent) {
    if (wrapRef && !wrapRef.contains(e.target as Node)) close();
  }

  function toggle() {
    setOpen((v) => !v);
    setCanvasSubOpen(false);
  }

  createEffect(() => {
    if (open()) {
      document.addEventListener('mousedown', onDocClick);
      onCleanup(() => document.removeEventListener('mousedown', onDocClick));
    }
  });

  function currentMediaUrl(): string {
    const rec = findDraftRecord(state.selectedDraftId, state.selectedType);
    if (!rec) return '';
    const d = rec.draft;
    if (d.mediaType === 'video') return d.videoUrl || '';
    if (d.mediaType === 'audio') return d.audioUrl || '';
    return d.imgUrl || '';
  }

  /** 导出到文件夹：下载原始格式图片（跨域走后端代理） */
  async function exportToFolder() {
    close();
    const url = currentMediaUrl();
    if (!url) {
      showToast('当前草稿没有可导出的媒体', 'warning');
      return;
    }
    const rec = findDraftRecord(state.selectedDraftId, state.selectedType);
    const fileName = rec?.draft.label || 'image.png';
    try {
      // 跨域代理逻辑已收口 api 层（铁律 10.1）
      const blob = await fetchMediaBlob(safeUrl(url));
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objUrl;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(objUrl), 5000);
      showToast('已开始下载', 'success');
    } catch (err) {
      showToast(`导出失败：${(err as Error).message}`, 'error');
    }
  }

  /** 导出到指定画布 */
  async function exportToCanvas(cv: CanvasListItem) {
    close();
    const url = currentMediaUrl();
    if (!url) {
      showToast('当前草稿没有可导出的媒体', 'warning');
      return;
    }
    const rec = findDraftRecord(state.selectedDraftId, state.selectedType);
    const name = rec?.draft.label || 'image.png';
    try {
      const res = await dropImageToCanvas({ url, name, canvas_id: cv.id });
      showToast(`已添加到画布「${res.canvas_title}」`, 'success');
    } catch (err) {
      showToast(`导出到画布失败：${(err as Error).message}`, 'error');
    }
  }

  function kindLabel(kind: string) {
    return kind === 'smart' ? '智能' : '普通';
  }

  return (
    <div class="export-dropdown" ref={wrapRef}>
      <button type="button" class={btnSecondary} onClick={toggle}>
        导出 <FiChevronUp size={11} class={`export-chevron ${open() ? 'open' : ''}`} />
      </button>
      {open() && (
        <div class="export-menu">
          <button type="button" class="export-menu-item" onClick={() => void exportToFolder()}>
            <FiDownload size={13} />
            <span>导出到文件夹</span>
          </button>
          <button
            type="button"
            class="export-menu-item"
            onClick={() => setCanvasSubOpen((v) => !v)}
          >
            <FiGrid size={13} />
            <span>导出到画布</span>
            <FiChevronRight size={11} style={{ 'margin-left': 'auto' }} />
          </button>
          {/* 画布选择子菜单 */}
          {canvasSubOpen() && (
            <div class="export-canvas-sub">
              {canvasListData.loading && <div class="export-canvas-loading">加载中...</div>}
              {!canvasListData.loading && canvasListData()?.canvas_online === false && (
                <div class="export-canvas-loading">画布未连接</div>
              )}
              {!canvasListData.loading && (canvasListData()?.canvases || []).length === 0 && canvasListData()?.canvas_online !== false && (
                <div class="export-canvas-loading">暂无画布</div>
              )}
              <For each={canvasListData()?.canvases || []}>
                {(cv) => (
                  <button
                    type="button"
                    class="export-canvas-item"
                    onClick={() => void exportToCanvas(cv)}
                  >
                    <span class="export-canvas-kind">{kindLabel(cv.kind)}</span>
                    <span class="export-canvas-name">{cv.title}</span>
                  </button>
                )}
              </For>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
