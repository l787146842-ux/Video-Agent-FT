import { Show, For, createSignal, createResource, createMemo, createEffect } from 'solid-js';
import { FiX, FiExternalLink } from 'solid-icons/fi';
import { useNavigate } from '@solidjs/router';
import { fetchAssetPicker, type AssetPickerItem, type AssetGridItem } from '@/api/providers';
import { fetchCanvasList, fetchAllCanvasNodeImages } from '@/api/canvas';
import { t } from '@/lib/locale';
import { useFocusTrap } from '@/lib/focus-trap';
import { AssetLibraryCanvasTab } from './AssetLibraryCanvasTab';
import { AssetLibraryItemsTab, TAB_LABELS } from './AssetLibraryItemsTab';

type Tab = 'image' | 'canvas' | 'local';

/**
 * "打开画布素材库"模态框（对齐旧版 asset-modal 三 tab）：
 * - 图片资产：画布 asset library 里的图片库
 * - 画布资产：当前画布上已经生成的素材
 * - 本地素材：用户本地 /workspace/assets/ 上传的素材
 *
 * 交互对齐旧版 _renderAssetGrid + _toggleAssetCard + confirmAssetSelection：
 * - 点击卡片 → 切换选中态（带视觉反馈 .selected + ✓ 角标）
 * - 底部"已选 N 个" + "添加到对话框"按钮 → 批量回调 onPick(items) 后关闭
 *
 * tab 主体拆为 AssetLibraryCanvasTab / AssetLibraryItemsTab（控制本文件行数），
 * 共用卡片网格 AssetLibraryGrid；本文件保留数据源与选中态，DOM 结构不变。
 */
export function AssetLibraryModal(props: {
  open: boolean;
  onClose: () => void;
  /** 批量回调：用户点击"添加到对话框"时触发，已勾选的素材数组（网格消费面最小视图态） */
  onPick?: (items: AssetGridItem[]) => void;
}) {
  const navigate = useNavigate();
  const [tab, setTab] = createSignal<Tab>('image');
  /** 多选状态：用 item.id 而非下标，避免分页/筛选时下标漂移 */
  const [selectedIds, setSelectedIds] = createSignal<Set<string>>(new Set());
  /** 画布资产 tab：目标画布空间 */
  const [selectedCanvasId, setSelectedCanvasId] = createSignal('');

  // 焦点圈闭：打开圈闭、Esc 关闭、关闭还原焦点
  const [panelEl, setPanelEl] = createSignal<HTMLElement>();
  useFocusTrap(() => (props.open ? panelEl() : undefined), { onEscape: () => props.onClose() });

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

  /** 当前 tab 的素材列表（画布 tab 取选中画布的图片，其余取 asset-picker 接口；
   * 两数据源归一为网格消费面 AssetGridItem） */
  const currentItems = createMemo<AssetGridItem[]>(() =>
    tab() === 'canvas' ? (canvasImages()?.items || []) : (items()?.items || [])
  );

  /** 已选素材对象数组（按当前列表顺序，驱动 onPick 回调） */
  const selectedItems = createMemo(() => {
    const list = currentItems();
    const sel = selectedIds();
    return list.filter((it) => sel.has(it.id));
  });

  function toggleItem(item: AssetGridItem) {
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

  /** 切换画布空间并清空选中（避免跨画布残留 id；下拉关闭在 tab 组件内） */
  function selectCanvas(id: string) {
    setSelectedCanvasId(id);
    setSelectedIds(new Set<string>());
  }

  return (
    <Show when={props.open}>
      <div class="asset-modal">
        <div class="asset-modal-backdrop" onClick={() => props.onClose()} />
        <div
          class="asset-modal-panel"
          ref={setPanelEl}
          role="dialog"
          aria-modal="true"
          aria-label={t('rp.asset.libraryAria')}
        >
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
            <button class="asset-modal-close" onClick={() => props.onClose()} title={t('rp.asset.close')}>
              <FiX size={16} />
            </button>
          </div>

          {/* 主体：素材网格 / 加载 / 错误 / 空 */}
          <div class="asset-modal-body">
            <Show when={tab() === 'canvas'}>
              <AssetLibraryCanvasTab
                canvasList={canvasList}
                canvasImages={canvasImages}
                selectedCanvasId={selectedCanvasId}
                selectCanvas={selectCanvas}
                onReconnect={() => { void refetchCanvasList(); void refetchItems(); }}
                selectedIds={selectedIds}
                toggleItem={toggleItem}
              />
            </Show>

            <Show when={tab() !== 'canvas'}>
              <AssetLibraryItemsTab
                items={items}
                tab={tab}
                onReconnect={() => void refetchItems()}
                selectedIds={selectedIds}
                toggleItem={toggleItem}
              />
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
