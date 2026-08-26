/** 统一预览灯箱（任务 #11 三合一：原 ImageLightbox/MediaLightbox/PreviewLightbox 收敛）。
 *
 * 三种模式（mode 参数切换，DOM 类名与原实现逐一相同，零视觉漂移）：
 *   image（默认）— 原图预览：下载 + 关闭钮（class image-lightbox）；
 *   media        — 视频/音频/图片按 kind 分发（class image-lightbox，safeUrl 守卫）；
 *   zoom         — 滚轮缩放 + 按住拖拽平移 + 百分比角标（class preview-lightbox）。
 * 无障碍行为统一保留：焦点圈闭（useFocusTrap）+ Esc 关闭 + 关闭还原焦点；
 * role=dialog / aria-modal / aria-label 与各自原取值一致。
 */
import { onCleanup, Switch, Match, Show, createSignal } from 'solid-js';
import { FiDownload, FiX } from 'solid-icons/fi';
import { safeUrl } from '@/lib/utils';
import { t } from '@/lib/locale';
import { useFocusTrap } from '@/lib/focus-trap';

export type LightboxMode = 'image' | 'media' | 'zoom';

export interface LightboxProps {
  /** 媒体源；支持普通字符串或访问器；空串=不显示（组件内置守卫） */
  url: string | (() => string);
  /** 预览模式（默认 image） */
  mode?: LightboxMode;
  /** media 模式的媒体类型（video/audio；其余按图片回退） */
  kind?: string;
  onClose: () => void;
}

export function Lightbox(props: LightboxProps) {
  const mode = () => props.mode || 'image';
  const rawUrl = () => (typeof props.url === 'function' ? props.url() : props.url);
  // media 模式沿用原 MediaLightbox 的 safeUrl 守卫；其余模式直传
  const src = () => (mode() === 'media' ? safeUrl(rawUrl()) : rawUrl());

  const [el, setEl] = createSignal<HTMLElement>();
  const [zoom, setZoom] = createSignal(1);
  const [pan, setPan] = createSignal({ x: 0, y: 0 });
  const [dragging, setDragging] = createSignal(false);
  let startX = 0;
  let startY = 0;
  let baseX = 0;
  let baseY = 0;

  const closeLightbox = () => {
    // zoom 模式关闭时复位缩放/平移（与原 PreviewLightbox 一致）
    setZoom(1);
    setPan({ x: 0, y: 0 });
    props.onClose();
  };

  // 焦点圈闭：url 非空时打开圈闭、Esc 关闭、关闭还原焦点
  // （media 模式的 Esc 关闭由圈闭 capture 监听覆盖，视频控件聚焦也生效；
  // 不再有 document 级重复 onDocKey）
  useFocusTrap(() => (rawUrl() ? el() : undefined), { onEscape: () => closeLightbox() });

  /** zoom 拖拽的 window 监听活动集（拖拽中组件卸载时由 onCleanup 兜底摘除） */
  let dragListeners: { onMove: (ev: MouseEvent) => void; onUp: () => void } | undefined;

  function detachDrag(): void {
    if (!dragListeners) return;
    window.removeEventListener('mousemove', dragListeners.onMove);
    window.removeEventListener('mouseup', dragListeners.onUp);
    dragListeners = undefined;
    setDragging(false);
  }

  // 组件卸载兜底：拖拽进行中被关闭/卸载时不留 window 监听泄漏
  onCleanup(detachDrag);

  /** zoom 模式：按住图片拖动平移（window 级监听，拖出图片不丢手势） */
  function onImgMouseDown(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    detachDrag();
    setDragging(true);
    startX = e.clientX;
    startY = e.clientY;
    baseX = pan().x;
    baseY = pan().y;
    const onMove = (ev: MouseEvent) => {
      setPan({ x: baseX + (ev.clientX - startX), y: baseY + (ev.clientY - startY) });
    };
    const onUp = () => detachDrag();
    dragListeners = { onMove, onUp };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }

  return (
    <Show when={rawUrl()}>
      <Show when={mode() === 'zoom'} fallback={
        // image / media 模式：共用 image-lightbox 容器（与原两实现类名一致）
        <div
          class="image-lightbox"
          ref={setEl}
          role="dialog"
          aria-modal="true"
          aria-label={mode() === 'media' ? t('rp.lightbox.dialogAria') : t('rp.msg.lightboxAria')}
          onClick={() => props.onClose()}
        >
          <Switch fallback={
            <img
              src={src()}
              alt={mode() === 'media' ? t('rp.lightbox.alt') : t('rp.msg.lightboxAlt')}
              onClick={(e) => e.stopPropagation()}
            />
          }
          >
            <Match when={mode() === 'media' && props.kind === 'video'}>
              <video src={src()} controls autoplay onClick={(e) => e.stopPropagation()} />
            </Match>
            <Match when={mode() === 'media' && props.kind === 'audio'}>
              {/* 音频无画面：居中播放器 */}
              <div class="image-lightbox-audio" onClick={(e) => e.stopPropagation()}>
                <audio src={src()} controls autoplay />
              </div>
            </Match>
          </Switch>
          <div class="image-lightbox-actions">
            <a
              href={src()}
              download=""
              title={mode() === 'media' ? t('rp.lightbox.download') : t('rp.msg.downloadOriginal')}
              onClick={(e) => e.stopPropagation()}
            >
              <FiDownload size={16} />
            </a>
            <button
              type="button"
              title={mode() === 'media' ? t('rp.lightbox.close') : t('rp.msg.closeEsc')}
              onClick={() => props.onClose()}
            >
              <FiX size={18} />
            </button>
          </div>
        </div>
      }
      >
        {/* zoom 模式：滚轮缩放 + 拖拽平移（原 PreviewLightbox 行为保真） */}
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
            src={src()}
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
      </Show>
    </Show>
  );
}
