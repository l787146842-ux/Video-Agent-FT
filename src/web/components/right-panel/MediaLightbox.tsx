import { onMount, onCleanup, Switch, Match, createSignal } from 'solid-js';
import { FiDownload, FiX } from 'solid-icons/fi';
import { safeUrl } from '@/lib/utils';
import { t } from '@/lib/locale';
import { useFocusTrap } from '@/lib/focus-trap';

/**
 * 媒体预览灯箱：点击/双击输入框缩略块后放大查看原图/原视频/播放音频。
 * 点击背景或按 Esc 关闭。
 */
export function MediaLightbox(props: {
  url: string;
  kind: string;
  onClose: () => void;
}) {
  // 焦点圈闭：打开圈闭、Esc 关闭、关闭还原焦点
  const [boxEl, setBoxEl] = createSignal<HTMLElement>();
  useFocusTrap(boxEl, { onEscape: () => props.onClose() });

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') props.onClose();
  }
  onMount(() => document.addEventListener('keydown', onKey));
  onCleanup(() => document.removeEventListener('keydown', onKey));

  const src = () => safeUrl(props.url);

  return (
    <div
      class="image-lightbox"
      ref={setBoxEl}
      role="dialog"
      aria-modal="true"
      aria-label={t('rp.lightbox.dialogAria')}
      onClick={() => props.onClose()}
    >
      <Switch fallback={
        <img src={src()} alt={t('rp.lightbox.alt')} onClick={(e) => e.stopPropagation()} />
      }>
        <Match when={props.kind === 'video'}>
          <video
            src={src()}
            controls
            autoplay
            onClick={(e) => e.stopPropagation()}
          />
        </Match>
        <Match when={props.kind === 'audio'}>
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
          title={t('rp.lightbox.download')}
          onClick={(e) => e.stopPropagation()}
        >
          <FiDownload size={16} />
        </a>
        <button type="button" title={t('rp.lightbox.close')} onClick={() => props.onClose()}>
          <FiX size={18} />
        </button>
      </div>
    </div>
  );
}
