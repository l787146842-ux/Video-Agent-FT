import { For, Show } from 'solid-js';
import { FiImage } from 'solid-icons/fi';
import { safeUrl } from '@/lib/utils';
import type { CanvasNodeImageItem } from '@/api/canvas';

/**
 * @ 提及画布图片的候选弹层（锚定在输入框上方）。
 * 从 ChatInput 拆出，保持主组件精简。
 */
export function MentionPopup(props: {
  loading: boolean;
  canvasOnline: boolean | undefined;
  items: CanvasNodeImageItem[];
  activeIdx: number;
  query: string;
  onSelect: (item: CanvasNodeImageItem) => void;
}) {
  return (
    <div class="mention-popup" role="listbox" aria-label="画布图片选择">
      <Show when={props.loading}>
        <div class="mention-popup-status">加载画布图片中...</div>
      </Show>
      <Show when={!props.loading && props.canvasOnline === false}>
        <div class="mention-popup-status">画布未连接，画布图片引用不可用（故事板素材仍可 @ 引用）</div>
      </Show>
      <Show when={!props.loading && props.items.length === 0 && props.canvasOnline !== false}>
        <div class="mention-popup-status">
          <Show when={props.query.length > 0} fallback={<>画布内暂无图片</>}>
            无匹配图片
          </Show>
        </div>
      </Show>
      <For each={props.items}>
        {(item, idx) => {
          const thumbUrl = () => safeUrl(item.thumb || item.url);
          const isActive = () => idx() === props.activeIdx;
          return (
            <div
              class={`mention-item${isActive() ? ' mention-item-active' : ''}`}
              role="option"
              aria-selected={isActive()}
              onMouseDown={(e) => {
                e.preventDefault(); // 阻止编辑器失焦
              }}
              onClick={() => props.onSelect(item)}
            >
              <Show when={thumbUrl()} fallback={
                <span class="mention-item-placeholder"><FiImage size={18} /></span>
              }>
                <img src={thumbUrl()} alt={item.name} class="mention-item-thumb" />
              </Show>
              <span class="mention-item-name">{item.name}</span>
            </div>
          );
        }}
      </For>
    </div>
  );
}
