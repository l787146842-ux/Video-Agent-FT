/**
 * 素材库卡片网格：
 * 图片资产/画布资产/本地素材三个 tab 共用的多选卡片网格。
 */
import { For, Show } from 'solid-js';
import { FiImage } from 'solid-icons/fi';
import type { AssetGridItem } from '@/api/providers';
import { safeUrl } from '@/lib/utils';
import { t } from '@/lib/locale';

export function AssetLibraryGrid(props: {
  items: AssetGridItem[];
  selectedIds: () => Set<string>;
  toggleItem: (item: AssetGridItem) => void;
}) {
  return (
    <div class="asset-grid">
      <For each={props.items}>{(item) => {
        const thumbUrl = () => safeUrl(item.thumb || item.url);
        const isSelected = () => props.selectedIds().has(item.id);
        return (
          <div
            class="asset-card"
            classList={{ selected: isSelected() }}
            title={t('rp.asset.cardToggle', { name: item.name, action: isSelected() ? t('rp.asset.unselect') : t('rp.asset.select') })}
            onClick={() => props.toggleItem(item)}
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
  );
}
