import { For, Show, createSignal, onMount, onCleanup } from 'solid-js';
import { FiBookmark, FiDownload, FiImage } from 'solid-icons/fi';
import { t } from '@/lib/locale';
import { safeUrl } from '@/lib/utils';
import { createImageDrag, absUrl } from '@/lib/chat/chat-image-drag';
import { endCanvasImageDrag } from '@/stores/canvas';
import { togglePinArtifact, isPinnedId, pinnedIdOf } from '@/stores/pinned';
import type { ImageCardData } from '@/types';
import { ImageLightbox } from './ImageLightbox';

/**
 * 生图结果卡片 + 原图预览 lightbox（拖拽/下载/Esc 关闭）。
 * 缩略图左上角钉住入口（F3）：钉到 PinnedRail 跨轮对照栏；
 * 钉住职责划分见 stores/pinned.ts 头注释（不并入 lightbox/MediaViewer）。
 */
export function ImageResultCard(props: { card: ImageCardData }) {
  const card = () => props.card;
  const drag = createImageDrag();
  const [lightboxUrl, setLightboxUrl] = createSignal('');

  // Esc 关闭原图预览
  function onDocKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') setLightboxUrl('');
  }
  onMount(() => document.addEventListener('keydown', onDocKeyDown));
  onCleanup(() => document.removeEventListener('keydown', onDocKeyDown));

  return (
    <>
      <Show when={(card().image_urls || []).length > 0}>
        <div class="image-card">
          <div class="image-card-header">
            <FiImage size={14} />
            <span>{t('rp.msg.imageResult')}</span>
            <Show when={card().provider}>
              <span class="image-card-provider">{card().provider}</span>
            </Show>
          </div>
          <div class="image-card-grid">
            <For each={card().image_urls}>
              {(url, idx) => {
                const fname = () => url.split('/').pop()?.split('?')[0] || `image-${idx() + 1}.png`;
                return (
                  <div
                    class="image-card-thumb"
                    draggable="true"
                    onDragStart={(e) => drag.handleImageDragStart(e, url, fname())}
                    onDragEnd={() => endCanvasImageDrag()}
                    onPointerDown={(e) => drag.onThumbPointerDown(e, url, fname())}
                    onClick={() => { if (!drag.wasMoved()) setLightboxUrl(absUrl(url)); }}
                    title={t('rp.msg.imageTip', { name: fname() })}
                  >
                    <img
                      src={safeUrl(url)}
                      alt={fname()}
                      loading="lazy"
                      onLoad={() => drag.prefetchDragFile(url, fname())}
                      onError={(e) => {
                        (e.currentTarget as HTMLImageElement).style.display = 'none';
                      }}
                    />
                    <span class="image-card-label">{fname()}</span>
                    <button
                      type="button"
                      class="image-card-pin"
                      classList={{ pinned: isPinnedId(pinnedIdOf({ kind: 'image', url, name: fname() })) }}
                      title="钉住到对照栏"
                      onClick={(e) => {
                        e.stopPropagation();
                        togglePinArtifact({ kind: 'image', url, name: fname() });
                      }}
                    >
                      <FiBookmark size={12} />
                    </button>
                    <button
                      type="button"
                      class="image-card-download"
                      title={t('rp.msg.download')}
                      onClick={(e) => {
                        e.stopPropagation();
                        const a = document.createElement('a');
                        a.href = absUrl(url);
                        a.download = fname();
                        a.click();
                      }}
                    >
                      <FiDownload size={12} />
                    </button>
                  </div>
                );
              }}
            </For>
          </div>
        </div>
      </Show>

      {/* 原图预览 lightbox（共享组件；Esc 关闭见上方监听） */}
      <ImageLightbox url={lightboxUrl} onClose={() => setLightboxUrl('')} />
    </>
  );
}
