import { Show, createSignal } from 'solid-js';
import { FiDownload, FiX } from 'solid-icons/fi';
import { t } from '@/lib/locale';
import { useFocusTrap } from '@/lib/focus-trap';

/**
 * 原图预览 lightbox（自 ChatMessageItem 拆出共用）：
 * 受控组件——url 非空时显示；点击背景/关闭钮由父级关闭（Esc 监听在父级）。
 * 生图卡片与用户消息内联媒体共用（消灭两处重复实现）。
 */
export function ImageLightbox(props: { url: () => string; onClose: () => void }) {
  // 焦点圈闭：打开圈闭、Esc 关闭、关闭还原焦点
  const [boxEl, setBoxEl] = createSignal<HTMLElement>();
  useFocusTrap(() => (props.url() ? boxEl() : undefined), { onEscape: () => props.onClose() });

  return (
    <Show when={props.url()}>
      <div
        class="image-lightbox"
        ref={setBoxEl}
        role="dialog"
        aria-modal="true"
        aria-label={t('rp.msg.lightboxAria')}
        onClick={() => props.onClose()}
      >
        <img
          src={props.url()}
          alt={t('rp.msg.lightboxAlt')}
          onClick={(e) => e.stopPropagation()}
        />
        <div class="image-lightbox-actions">
          <a
            href={props.url()}
            download=""
            title={t('rp.msg.downloadOriginal')}
            onClick={(e) => e.stopPropagation()}
          >
            <FiDownload size={16} />
          </a>
          <button type="button" title={t('rp.msg.closeEsc')} onClick={() => props.onClose()}>
            <FiX size={18} />
          </button>
        </div>
      </div>
    </Show>
  );
}
