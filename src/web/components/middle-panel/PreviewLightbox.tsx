import { createSignal } from 'solid-js';
import { FiX } from 'solid-icons/fi';
import { useFocusTrap } from '@/lib/focus-trap';

/**
 * 图片放大查看 lightbox（支持滚轮缩放 + 鼠标按住拖拽平移）。
 * 焦点圈闭内置：Esc 关闭；由父级以 <Show when={url}> 条件挂载。
 */
export function PreviewLightbox(props: { url: string; onClose: () => void }) {
  const [zoom, setZoom] = createSignal(1);
  const [pan, setPan] = createSignal({ x: 0, y: 0 });
  const [dragging, setDragging] = createSignal(false);
  const [el, setEl] = createSignal<HTMLElement>();
  let startX = 0;
  let startY = 0;
  let baseX = 0;
  let baseY = 0;

  const closeLightbox = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    props.onClose();
  };

  // 焦点圈闭：放大预览 Esc 关闭（补齐 title 提示对应的实际监听）
  useFocusTrap(() => el(), { onEscape: () => closeLightbox() });

  /** 按住图片拖动：上下左右平移（window 级监听，拖出图片不丢手势） */
  function onImgMouseDown(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setDragging(true);
    startX = e.clientX;
    startY = e.clientY;
    baseX = pan().x;
    baseY = pan().y;
    const onMove = (ev: MouseEvent) => {
      setPan({ x: baseX + (ev.clientX - startX), y: baseY + (ev.clientY - startY) });
    };
    const onUp = () => {
      setDragging(false);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }

  return (
    <div
      class="preview-lightbox"
      ref={setEl}
      role="dialog"
      aria-modal="true"
      aria-label="放大预览"
      onClick={() => closeLightbox()}
      onWheel={(e) => {
        e.preventDefault();
        setZoom((z) => Math.min(5, Math.max(0.2, z - e.deltaY * 0.001)));
      }}
    >
      <img
        src={props.url}
        alt="放大预览"
        class={`preview-lightbox-img ${dragging() ? 'preview-lightbox-img-dragging' : ''}`}
        style={{ transform: `translate(${pan().x}px, ${pan().y}px) scale(${zoom()})` }}
        onClick={(e) => e.stopPropagation()}
        onMouseDown={onImgMouseDown}
        title="按住拖动移动，滚轮缩放"
      />
      <span class="preview-lightbox-zoom">{Math.round(zoom() * 100)}%</span>
      <button
        type="button"
        class="preview-lightbox-close"
        onClick={() => closeLightbox()}
        title="关闭 (Esc)"
      >
        <FiX size={20} />
      </button>
    </div>
  );
}
