import { Show, For, createSignal, createResource, createEffect } from 'solid-js';
import {
  FiX, FiImage, FiMusic, FiVideo, FiLoader, FiAlertCircle, FiPlus, FiChevronDown, FiLayers, FiCheck,
} from 'solid-icons/fi';
import {
  fetchAllCanvasNodeImages, fetchCanvasList, type CanvasListItem,
} from '@/api/canvas';
import { safeUrl } from '@/lib/utils';

/** 参考素材项（统一图片/视频/音频） */
export interface RefAssetItem {
  id: string;
  name: string;
  url: string;
  type: 'image' | 'video' | 'audio';
  thumb: string;
}

/**
 * 参考素材选择弹窗：源下拉仅画布列表（故事板分区/关键元素按用户审定不恢复），
 * 网格展示所选画布的素材；多选 → 「添加选中」批量加入参考素材横条。
 */
export function RefAssetPickerModal(props: {
  open: boolean;
  onClose: () => void;
  onPick: (items: RefAssetItem[]) => void;
}) {
  const [source, setSource] = createSignal<string>('');
  const [dropdownOpen, setDropdownOpen] = createSignal(false);
  /** 多选暂存（确认时批量添加） */
  const [picked, setPicked] = createSignal<RefAssetItem[]>([]);

  // 每次打开重置选择
  createEffect(() => { if (props.open) setPicked([]); });

  const isPicked = (item: RefAssetItem) => picked().some((p) => p.url === item.url);
  function togglePick(item: RefAssetItem) {
    setPicked((prev) =>
      prev.some((p) => p.url === item.url)
        ? prev.filter((p) => p.url !== item.url)
        : [...prev, item]);
  }
  function confirmPick() {
    if (!picked().length) return;
    props.onPick(picked());
    setPicked([]);
    props.onClose();
  }

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

  /** 打开后未选源时默认选中第一个画布 */
  createEffect(() => {
    if (!props.open || source() !== '') return;
    const first = (canvasList()?.canvases || [])[0];
    if (first) setSource(first.id);
  });

  // 选中画布的图片（源为画布时加载）
  const [canvasImages, { refetch: refetchCanvasImages }] = createResource(
    () => (props.open && source() !== '' ? source() : null),
    async (cid) => {
      try {
        return await fetchAllCanvasNodeImages(cid);
      } catch {
        return { items: [], canvas_online: false } as Awaited<ReturnType<typeof fetchAllCanvasNodeImages>>;
      }
    },
  );

  const items = (): RefAssetItem[] =>
    (canvasImages()?.items || []).map((it) => ({
      id: it.id,
      name: it.name,
      url: it.url,
      type: 'image' as const,
      thumb: it.thumb || it.url,
    }));

  const loading = () => canvasImages.loading;

  const sourceLabel = () => {
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
        <div class="asset-modal-backdrop" onClick={() => props.onClose()} />
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
                  {/* 仅画布选项（故事板分区已移除） */}
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

            <button class="asset-modal-close" onClick={() => props.onClose()} title="关闭">
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

            <Show when={!loading() && source() === '' && (canvasList()?.canvases || []).length === 0}>
              <div class="asset-modal-status">
                <FiImage size={28} />
                <p>暂无可用画布，可在 + 菜单本地上传素材</p>
              </div>
            </Show>

            <Show when={!loading() && source() !== '' && canvasImages()?.canvas_online === false}>
              <div class="asset-modal-status">
                <FiAlertCircle size={22} />
                <p>画布未连接，画布源不可用（仍可用参考栏已有素材或 + 本地上传）</p>
                <button type="button" class="btn-secondary" onClick={() => void refetchCanvasImages()}>重连画布</button>
              </div>
            </Show>

            <Show when={!loading() && source() !== '' && canvasImages()?.canvas_online !== false && items().length === 0}>
              <div class="asset-modal-status">
                <FiImage size={28} />
                <p>该画布中暂无素材</p>
              </div>
            </Show>

            <Show when={!loading() && items().length > 0}>
              <div class="asset-grid">
                <For each={items()}>
                  {(item) => (
                    <div
                      class={`asset-card ref-asset-card${isPicked(item) ? ' selected' : ''}`}
                      title={`${item.name} — 点击选中，确认后加入参考素材`}
                      onClick={() => togglePick(item)}
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
                      <span class="ref-asset-add">{isPicked(item) ? <FiCheck size={13} /> : <FiPlus size={13} />}</span>
                    </div>
                  )}
                </For>
              </div>
            </Show>
          </div>

          {/* 底部提示 */}
          <div class="asset-modal-footer">
            <span class="asset-selected-count">
              {picked().length ? `已选 ${picked().length} 个` : '勾选多个素材后一次加入参考栏'}
            </span>
            <Show when={picked().length > 0}>
              <button class="btn-secondary" onClick={() => setPicked([])}>清空</button>
            </Show>
            <button class="btn-secondary" disabled={picked().length === 0} onClick={confirmPick}>
              添加选中{picked().length ? ` (${picked().length})` : ''}
            </button>
            <button class="btn-secondary" onClick={() => props.onClose()}>完成</button>
          </div>
        </div>
      </div>
    </Show>
  );
}
