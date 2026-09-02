/**
 * 素材库「图片资产 / 本地素材」tab（自 AssetLibraryModal 拆出）：
 * 加载 / 错误 / 画布离线 / 空态 / 卡片网格。
 * DOM 结构不变（.asset-modal-status / .asset-grid 原样），
 * 数据源（items 资源）仍在父组件，行为零变化。
 */
import { Show } from 'solid-js';
import { FiImage, FiGrid, FiHardDrive, FiLoader, FiAlertCircle } from 'solid-icons/fi';
import type { Resource } from 'solid-js';
import type { AssetGridItem, AssetPickerResponse } from '@/api/providers';
import { t } from '@/lib/locale';
import { AssetLibraryGrid } from './AssetLibraryGrid';

/** 未加载时的空结果（结构上归入 AssetPickerResponse，与父侧 fetcher 返回值等价） */
type ItemsValue = AssetPickerResponse;

type Tab = 'image' | 'canvas' | 'local';

/** tab 文案走 i18n 字典，函数形式保持语言切换可扩展 */
export function TAB_LABELS(): Record<Tab, string> {
  return {
    image: t('rp.asset.tabImage'),
    canvas: t('rp.asset.tabCanvas'),
    local: t('rp.asset.tabLocal'),
  };
}

export function AssetLibraryItemsTab(props: {
  items: Resource<ItemsValue | undefined>;
  tab: () => Tab;
  onReconnect: () => void;
  selectedIds: () => Set<string>;
  toggleItem: (item: AssetGridItem) => void;
}) {
  return (
    <>
      <Show when={props.items.loading}>
        <div class="asset-modal-status">
          <FiLoader size={22} class="animate-spin" />
          <p>{t('rp.asset.loading')}</p>
        </div>
      </Show>

      <Show when={!props.items.loading && props.items.error}>
        <div class="asset-modal-status">
          <FiAlertCircle size={22} />
          <p>{t('rp.asset.loadFailed', { error: String(props.items.error) })}</p>
        </div>
      </Show>

      <Show when={!props.items.loading && props.items() && props.items()!.canvas_online === false}>
        <div class="asset-modal-status">
          <FiAlertCircle size={22} />
          <p>{t('rp.asset.offlineLimited', { error: t('rp.asset.connectionFailed') })}</p>
          <p class="asset-modal-status-hint">{t('rp.asset.checkOriginPre')}<code>{location.origin.replace(/\d+$/, '3000')}</code>{t('rp.asset.checkOriginPost')}</p>
          <button type="button" class="btn-secondary" onClick={() => props.onReconnect()}>{t('rp.asset.reconnect')}</button>
        </div>
      </Show>

      <Show when={!props.items.loading && props.items() && props.items()!.canvas_online !== false && (props.items()!.items?.length ?? 0) === 0}>
        <div class="asset-modal-status">
          <Show when={props.tab() === 'image'}><FiImage size={28} /></Show>
          <Show when={props.tab() === 'canvas'}><FiGrid size={28} /></Show>
          <Show when={props.tab() === 'local'}><FiHardDrive size={28} /></Show>
          <p>{t('rp.asset.emptyOf', { label: TAB_LABELS()[props.tab()] })}</p>
          <Show when={props.tab() === 'image'}>
            <p class="asset-modal-status-hint">{t('rp.asset.emptyImageHint')}</p>
          </Show>
          <Show when={props.tab() === 'canvas'}>
            <p class="asset-modal-status-hint">{t('rp.asset.canvasImagesHint')}</p>
          </Show>
          <Show when={props.tab() === 'local'}>
            <p class="asset-modal-status-hint">{t('rp.asset.emptyLocalHint')}</p>
          </Show>
        </div>
      </Show>

      <Show when={!props.items.loading && props.items() && props.items()!.items && props.items()!.items.length > 0}>
        <AssetLibraryGrid
          items={props.items()!.items}
          selectedIds={props.selectedIds}
          toggleItem={props.toggleItem}
        />
      </Show>
    </>
  );
}
