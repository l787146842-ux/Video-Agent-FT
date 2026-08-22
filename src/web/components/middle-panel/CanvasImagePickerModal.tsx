import { Show, For, createSignal, createResource, createEffect } from 'solid-js';
import { FiX, FiImage, FiLoader, FiAlertCircle, FiDownload, FiChevronDown } from 'solid-icons/fi';
import {
  fetchAllCanvasNodeImages, fetchCanvasList,
  type AllCanvasImageItem, type CanvasListItem,
} from '@/api/canvas';
import { safeUrl } from '@/lib/utils';
import { useFocusTrap } from '@/lib/focus-trap';

/**
 * "当前画布操作空间"图片选择弹窗（单选模式 + 手动画布选择器）。
 * 顶部下拉选择目标画布，下方网格展示该画布内的图片，选中一张后导入到预览。
 */
export function CanvasImagePickerModal(props: {
  open: boolean;
  onClose: () => void;
  onPick: (item: AllCanvasImageItem) => void;
}) {
  const [selectedId, setSelectedId] = createSignal<string | null>(null);
  const [selectedCanvasId, setSelectedCanvasId] = createSignal<string>('');
  const [dropdownOpen, setDropdownOpen] = createSignal(false);

  // 焦点圈闭（任务 #29）：打开圈闭、Esc 关闭、关闭还原焦点
  // （容器随 open 置空：<Show> 卸载后 ref 信号残留旧元素，不得据此保持激活）
  const [panelEl, setPanelEl] = createSignal<HTMLElement>();
  useFocusTrap(() => (props.open ? panelEl() : undefined), { onEscape: () => props.onClose() });

  // 加载画布列表
  const [canvasList, { refetch: refetchCanvasList }] = createResource(
    () => (props.open ? 'load' : null),
    async () => {
      setSelectedId(null);
      return await fetchCanvasList();
    },
  );

  // 默认选中第一个画布（最近更新的）
  createEffect(() => {
    const list = canvasList()?.canvases;
    if (list && list.length > 0 && !selectedCanvasId()) {
      setSelectedCanvasId(list[0].id);
    }
  });

  // 加载选中画布的图片
  const [images] = createResource(
    () => (props.open && selectedCanvasId() ? selectedCanvasId() : null),
    async (cid) => {
      setSelectedId(null);
      return await fetchAllCanvasNodeImages(cid);
    },
  );

  const currentCanvas = () => {
    const id = selectedCanvasId();
    return (canvasList()?.canvases || []).find((c) => c.id === id);
  };

  const selectedItem = () => {
    const id = selectedId();
    if (!id) return null;
    return (images()?.items || []).find((it) => it.id === id) || null;
  };

  function confirmPick() {
    const item = selectedItem();
    if (!item) return;
    props.onPick(item);
    setSelectedId(null);
    props.onClose();
  }

  function selectCanvas(id: string) {
    setSelectedCanvasId(id);
    setDropdownOpen(false);
  }

  function kindLabel(kind: string) {
    return kind === 'smart' ? '智能画布' : '普通画布';
  }

  return (
    <Show when={props.open}>
      <div class="asset-modal canvas-picker-modal">
        <div class="asset-modal-backdrop" onClick={() => props.onClose()} />
        <div
          class="asset-modal-panel"
          ref={setPanelEl}
          role="dialog"
          aria-modal="true"
          aria-label="画布操作空间图片选择"
        >
          {/* 头部：标题 + 画布选择器 + 关闭 */}
          <div class="asset-modal-header">
            <div class="canvas-picker-title">
              <FiImage size={15} />
              <span>画布操作空间</span>
            </div>

            {/* 手动画布选择器下拉 */}
            <div class="canvas-selector">
              <button
                class="canvas-selector-btn"
                onClick={() => setDropdownOpen((v) => !v)}
              >
                <Show when={currentCanvas()} fallback={<span>选择画布…</span>}>
                  <span class="canvas-selector-kind">{kindLabel(currentCanvas()!.kind)}</span>
                  <span class="canvas-selector-name">{currentCanvas()!.title}</span>
                </Show>
                <FiChevronDown size={12} />
              </button>
              <Show when={dropdownOpen()}>
                <div class="canvas-selector-dropdown">
                  <Show when={(canvasList()?.canvases || []).length === 0}>
                    <div class="canvas-selector-empty">暂无画布</div>
                  </Show>
                  <For each={canvasList()?.canvases || []}>
                    {(cv: CanvasListItem) => (
                      <button
                        class="canvas-selector-item"
                        classList={{ active: cv.id === selectedCanvasId() }}
                        onClick={() => selectCanvas(cv.id)}
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

          {/* 主体 */}
          <div class="asset-modal-body">
            <Show when={canvasList.loading || images.loading}>
              <div class="asset-modal-status">
                <FiLoader size={22} class="animate-spin" />
                <p>加载中...</p>
              </div>
            </Show>

            <Show when={!canvasList.loading && canvasList()?.canvas_online === false}>
              <div class="asset-modal-status">
                <FiAlertCircle size={22} />
                <p>画布未连接，无法从画布导入图片</p>
                <p class="asset-modal-status-hint">请检查画布服务是否启动</p>
                <button type="button" class="btn-secondary" onClick={() => void refetchCanvasList()}>重连画布</button>
              </div>
            </Show>

            <Show when={!canvasList.loading && canvasList()?.canvas_online !== false && (canvasList()?.canvases || []).length === 0}>
              <div class="asset-modal-status">
                <FiImage size={28} />
                <p>暂无画布</p>
                <p class="asset-modal-status-hint">请先在画布中创建一个画布</p>
              </div>
            </Show>

            <Show when={!images.loading && images() && images()!.canvas_online !== false && (images()!.items?.length ?? 0) === 0 && selectedCanvasId()}>
              <div class="asset-modal-status">
                <FiImage size={28} />
                <p>该画布中暂无图片</p>
                <p class="asset-modal-status-hint">在画布上生成的素材会出现在这里</p>
              </div>
            </Show>

            <Show when={!images.loading && images() && images()!.items && images()!.items.length > 0}>
              <div class="asset-grid">
                <For each={images()!.items}>{(item) => {
                  const thumbUrl = () => safeUrl(item.thumb || item.url);
                  const isSelected = () => selectedId() === item.id;
                  return (
                    <div
                      class="asset-card"
                      classList={{ selected: isSelected() }}
                      title={`${item.name} — 点击选中`}
                      onClick={() => setSelectedId(isSelected() ? null : item.id)}
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
          </div>

          {/* 底部 */}
          <div class="asset-modal-footer">
            <span class="asset-selected-count">
              {selectedId() ? '已选 1 个' : '未选择'}
            </span>
            <button
              class="btn-primary"
              disabled={!selectedId()}
              onClick={confirmPick}
            >
              <FiDownload size={13} /> 导入到预览
            </button>
          </div>
        </div>
      </div>
    </Show>
  );
}
