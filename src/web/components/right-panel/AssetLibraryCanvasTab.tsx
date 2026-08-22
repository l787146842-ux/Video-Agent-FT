/**
 * 素材库「画布资产」tab：
 * 画布空间选择器 + 加载/离线/空状态 + 所选画布的图片网格。
 * 数据源（canvasList/canvasImages 资源）由父组件提供。
 */
import { Show, For, createSignal } from 'solid-js';
import { FiGrid, FiLoader, FiAlertCircle, FiChevronDown } from 'solid-icons/fi';
import type { Resource } from 'solid-js';
import type { CanvasListItem, CanvasListResult, AllCanvasImagesResult } from '@/api/canvas';
import type { AssetPickerItem } from '@/api/providers';
import { t } from '@/lib/locale';
import { AssetLibraryGrid } from './AssetLibraryGrid';

export function AssetLibraryCanvasTab(props: {
  canvasList: Resource<CanvasListResult | undefined>;
  canvasImages: Resource<AllCanvasImagesResult | undefined>;
  selectedCanvasId: () => string;
  /** 切换画布空间（父侧负责换 id 与清选中；下拉关闭在本组件） */
  selectCanvas: (id: string) => void;
  onReconnect: () => void;
  selectedIds: () => Set<string>;
  toggleItem: (item: AssetPickerItem) => void;
}) {
  /** 画布空间选择器下拉开关（纯本 tab 视图态） */
  const [canvasDropdownOpen, setCanvasDropdownOpen] = createSignal(false);

  const currentCanvas = () =>
    (props.canvasList()?.canvases || []).find((c) => c.id === props.selectedCanvasId());

  function canvasKindLabel(kind: string) {
    return kind === 'smart' ? t('rp.asset.kindSmart') : t('rp.asset.kindNormal');
  }

  return (
    <>
      {/* 画布操作空间选择器（对齐预览框"导入画布内的图片"弹窗） */}
      <div class="canvas-picker-subheader">
        <div class="canvas-picker-title">
          <FiGrid size={14} />
          <span>{t('rp.asset.canvasSpace')}</span>
        </div>
        <div class="canvas-selector">
          <button
            class="canvas-selector-btn"
            onClick={() => setCanvasDropdownOpen((v) => !v)}
          >
            <Show when={currentCanvas()} fallback={<span>{t('rp.asset.selectCanvas')}</span>}>
              <span class="canvas-selector-kind">{canvasKindLabel(currentCanvas()!.kind)}</span>
              <span class="canvas-selector-name">{currentCanvas()!.title}</span>
            </Show>
            <FiChevronDown size={12} />
          </button>
          <Show when={canvasDropdownOpen()}>
            <div class="canvas-selector-dropdown">
              <Show when={(props.canvasList()?.canvases || []).length === 0}>
                <div class="canvas-selector-empty">{t('rp.asset.noCanvas')}</div>
              </Show>
              <For each={props.canvasList()?.canvases || []}>
                {(cv: CanvasListItem) => (
                  <button
                    class="canvas-selector-item"
                    classList={{ active: cv.id === props.selectedCanvasId() }}
                    onClick={() => { setCanvasDropdownOpen(false); props.selectCanvas(cv.id); }}
                  >
                    <span class="canvas-selector-item-kind">{canvasKindLabel(cv.kind)}</span>
                    <span class="canvas-selector-item-name">{cv.title}</span>
                  </button>
                )}
              </For>
            </div>
          </Show>
        </div>
      </div>

      <Show when={props.canvasList.loading || props.canvasImages.loading}>
        <div class="asset-modal-status">
          <FiLoader size={22} class="animate-spin" />
          <p>{t('rp.asset.loading')}</p>
        </div>
      </Show>

      <Show when={!props.canvasList.loading && props.canvasList()?.canvas_online === false}>
        <div class="asset-modal-status">
          <FiAlertCircle size={22} />
          <p>{t('rp.asset.canvasOffline')}</p>
          <p class="asset-modal-status-hint">{t('rp.asset.canvasOfflineHint')}</p>
          <button type="button" class="btn-secondary" onClick={props.onReconnect}>{t('rp.asset.reconnect')}</button>
        </div>
      </Show>

      <Show when={!props.canvasList.loading && props.canvasList()?.canvas_online !== false && (props.canvasList()?.canvases || []).length === 0}>
        <div class="asset-modal-status">
          <FiGrid size={28} />
          <p>{t('rp.asset.noCanvas')}</p>
          <p class="asset-modal-status-hint">{t('rp.asset.noCanvasHint')}</p>
        </div>
      </Show>

      <Show when={!props.canvasImages.loading && props.canvasImages() && props.canvasImages()!.canvas_online !== false && (props.canvasImages()!.items?.length ?? 0) === 0 && props.selectedCanvasId()}>
        <div class="asset-modal-status">
          <FiGrid size={28} />
          <p>{t('rp.asset.noCanvasImages')}</p>
          <p class="asset-modal-status-hint">{t('rp.asset.canvasImagesHint')}</p>
        </div>
      </Show>

      <Show when={!props.canvasImages.loading && props.canvasImages() && props.canvasImages()!.items && props.canvasImages()!.items.length > 0}>
        <AssetLibraryGrid
          items={props.canvasImages()!.items}
          selectedIds={props.selectedIds}
          toggleItem={props.toggleItem}
        />
      </Show>
    </>
  );
}
