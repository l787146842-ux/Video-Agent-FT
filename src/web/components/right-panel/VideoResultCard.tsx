import { For, Show, createSignal, onMount, onCleanup } from 'solid-js';
import { FiBookmark, FiDownload, FiVideo } from 'solid-icons/fi';
import { t } from '@/lib/locale';
import { safeUrl } from '@/lib/utils';
import { absUrl } from '@/lib/chat/chat-image-drag';
import { togglePinArtifact, isPinnedId, pinnedIdOf } from '@/stores/pinned';
import type { VideoCardData } from '@/types';
import { Lightbox } from '@/components/Lightbox';

/**
 * 视频结果内联预览卡：复用 ImageResultCard 的结构与交互模式
 *（<video> 首帧 poster + 左上角 ▶ 角标；点击 lightbox 播放、悬停下载、Esc 关闭）。
 * 缩略图左上角钉住入口（F3）：钉到 PinnedRail 跨轮对照栏。
 */
export function VideoResultCard(props: { card: VideoCardData }) {
  const card = () => props.card;
  const [lightboxUrl, setLightboxUrl] = createSignal('');

  // Esc 关闭视频预览
  function onDocKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') setLightboxUrl('');
  }
  onMount(() => document.addEventListener('keydown', onDocKeyDown));
  onCleanup(() => document.removeEventListener('keydown', onDocKeyDown));

  return (
    <>
      <Show when={(card().items || []).length > 0}>
        <div class="image-card video-card">
          <div class="image-card-header">
            <FiVideo size={14} />
            <span>{t('rp.msg.videoResult')}</span>
          </div>
          <div class="image-card-grid">
            <For each={card().items}>
              {(item, idx) => {
                const fname = () =>
                  item.name || item.url.split('/').pop()?.split('?')[0] || `video-${idx() + 1}.mp4`;
                return (
                  <div
                    class="image-card-thumb video-card-thumb"
                    onClick={() => setLightboxUrl(absUrl(item.url))}
                    title={t('rp.msg.videoTip', { name: fname() })}
                  >
                    {/* preload=metadata：缩略只加载首帧/元数据，点击播放时再全量 */}
                    <video
                      src={safeUrl(item.url)}
                      poster={item.thumb ? safeUrl(item.thumb) : undefined}
                      preload="metadata"
                      muted
                      playsinline
                    />
                    <span class="video-card-badge">▶</span>
                    <span class="image-card-label">{fname()}</span>
                    <button
                      type="button"
                      class="image-card-pin"
                      classList={{ pinned: isPinnedId(pinnedIdOf({ kind: 'video', url: item.url, name: fname() })) }}
                      title="钉住到对照栏"
                      onClick={(e) => {
                        e.stopPropagation();
                        togglePinArtifact({ kind: 'video', url: item.url, name: fname(), thumb: item.thumb });
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
                        a.href = absUrl(item.url);
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

      {/* 视频播放 lightbox（共享组件，autoplay + 下载；Esc 关闭见上方监听） */}
      <Show when={lightboxUrl()}>
        <Lightbox mode="media" url={lightboxUrl()} kind="video" onClose={() => setLightboxUrl('')} />
      </Show>
    </>
  );
}
