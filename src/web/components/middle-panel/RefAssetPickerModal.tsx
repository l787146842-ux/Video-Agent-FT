import { Show, For, createSignal, createResource } from 'solid-js';
import {
  FiX, FiImage, FiVideo, FiMusic, FiLoader, FiAlertCircle, FiPlus, FiChevronDown, FiLayers,
} from 'solid-icons/fi';
import {
  fetchAllCanvasNodeImages, fetchCanvasList, type CanvasListItem,
} from '@/api/canvas';
import { state } from '@/stores/studio';
import { safeUrl } from '@/lib/utils';

/** 参考素材项（统一图片/视频/音频） */
export interface RefAssetItem {
  id: string;
  name: string;
  url: string;
  type: 'image' | 'video' | 'audio';
  thumb: string;
}

/** 特殊源：故事板分区（非画布 ID） */
const KEY_ELEMENT_SOURCE = '__key_elements__';
const SHOTS_SOURCE = '__shots__';
const AUDIO_SOURCE = '__audio__';
/** 是否故事板分区源（本地状态，无需网络请求） */
const isStoryboardSource = (s: string) =>
  s === KEY_ELEMENT_SOURCE || s === SHOTS_SOURCE || s === AUDIO_SOURCE;

/**
 * 参考素材选择弹窗：源下拉（关键元素 / 分镜 / 音频 + 画布列表，分类同"画布操作空间"），
 * 网格展示对应源的素材（图片/视频/音频），点击即加入参考素材横条。
 */
export function RefAssetPickerModal(props: {
  open: boolean;
  onClose: () => void;
  onPick: (item: RefAssetItem) => void;
}) {
  const [source, setSource] = createSignal<string>(KEY_ELEMENT_SOURCE);
  const [dropdownOpen, setDropdownOpen] = createSignal(false);

  // 画布列表（用于源下拉分类）
  const [canvasList] = createResource(
    () => (props.open ? 'load' : null),
    async () => {
      try {
        return await fetchCanvasList();
      } catch {
        return { canvases: [] as CanvasListItem[], canvas_online: false };
      }
    },
  );

  // 选中画布的图片（源为画布时加载）
  const [canvasImages, { refetch: refetchCanvasImages }] = createResource(
    () => (props.open && !isStoryboardSource(source()) ? source() : null),
    async (cid) => {
      try {
        return await fetchAllCanvasNodeImages(cid);
      } catch {
        return { items: [], canvas_online: false } as Awaited<ReturnType<typeof fetchAllCanvasNodeImages>>;
      }
    },
  );

  /** 从故事板分组列表中提取已生成素材（图片/视频/音频） */
  function draftItems(groups: { title: string; drafts?: Array<{ id: string; label?: string; mediaType?: string; imgUrl?: string; videoUrl?: string; audioUrl?: string }> }[]): RefAssetItem[] {
    const items: RefAssetItem[] = [];
    for (const g of groups || []) {
      for (const d of g.drafts || []) {
        const mt = (d.mediaType || 'image') as RefAssetItem['type'];
        const url = mt === 'video' ? d.videoUrl : mt === 'audio' ? d.audioUrl : d.imgUrl;
        if (!url) continue;
        items.push({
          id: d.id,
          name: `${g.title} · ${d.label || '草稿'}`,
          url,
          type: mt,
          thumb: mt === 'audio' ? '' : (d.imgUrl || url),
        });
      }
    }
    return items;
  }

  const items = (): RefAssetItem[] => {
    if (source() === KEY_ELEMENT_SOURCE) return draftItems(state.keyElements);
    if (source() === SHOTS_SOURCE) return draftItems(state.shots);
    if (source() === AUDIO_SOURCE) return draftItems(state.audioItems);
    return (canvasImages()?.items || []).map((it) => ({
      id: it.id,
      name: it.name,
      url: it.url,
      type: 'image' as const,
      thumb: it.thumb || it.url,
    }));
  };

  const loading = () =>
    isStoryboardSource(source()) ? false : canvasImages.loading;

  const sourceLabel = () => {
    if (source() === KEY_ELEMENT_SOURCE) return '关键元素';
    if (source() === SHOTS_SOURCE) return '分镜';
    if (source() === AUDIO_SOURCE) return '音频';
    const cv = (canvasList()?.canvases || []).find((c) => c.id === source());
    return cv ? cv.title : '选择素材源…';
  };

  function kindLabel(kind: string) {
    return kind === 'smart' ? '智能画布' : '普通画布';
  }

  function pickSource(id: string) {
    setSource(id);
    setDropdownOpen(false);
  }

  function videoThumb(url: string) {
    const u = safeUrl(url);
    return u.includes('#') ? u : `${u}#t=0.1`;
  }

  return (
    <Show when={props.open}>
      <div class="asset-modal canvas-picker-modal">
        <div class="asset-modal-backdrop" onClick={props.onClose} />
        <div class="asset-modal-panel">
          {/* 头部：标题 + 源选择器 + 关闭 */}
          <div class="asset-modal-header">
            <div class="canvas-picker-title">
              <FiLayers size={15} />
              <span>选择参考素材</span>
            </div>

            <div class="canvas-selector">
              <button
                class="canvas-selector-btn"
                onClick={() => setDropdownOpen((v) => !v)}
              >
                <span class="canvas-selector-name">{sourceLabel()}</span>
                <FiChevronDown size={12} />
              </button>
              <Show when={dropdownOpen()}>
                <div class="canvas-selector-dropdown">
                  {/* 故事板分区选项（关键元素 / 分镜 / 音频） */}
                  <button
                    class="canvas-selector-item"
                    classList={{ active: source() === KEY_ELEMENT_SOURCE }}
                    onClick={() => pickSource(KEY_ELEMENT_SOURCE)}
                  >
                    <span class="canvas-selector-item-kind">关键元素</span>
                    <span class="canvas-selector-item-name">已生成的所有素材</span>
                  </button>
                  <button
                    class="canvas-selector-item"
                    classList={{ active: source() === SHOTS_SOURCE }}
                    onClick={() => pickSource(SHOTS_SOURCE)}
                  >
                    <span class="canvas-selector-item-kind">分镜</span>
                    <span class="canvas-selector-item-name">已生成的所有素材</span>
                  </button>
                  <button
                    class="canvas-selector-item"
                    classList={{ active: source() === AUDIO_SOURCE }}
                    onClick={() => pickSource(AUDIO_SOURCE)}
                  >
                    <span class="canvas-selector-item-kind">音频</span>
                    <span class="canvas-selector-item-name">已生成的所有素材</span>
                  </button>
                  {/* 画布分类 */}
                  <Show when={(canvasList()?.canvases || []).length === 0}>
                    <div class="canvas-selector-empty">暂无画布</div>
                  </Show>
                  <For each={canvasList()?.canvases || []}>
                    {(cv: CanvasListItem) => (
                      <button
                        class="canvas-selector-item"
                        classList={{ active: cv.id === source() }}
                        onClick={() => pickSource(cv.id)}
                      >
                        <span class="canvas-selector-item-kind">{kindLabel(cv.kind)}</span>
                        <span class="canvas-selector-item-name">{cv.title}</span>
                      </button>
                    )}
                  </For>
                </div>
              </Show>
            </div>

            <button class="asset-modal-close" onClick={props.onClose} title="关闭">
              <FiX size={16} />
            </button>
          </div>

          {/* 主体网格 */}
          <div class="asset-modal-body">
            <Show when={loading()}>
              <div class="asset-modal-status">
                <FiLoader size={22} class="animate-spin" />
                <p>加载中...</p>
              </div>
            </Show>

            <Show when={!loading() && !isStoryboardSource(source()) && canvasImages()?.canvas_online === false}>
              <div class="asset-modal-status">
                <FiAlertCircle size={22} />
                <p>画布未连接，画布源不可用（故事板分区仍可用）</p>
                <button type="button" class="btn-secondary" onClick={() => void refetchCanvasImages()}>重连画布</button>
              </div>
            </Show>

            <Show when={!loading() && items().length === 0 && (isStoryboardSource(source()) || canvasImages()?.canvas_online !== false)}>
              <div class="asset-modal-status">
                <FiImage size={28} />
                <p>{isStoryboardSource(source()) ? '该分区暂无已生成素材' : '该画布中暂无素材'}</p>
              </div>
            </Show>

            <Show when={!loading() && items().length > 0}>
              <div class="asset-grid">
                <For each={items()}>
                  {(item) => (
                    <div
                      class="asset-card ref-asset-card"
                      title={`${item.name} — 点击添加到参考素材`}
                      onClick={() => props.onPick(item)}
                    >
                      <Show when={item.type === 'video'}>
                        <video class="ref-asset-media" src={videoThumb(item.url)} muted playsinline preload="metadata" />
                        <span class="ref-asset-badge"><FiVideo size={11} /></span>
                      </Show>
                      <Show when={item.type === 'audio'}>
                        <div class="ref-asset-audio">
                          <FiMusic size={22} />
                        </div>
                        <span class="ref-asset-badge"><FiMusic size={11} /></span>
                      </Show>
                      <Show when={item.type === 'image'}>
                        <Show when={safeUrl(item.thumb)} fallback={
                          <div class="asset-card-placeholder"><FiImage size={28} /></div>
                        }>
                          <img class="ref-asset-media" src={safeUrl(item.thumb)} alt={item.name} loading="lazy" />
                        </Show>
                      </Show>
                      <div class="asset-card-name">{item.name}</div>
                      <span class="ref-asset-add"><FiPlus size={13} /></span>
                    </div>
                  )}
                </For>
              </div>
            </Show>
          </div>

          {/* 底部提示 */}
          <div class="asset-modal-footer">
            <span class="asset-selected-count">点击素材卡片即可添加到参考素材</span>
            <button class="btn-secondary" onClick={props.onClose}>完成</button>
          </div>
        </div>
      </div>
    </Show>
  );
}
