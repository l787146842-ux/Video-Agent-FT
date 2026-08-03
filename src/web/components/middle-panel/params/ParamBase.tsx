import { For, createSignal, createEffect, createResource, onCleanup, type ParentProps } from 'solid-js';
import { FiDownload, FiGrid, FiChevronUp, FiChevronRight } from 'solid-icons/fi';
import { findDraftRecord, persistBoard, state, studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { apiProvidersFor, providerModels } from '@/lib/providers';
import { studioImageSizeForRatio } from '@/lib/image-sizes';
import { dropImageToCanvas, fetchCanvasList, type CanvasListItem } from '@/api/canvas';
import { safeUrl } from '@/lib/utils';
import type { Draft, DraftType } from '@/types';

/** 参数变更后防抖持久化（所有参数控件 onChange 统一走这里） */
export function persistParams() {
  persistBoard();
}

/** 参数组容器（旧版 .param-group + .param-label） */
export function ParamGroup(props: ParentProps<{ label: string }>) {
  return (
    <div class="param-group">
      <span class="param-label">{props.label}</span>
      {props.children}
    </div>
  );
}

/** 通用下拉样式（旧版 .param-select） */
const selectClass = 'param-select';

/** 通用下拉 */
export function ParamSelect(props: {
  value: string;
  options: Array<{ value: string; label: string; disabled?: boolean }>;
  ariaLabel: string;
  onChange: (value: string) => void;
}) {
  return (
    <select
      class={selectClass}
      aria-label={props.ariaLabel}
      value={props.value}
      onChange={(e) => props.onChange(e.currentTarget.value)}
    >
      <For each={props.options}>
        {(opt) => <option value={opt.value} disabled={opt.disabled}>{opt.label}</option>}
      </For>
    </select>
  );
}

/** 供应商 + 模型联动下拉（切供应商时模型重置为该供应商首项） */
export function ProviderModelSelects(props: {
  kind: 'image' | 'video' | 'chat';
  providerLabel: string;
  modelLabel: string;
  draft: Draft;
}) {
  const providers = () => apiProvidersFor(props.kind);
  const models = () => providerModels(props.draft.providerId || '', props.kind);

  const draftType = (): DraftType =>
    state.selectedType === 'shot' ? 'shot' : state.selectedType === 'audio' ? 'audio' : 'keyElement';

  function changeProvider(id: string) {
    const firstModel = providerModels(id, props.kind)[0] || '';
    studioActions.updateDraftLocal(draftType(), props.draft.id, { providerId: id, model: firstModel });
  }

  function changeModel(v: string) {
    studioActions.updateDraftLocal(draftType(), props.draft.id, { model: v });
  }

  return (
    <>
      <ParamGroup label={props.providerLabel}>
        <ParamSelect
          ariaLabel={props.providerLabel}
          value={props.draft.providerId || ''}
          options={providers().map((p) => ({ value: p.id, label: p.name || p.id }))}
          onChange={changeProvider}
        />
      </ParamGroup>
      <ParamGroup label={props.modelLabel}>
        <ParamSelect
          ariaLabel={props.modelLabel}
          value={props.draft.model || ''}
          options={models().map((m) => ({ value: m, label: m }))}
          onChange={changeModel}
        />
      </ParamGroup>
    </>
  );
}

/** 次要按钮（保存）：旧版 .btn-secondary */
export const btnSecondary = 'btn-secondary';

/** 主要按钮（生成）：旧版 .btn-primary（配色变体用 btn-purple/btn-emerald 复合类） */
export const btnPrimary = 'btn-primary';

/** 保存按钮动作：校正图片尺寸 + 立即冲刷防抖保存（不等 400ms） */
export function saveDraftParams() {
  const rec = findDraftRecord(state.selectedDraftId, state.selectedType);
  if (!rec) return;
  const d = rec.draft;
  if (state.selectedType === 'keyElement') {
    d.size = studioImageSizeForRatio(
      d.aspectRatio || '1:1',
      d.customRatioWidth,
      d.customRatioHeight,
    );
  }
  persistBoard();
  persistBoard.flush();
  showToast('参数已保存到草稿卡片', 'success');
}

/** 导出下拉按钮：导出到文件夹（浏览器下载）/ 导出到画布（手动画布选择器） */
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
      const fullUrl = safeUrl(url);
      const isCrossOrigin = fullUrl.startsWith('http') && !fullUrl.startsWith(location.origin);
      const fetchUrl = isCrossOrigin
        ? `/api/image-proxy?url=${encodeURIComponent(fullUrl)}`
        : fullUrl;
      const resp = await fetch(fetchUrl);
      if (!resp.ok) throw new Error(`图片下载失败 (HTTP ${resp.status})`);
      const blob = await resp.blob();
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
