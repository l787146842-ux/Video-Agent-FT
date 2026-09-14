/**
 * 提示词 @ 提及弹层（从 PromptEditor.tsx 拆出）：
 * 搜索框 + 故事板分类页签（关键元素/分镜/音频）+ 故事板/参考栏双分区网格。
 */
import { For, Show, createSignal } from 'solid-js';
import { FiImage, FiMusic } from 'solid-icons/fi';
import { safeUrl } from '@/lib/utils';
import { videoThumb } from '@/lib/prompt-ref-utils';
import type { MentionItem } from '@/hooks/use-prompt-mention';

/** @面板故事板分类页签 */
const MENTION_CATS: Array<{ id: 'keyElement' | 'shot' | 'audio'; label: string }> = [
  { id: 'keyElement', label: '关键元素' },
  { id: 'shot', label: '分镜' },
  { id: 'audio', label: '音频' },
];

export function PromptMentionPopup(props: {
  /** fixed 定位坐标（锚定光标） */
  pos: { bottom: number; left: number; width: number };
  query: string;
  onQuery: (v: string) => void;
  boardItems: () => MentionItem[];
  refItems: () => MentionItem[];
  /** 键盘导航当前高亮项判定 */
  isActive: (item: MentionItem) => boolean;
  onPick: (item: MentionItem) => void;
  /** 隐藏「参考栏素材」分区（分镜正文编辑器无参考栏概念） */
  hideRefSection?: boolean;
}) {
  /** @面板故事板分类当前页签 */
  const [cat, setCat] = createSignal<'keyElement' | 'shot' | 'audio'>('keyElement');
  const filteredBoard = () => props.boardItems().filter((i) => i.category === cat());

  /** 候选条目：图片缩略图 / 视频首帧 / 音频图标 */
  function renderItem(item: MentionItem) {
    return (
      <div
        class={`mention-item${props.isActive(item) ? ' mention-item-active' : ''}`}
        role="option"
        aria-selected={props.isActive(item)}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => props.onPick(item)}
      >
        <Show when={item.type === 'image' && safeUrl(item.url)} fallback={
          <Show when={item.type === 'video' && safeUrl(item.url)} fallback={
            <span class="mention-item-placeholder">
              {item.type === 'audio' ? <FiMusic size={18} /> : <FiImage size={18} />}
            </span>
          }>
            <span class="mention-thumb-wrap">
              <video src={videoThumb(item.url)} muted playsinline preload="metadata" class="mention-item-thumb" />
              <span class="mention-video-badge">▶</span>
            </span>
          </Show>
        }>
          <img src={safeUrl(item.url)} alt={item.name} class="mention-item-thumb" />
        </Show>
        <span class="mention-item-name">{item.name}</span>
      </div>
    );
  }

  return (
    <div
      class="mention-popup prompt-mention-popup"
      role="listbox"
      aria-label="参考素材选择"
      style={{
        position: 'fixed',
        right: 'auto',
        bottom: `${props.pos.bottom}px`,
        left: `${props.pos.left}px`,
        width: `${props.pos.width}px`,
      }}
    >
      {/* 搜索框：过滤故事板素材与参考栏素材 */}
      <input
        class="mention-search"
        placeholder="搜索素材..."
        value={props.query}
        onInput={(e) => props.onQuery(e.currentTarget.value)}
      />
      {/* 上区：故事板素材（分类页签） */}
      <div class="mention-tabs">
        <For each={MENTION_CATS}>
          {(c) => (
            <button
              type="button"
              class={`mention-tab ${cat() === c.id ? 'active' : ''}`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => setCat(c.id)}
            >
              {c.label}
            </button>
          )}
        </For>
      </div>
      <div class="mention-section">
        <For each={filteredBoard()}>
          {(item) => renderItem(item)}
        </For>
        <Show when={filteredBoard().length === 0}>
          <div class="mention-popup-status">该分类暂无故事板素材</div>
        </Show>
      </div>
      {/* 下区：中间预览框参考栏素材（分镜正文编辑器隐藏） */}
      <Show when={!props.hideRefSection}>
        <div class="mention-section-title">参考栏素材</div>
        <div class="mention-section">
          <For each={props.refItems()}>
            {(item) => renderItem(item)}
          </For>
          <Show when={props.refItems().length === 0}>
            <div class="mention-popup-status">参考栏暂无素材</div>
          </Show>
        </div>
      </Show>
    </div>
  );
}
