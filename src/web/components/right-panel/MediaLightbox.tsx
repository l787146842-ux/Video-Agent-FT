import { onMount, onCleanup, Show } from 'solid-js';
import { FiDownload, FiX } from 'solid-icons/fi';
import { safeUrl } from '@/lib/utils';
import { t } from '@/lib/locale';

/**
 * 媒体预览灯箱：双击输入框缩略块后放大查看原图/原视频。
 * 点击背景或按 Esc 关闭。
 */
export function MediaLightbox(props: {
  url: string;
  kind: string;
  onClose: () => void;
}) {
  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') props.onClose();
  }
  onMount(() => document.addEventListener('keydown', onKey));
  onCleanup(() => document.removeEventListener('keydown', onKey));

  const src = () => safeUrl(props.url);

  return (
    <div class="image-lightbox" onClick={() => props.onClose()}>
      <Show when={props.kind === 'video'} fallback={
        <img src={src()} alt={t('rp.lightbox.alt')} onClick={(e) => e.stopPropagation()} />
      }>
        <video
          src={src()}
          controls
          autoplay
          onClick={(e) => e.stopPropagation()}
        />
      </Show>
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
