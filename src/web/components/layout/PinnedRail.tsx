import { For, Show } from 'solid-js';
import {
  FiBookmark, FiFileText, FiImage, FiVideo, FiX, FiTrash2,
} from 'solid-icons/fi';
import {
  pinned, activeId, setActivePinned, unpinArtifact, clearAllPinned,
  PINNED_MAX, type PinnedArtifact,
} from '@/stores/pinned';
import { state } from '@/stores/studio';
import { renderMarkdown } from '@/lib/markdown';
import { handleCodeBlockClick } from '@/lib/code-copy';
import { safeUrl } from '@/lib/utils';

/**
 * 钉住侧栏（F3）：跨轮对照钉住的产物预览分栏。
 *
 * 职责划分（三者不合并）：
 * - middle-panel MediaViewer = 生成工作区预览（跟随故事板选中草稿，单产物）；
 * - Lightbox（统一预览灯箱） = 临时全屏查看（Esc 即走，不留驻）；
 * - PinnedRail（本组件）= 跨轮对照钉住（≤3 个产物并置，会话内常驻）。
 *
 * 内存纪律：仅激活项挂载媒体 src（图片 loading=lazy、视频 preload=none）；
 * 非激活项卸载 src，仅渲染 kind 图标 + 文件名的元数据行。
 * 文档预览复用项目 markdown 渲染器（renderMarkdown，与 DocsPanel 同源），
 * 正文从 studio state.documents 现读 —— 文档被更新后钉住预览同步最新。
 */

/** kind → 图标 */
function KindIcon(props: { kind: PinnedArtifact['kind'] }) {
  return (
    <Show
      when={props.kind === 'image'}
      fallback={
        <Show when={props.kind === 'video'} fallback={<FiFileText size={13} />}>
          <FiVideo size={13} />
        </Show>
      }
    >
      <FiImage size={13} />
    </Show>
  );
}

/** 激活项的文档预览：markdown 渲染；文档已被删除时给降级提示 */
function PinnedDocPreview(props: { name: string }) {
  const content = () =>
    (state.documents || []).find((d) => d.name === props.name)?.content || '';
  return (
    <Show
      when={content()}
      fallback={<div class="pinned-preview-empty">文档「{props.name}」不存在或已被删除</div>}
    >
      {/* chat-markdown 类复用对话区 markdown 排版 token（tokens.css @layer base） */}
      <div
        class="pinned-doc chat-markdown"
        innerHTML={renderMarkdown(content())}
        onClick={handleCodeBlockClick}
      />
    </Show>
  );
}

/** 激活项预览：按 kind 分发（doc→markdown / image→lazy img / video→preload=none） */
function PinnedPreview(props: { item: PinnedArtifact }) {
  return (
    <Show
      when={props.item.kind === 'doc'}
      fallback={
        <Show when={props.item.kind === 'video'} fallback={
          <img
            class="pinned-preview-img"
            src={safeUrl((props.item as Extract<PinnedArtifact, { kind: 'image' }>).url)}
            alt={props.item.name}
            loading="lazy"
          />
        }>
          <video
            class="pinned-preview-video"
            src={safeUrl((props.item as Extract<PinnedArtifact, { kind: 'video' }>).url)}
            poster={(props.item as Extract<PinnedArtifact, { kind: 'video' }>).thumb
              ? safeUrl((props.item as Extract<PinnedArtifact, { kind: 'video' }>).thumb!)
              : undefined}
            preload="none"
            controls
            muted
            playsinline
          />
        </Show>
      }
    >
      <PinnedDocPreview name={props.item.name} />
    </Show>
  );
}

export function PinnedRail() {
  const active = () => pinned().find((p) => p.id === activeId());
  return (
    <div class="pinned-rail">
      <div class="pinned-rail-header">
        <FiBookmark size={14} class="pinned-rail-header-icon" />
        <span class="pinned-rail-title">钉住对照</span>
        <span class="pinned-rail-count">{pinned().length}/{PINNED_MAX}</span>
        <button
          type="button"
          class="pinned-rail-clear"
          title="清空钉住栏"
          onClick={clearAllPinned}
        >
          <FiTrash2 size={12} />
        </button>
      </div>

      {/* 元数据列表：非激活项不挂媒体 src，仅图标+文件名（防内存膨胀） */}
      <div class="pinned-rail-list">
        <For each={pinned()}>
          {(item) => (
            <div
              class="pinned-item"
              classList={{ active: item.id === activeId() }}
              role="button"
              tabIndex={0}
              title={item.name}
              onClick={() => setActivePinned(item.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  setActivePinned(item.id);
                }
              }}
            >
              <KindIcon kind={item.kind} />
              <span class="pinned-item-name">{item.name}</span>
              <button
                type="button"
                class="pinned-item-unpin"
                title="取消钉住"
                onClick={(e) => {
                  e.stopPropagation();
                  unpinArtifact(item.id);
                }}
              >
                <FiX size={12} />
              </button>
            </div>
          )}
        </For>
      </div>

      {/* 激活项预览区 */}
      <div class="pinned-rail-preview">
        <Show
          when={active()}
          keyed
          fallback={<div class="pinned-preview-empty">钉住产物后在此对照查看</div>}
        >
          {(item) => <PinnedPreview item={item} />}
        </Show>
      </div>
    </div>
  );
}
