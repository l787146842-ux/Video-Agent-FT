/* eslint-disable max-lines -- 存量超行（铁律 10.1），待后续拆分；新增代码仍受规则约束 */
import { Show, For, createSignal, createResource, createMemo, createEffect } from 'solid-js';
import { FiX, FiImage, FiGrid, FiHardDrive, FiLoader, FiAlertCircle, FiExternalLink, FiChevronDown } from 'solid-icons/fi';
import { useNavigate } from '@solidjs/router';
import { fetchAssetPicker, type AssetPickerItem } from '@/api/providers';
import {
  fetchCanvasList, fetchAllCanvasNodeImages,
  type CanvasListItem,
} from '@/api/canvas';
import { safeUrl } from '@/lib/utils';
import { t } from '@/lib/locale';

type Tab = 'image' | 'canvas' | 'local';

/** tab 文案走 i18n 字典（P2-4），函数形式保持语言切换可扩展 */
function TAB_LABELS(): Record<Tab, string> {
  return {
    image: t('rp.asset.tabImage'),
    canvas: t('rp.asset.tabCanvas'),
    local: t('rp.asset.tabLocal'),
  };
}

/**
 * "打开画布素材库"模态框（对齐旧版 asset-modal 三 tab）：
 * - 图片资产：熊布 asset library 里的图片库
 * - 画布资产：当前画布上已经生成的素材
 * - 本地素材：用户本地 /workspace/assets/ 上传的素材
 *
 * 交互对齐旧版 _renderAssetGrid + _toggleAssetCard + confirmAssetSelection：
 * - 点击卡片 → 切换选中态（带视觉反馈 .selected + ✓ 角标）
 * - 底部"已选 N 个" + "添加到对话框"按钮 → 批量回调 onPick(items) 后关闭
 */
export function AssetLibraryModal(props: {
  open: boolean;
  onClose: () => void;
  /** 批量回调：用户点击"添加到对话框"时触发，已勾选的素材数组 */
  onPick?: (items: AssetPickerItem[]) => void;
}) {
  const navigate = useNavigate();
  const [tab, setTab] = createSignal<Tab>('image');
  /** 多选状态：用 item.id 而非下标，避免分页/筛选时下标漂移 */
  const [selectedIds, setSelectedIds] = createSignal<Set<string>>(new Set());
  /** 画布资产 tab：目标画布空间 + 选择器下拉开关 */
  const [selectedCanvasId, setSelectedCanvasId] = createSignal('');
  const [canvasDropdownOpen, setCanvasDropdownOpen] = createSignal(false);

  // 加载当前 tab 的素材（画布资产 tab 走独立的画布空间逻辑，不走此接口）
  const [items, { refetch: refetchItems }] = createResource(
    () => (props.open && tab() !== 'canvas' ? tab() : null),
    async (t) => {
      if (!t) return { items: [] as AssetPickerItem[], canvas_online: false };
      return await fetchAssetPicker(t);
    }
  );

  // ===== 画布资产 tab：画布空间列表 + 选中画布的图片 =====
  const [canvasList, { refetch: refetchCanvasList }] = createResource(
    () => (props.open && tab() === 'canvas' ? 'load' : null),
    async () => fetchCanvasList(),
  );

  // 默认选中第一个画布（最近更新的）
  createEffect(() => {
    const list = canvasList()?.canvases;
    if (tab() === 'canvas' && list && list.length > 0 && !selectedCanvasId()) {
      setSelectedCanvasId(list[0].id);
    }
  });

  const [canvasImages] = createResource(
    () => (props.open && tab() === 'canvas' && selectedCanvasId() ? selectedCanvasId() : null),
    async (cid) => fetchAllCanvasNodeImages(cid),
  );

  const currentCanvas = () =>
    (canvasList()?.canvases || []).find((c) => c.id === selectedCanvasId());

  /** 当前 tab 的素材列表（画布 tab 取选中画布的图片，其余取 asset-picker 接口） */
  const currentItems = createMemo<AssetPickerItem[]>(() =>
    tab() === 'canvas' ? (canvasImages()?.items || []) : (items()?.items || [])
  );

  /** 已选素材对象数组（按当前列表顺序，驱动 onPick 回调） */
  const selectedItems = createMemo(() => {
    const list = currentItems();
    const sel = selectedIds();
    return list.filter((it) => sel.has(it.id));
  });

  function toggleItem(item: AssetPickerItem) {
    setSelectedIds((prev) => {
      const next = new Set<string>(prev);
      if (next.has(item.id)) {
        next.delete(item.id);
      } else {
        next.add(item.id);
      }
      return next;
    });
  }

  function confirmPick() {
    const picked = selectedItems();
    if (picked.length === 0) return;
    props.onPick?.(picked);
    setSelectedIds(new Set<string>());
    props.onClose();
  }

  /** 切换 tab 时清空选中（避免跨 tab 残留 id） */
  function switchTab(next: Tab) {
    setTab(next);
    setSelectedIds(new Set<string>());
  }

  /** 切换画布空间：关闭下拉并清空选中（避免跨画布残留 id） */
  function selectCanvas(id: string) {
    setSelectedCanvasId(id);
    setCanvasDropdownOpen(false);
    setSelectedIds(new Set<string>());
  }

  function canvasKindLabel(kind: string) {
    return kind === 'smart' ? t('rp.asset.kindSmart') : t('rp.asset.kindNormal');
  }

  return (
    <Show when={props.open}>
      <div class="asset-modal">
        <div class="asset-modal-backdrop" onClick={props.onClose} />
        <div class="asset-modal-panel">
          {/* 头部：3 tab + 跳转画布按钮 + 关闭 */}
          <div class="asset-modal-header">
            <div class="asset-modal-tabs">
              <For each={Object.entries(TAB_LABELS()) as [Tab, string][]}>
                {([key, label]) => (
                  <button
                    classList={{ active: tab() === key }}
                    onClick={() => switchTab(key)}
                  >{label}</button>
                )}
              </For>
            </div>
            <button class="asset-modal-action" title={t('rp.asset.openCanvasTitle')} onClick={() => { props.onClose(); navigate('/canvas'); }}>
              <FiExternalLink size={13} /> {t('rp.asset.canvasJump')}
            </button>
            <button class="asset-modal-close" onClick={props.onClose} title={t('rp.asset.close')}>
              <FiX size={16} />
            </button>
          </div>

          {/* 主体：素材网格 / 加载 / 错误 / 空 */}
          <div class="asset-modal-body">
            {/* ===== 画布资产 tab：画布空间选择器 + 所选画布的图片 ===== */}
            <Show when={tab() === 'canvas'}>
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
                      <Show when={(canvasList()?.canvases || []).length === 0}>
                        <div class="canvas-selector-empty">{t('rp.asset.noCanvas')}</div>
                      </Show>
                      <For each={canvasList()?.canvases || []}>
                        {(cv: CanvasListItem) => (
                          <button
                            class="canvas-selector-item"
                            classList={{ active: cv.id === selectedCanvasId() }}
                            onClick={() => selectCanvas(cv.id)}
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

              <Show when={canvasList.loading || canvasImages.loading}>
                <div class="asset-modal-status">
                  <FiLoader size={22} class="animate-spin" />
                  <p>{t('rp.asset.loading')}</p>
                </div>
              </Show>

              <Show when={!canvasList.loading && canvasList()?.canvas_online === false}>
                <div class="asset-modal-status">
                  <FiAlertCircle size={22} />
                  <p>{t('rp.asset.canvasOffline')}</p>
                  <p class="asset-modal-status-hint">{t('rp.asset.canvasOfflineHint')}</p>
                  <button type="button" class="btn-secondary" onClick={() => { void refetchCanvasList(); void refetchItems(); }}>{t('rp.asset.reconnect')}</button>
                </div>
              </Show>

              <Show when={!canvasList.loading && canvasList()?.canvas_online !== false && (canvasList()?.canvases || []).length === 0}>
                <div class="asset-modal-status">
                  <FiGrid size={28} />
                  <p>{t('rp.asset.noCanvas')}</p>
                  <p class="asset-modal-status-hint">{t('rp.asset.noCanvasHint')}</p>
                </div>
              </Show>

              <Show when={!canvasImages.loading && canvasImages() && canvasImages()!.canvas_online !== false && (canvasImages()!.items?.length ?? 0) === 0 && selectedCanvasId()}>
                <div class="asset-modal-status">
                  <FiGrid size={28} />
                  <p>{t('rp.asset.noCanvasImages')}</p>
                  <p class="asset-modal-status-hint">{t('rp.asset.canvasImagesHint')}</p>
                </div>
              </Show>

              <Show when={!canvasImages.loading && canvasImages() && canvasImages()!.items && canvasImages()!.items.length > 0}>
                <div class="asset-grid">
                  <For each={canvasImages()!.items}>{(item) => {
                    const thumbUrl = () => safeUrl(item.thumb || item.url);
                    const isSelected = () => selectedIds().has(item.id);
                    return (
                      <div
                        class="asset-card"
                        classList={{ selected: isSelected() }}
                        title={t('rp.asset.cardToggle', { name: item.name, action: isSelected() ? t('rp.asset.unselect') : t('rp.asset.select') })}
                        onClick={() => toggleItem(item)}
                      >
                        <Show when={thumbUrl()} fallback={
                          <div class="asset-card-placeholder"><FiImage size={28} /></div>
                        }>
                          <img src={thumbUrl()} alt={item.name} loading="lazy" />
                        </Show>
                        <div class="asset-card-name">{item.name}</div>
                      </div>
                    );
                  }}</For>
                </div>
              </Show>
            </Show>

            {/* ===== 图片资产 / 本地素材 tab ===== */}
            <Show when={tab() !== 'canvas'}>
            <Show when={items.loading}>
              <div class="asset-modal-status">
                <FiLoader size={22} class="animate-spin" />
                <p>{t('rp.asset.loading')}</p>
              </div>
            </Show>

            <Show when={!items.loading && items.error}>
              <div class="asset-modal-status">
                <FiAlertCircle size={22} />
                <p>{t('rp.asset.loadFailed', { error: String(items.error) })}</p>
              </div>
            </Show>

            <Show when={!items.loading && items() && items()!.canvas_online === false}>
              <div class="asset-modal-status">
                <FiAlertCircle size={22} />
                <p>{t('rp.asset.offlineLimited', { error: items()!.error || t('rp.asset.connectionFailed') })}</p>
                <p class="asset-modal-status-hint">{t('rp.asset.checkOriginPre')}<code>{location.origin.replace(/\d+$/, '3000')}</code>{t('rp.asset.checkOriginPost')}</p>
                <button type="button" class="btn-secondary" onClick={() => void refetchItems()}>{t('rp.asset.reconnect')}</button>
              </div>
            </Show>

            <Show when={!items.loading && items() && items()!.canvas_online !== false && (items()!.items?.length ?? 0) === 0}>
              <div class="asset-modal-status">
                <Show when={tab() === 'image'}><FiImage size={28} /></Show>
                <Show when={tab() === 'canvas'}><FiGrid size={28} /></Show>
                <Show when={tab() === 'local'}><FiHardDrive size={28} /></Show>
                <p>{t('rp.asset.emptyOf', { label: TAB_LABELS()[tab()] })}</p>
                <Show when={tab() === 'image'}>
                  <p class="asset-modal-status-hint">{t('rp.asset.emptyImageHint')}</p>
                </Show>
                <Show when={tab() === 'canvas'}>
                  <p class="asset-modal-status-hint">{t('rp.asset.canvasImagesHint')}</p>
                </Show>
                <Show when={tab() === 'local'}>
                  <p class="asset-modal-status-hint">{t('rp.asset.emptyLocalHint')}</p>
                </Show>
              </div>
            </Show>

            <Show when={!items.loading && items() && items()!.items && items()!.items.length > 0}>
              <div class="asset-grid">
                <For each={items()!.items}>{(item) => {
                  const thumbUrl = () => safeUrl(item.thumb || item.url);
                  const isSelected = () => selectedIds().has(item.id);
                  return (
                    <div
                      class="asset-card"
                      classList={{ selected: isSelected() }}
                      title={t('rp.asset.cardToggle', { name: item.name, action: isSelected() ? t('rp.asset.unselect') : t('rp.asset.select') })}
                      onClick={() => toggleItem(item)}
                    >
                      <Show when={thumbUrl()} fallback={
                        <div class="asset-card-placeholder"><FiImage size={28} /></div>
                      }>
                        <img src={thumbUrl()} alt={item.name} loading="lazy" />
                      </Show>
                      <div class="asset-card-name">{item.name}</div>
                    </div>
                  );
                }}</For>
              </div>
            </Show>
            </Show>
          </div>

          {/* 底部：选中计数 + 确认添加按钮 */}
          <div class="asset-modal-footer">
            <span class="asset-selected-count">{t('rp.asset.selected', { count: selectedIds().size })}</span>
            <button
              class="btn-primary"
              disabled={selectedIds().size === 0}
              onClick={confirmPick}
            >
              {t('rp.asset.addToChat')}
            </button>
          </div>
        </div>
      </div>
    </Show>
  );
}