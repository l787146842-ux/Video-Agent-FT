import { Show, For, createSignal, createMemo } from 'solid-js';
import { FiX, FiImage, FiMusic, FiExternalLink } from 'solid-icons/fi';
import { state } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { requestInsertMedia } from '@/lib/chat-input-bridge';
import { safeUrl, uid } from '@/lib/utils';
import { t } from '@/lib/locale';
import type { AnyGroup, MediaType } from '@/types';

/** 弹窗内的统一媒体项（故事板草稿 / 未归类素材共用） */
interface PickerItem {
  id: string;
  name: string;
  kind: MediaType;
  url: string;
  thumb?: string;
}

type Tab = 'keyElement' | 'shot' | 'audio' | 'uncat';

/** tab 文案走 i18n 字典（P2-4） */
function TAB_LABELS(): Record<Tab, string> {
  return {
    keyElement: t('rp.picker.tabKeyElement'),
    shot: t('rp.picker.tabShot'),
    audio: t('rp.picker.tabAudio'),
    uncat: t('rp.picker.tabUncat'),
  };
}

/** 故事板某分区的媒体项（仅取已有媒体文件的草稿） */
function boardItems(field: 'keyElements' | 'shots' | 'audioItems'): PickerItem[] {
  const items: PickerItem[] = [];
  for (const g of state[field] as AnyGroup[]) {
    for (const d of g.drafts || []) {
      const kind = d.mediaType || 'image';
      const url = kind === 'image' ? d.imgUrl : kind === 'video' ? d.videoUrl : d.audioUrl;
      if (!url) continue;
      items.push({
        id: d.id,
        name: d.label || d.id,
        kind,
        url,
        thumb: kind === 'video' && d.imgUrl ? d.imgUrl : undefined,
      });
    }
  }
  return items;
}

/** 未归类素材的媒体项 */
function uncatItems(): PickerItem[] {
  return state.assets
    .filter((a) => a.url)
    .map((a) => ({ id: a.id, name: a.name, kind: a.type, url: a.url }));
}

/**
 * 「素材库」选择弹窗（界面参照"打开画布素材库"模态框）：
 * - Tab：关键元素 / 分镜 / 音频（故事板素材）+ 未归类素材
 * - 点击卡片多选（.selected 视觉反馈），底部"已选 N 个" + "添加到对话框"
 *   批量插入聊天输入框（内联媒体缩略块）。
 */
export function StudioAssetPickerModal(props: {
  open: boolean;
  onClose: () => void;
  /** 打开画布素材库（原有入口保留，位于头部右侧） */
  onOpenCanvas: () => void;
}) {
  const [tab, setTab] = createSignal<Tab>('keyElement');
  /** 多选状态：用 item.id 而非下标，避免切换 tab 时下标漂移 */
  const [selectedIds, setSelectedIds] = createSignal<Set<string>>(new Set());

  const items = createMemo<PickerItem[]>(() => {
    const t = tab();
    if (t === 'uncat') return uncatItems();
    return boardItems(t === 'shot' ? 'shots' : t === 'audio' ? 'audioItems' : 'keyElements');
  });

  const selectedItems = createMemo(() => {
    const sel = selectedIds();
    return items().filter((it) => sel.has(it.id));
  });

  function toggleItem(item: PickerItem) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(item.id)) next.delete(item.id);
      else next.add(item.id);
      return next;
    });
  }

  function switchTab(next: Tab) {
    setTab(next);
    setSelectedIds(new Set<string>());
  }

  function confirmPick() {
    const picked = selectedItems();
    if (!picked.length) return;
    for (const it of picked) {
      requestInsertMedia({ id: uid('im'), kind: it.kind, url: it.url, name: it.name, thumb: it.thumb });
    }
    showToast(t('rp.picker.addedToChat', { count: picked.length }), 'success');
    setSelectedIds(new Set<string>());
    props.onClose();
  }

  return (
    <Show when={props.open}>
      <div class="asset-modal">
        <div class="asset-modal-backdrop" onClick={() => props.onClose()} />
        <div class="asset-modal-panel">
          {/* 头部：tab + 画布素材库入口 + 关闭 */}
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
            <button
              class="asset-modal-action"
              title={t('rp.picker.openCanvasLibrary')}
              onClick={() => { props.onClose(); props.onOpenCanvas(); }}
            >
              <FiExternalLink size={13} /> {t('rp.picker.canvasAssets')}
            </button>
            <button class="asset-modal-close" onClick={() => props.onClose()} title={t('rp.asset.close')}>
              <FiX size={16} />
            </button>
          </div>

          {/* 主体：素材网格 / 空态 */}
          <div class="asset-modal-body">
            <Show when={items().length > 0} fallback={
              <div class="asset-modal-status">
                <Show when={tab() === 'uncat'} fallback={<FiImage size={28} />}>
                  <FiImage size={28} />
                </Show>
                <p>{t('rp.picker.emptyOf', { label: TAB_LABELS()[tab()] })}</p>
                <p class="asset-modal-status-hint">
                  {tab() === 'uncat' ? t('rp.picker.uncatHint') : t('rp.picker.boardHint')}
                </p>
              </div>
            }>
              <div class="asset-grid">
                <For each={items()}>{(item) => {
                  const thumbUrl = () => safeUrl(item.thumb || (item.kind === 'image' ? item.url : ''));
                  const isSelected = () => selectedIds().has(item.id);
                  return (
                    <div
                      class="asset-card"
                      classList={{ selected: isSelected() }}
                      title={t('rp.asset.cardToggle', { name: item.name, action: isSelected() ? t('rp.asset.unselect') : t('rp.asset.select') })}
                      onClick={() => toggleItem(item)}
                    >
                      {/* 音频：图标占位；视频无海报：首帧；其余：缩略图 */}
                      <Show when={item.kind === 'audio'}>
                        <div class="asset-card-placeholder"><FiMusic size={28} /></div>
                      </Show>
                      <Show when={item.kind === 'video' && !thumbUrl()}>
                        <video src={`${safeUrl(item.url)}#t=0.1`} muted playsinline preload="metadata" />
                      </Show>
                      <Show when={item.kind !== 'audio' && thumbUrl()}>
                        <img src={thumbUrl()} alt={item.name} loading="lazy" />
                      </Show>
                      <div class="asset-card-name">{item.name}</div>
                    </div>
                  );
                }}</For>
              </div>
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
