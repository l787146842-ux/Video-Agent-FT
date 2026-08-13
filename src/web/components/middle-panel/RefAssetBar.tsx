/**
 * 参考素材横条（从 PromptEditor.tsx 拆出）
 *
 * 缩略图列表 + 分镜绑定元素参考 chips + 「+」添加菜单（本地上传 / 画布）
 * + 拖拽上传 + RefAssetPickerModal + 右侧实时素材计数徽章。
 */
import { For, Show, createEffect, createMemo, createSignal, onCleanup } from 'solid-js';
import { FiImage, FiVideo, FiX, FiMusic, FiLayers, FiUpload } from 'solid-icons/fi';
import { state, studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { safeUrl } from '@/lib/utils';
import { storyboardMediaMap } from '@/lib/prompt-mentions';
import { uploadRefFile } from '@/lib/ref-upload';
import {
  boundAssetTitle, refAssetType, refAssetName, videoThumb,
} from '@/lib/prompt-ref-utils';
import { RefAssetPickerModal, type RefAssetItem } from './RefAssetPickerModal';
import type { DraftRecord } from '@/types';

export function RefAssetBar(props: {
  /** 当前选中草稿记录 */
  rec: () => DraftRecord | undefined;
  /** 当前草稿参考素材 URL 列表 */
  refAssets: () => string[];
  /** 参考素材上限（shot=2 / 其他=5） */
  maxRefs: () => number;
}) {
  const [pickerOpen, setPickerOpen] = createSignal(false);
  const [addMenuOpen, setAddMenuOpen] = createSignal(false);
  let fileInputRef: HTMLInputElement | undefined;
  let audioInputRef: HTMLInputElement | undefined;

  /** +号菜单打开时，点击菜单外部任意位置即关闭 */
  createEffect(() => {
    if (!addMenuOpen()) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target as HTMLElement;
      if (!t.closest('.ref-add-wrap')) setAddMenuOpen(false);
    };
    document.addEventListener('pointerdown', onDown);
    onCleanup(() => document.removeEventListener('pointerdown', onDown));
  });

  /** 右侧计数：参考栏素材 + 提示词中 @ 引用的故事板素材（URL 去重，按类型统计） */
  const refCounts = createMemo(() => {
    const counts: Record<'image' | 'video' | 'audio', number> = { image: 0, video: 0, audio: 0 };
    const seen = new Set<string>();
    for (const url of props.refAssets()) {
      counts[refAssetType(url, state.keyElements)] += 1;
      seen.add(url);
    }
    const prompt = props.rec()?.draft.prompt || '';
    if (prompt.includes('@') || prompt.includes('＠')) {
      const map = storyboardMediaMap();
      const re = /[@＠]([^\s@＠]+)/g;
      let m: RegExpExecArray | null;
      while ((m = re.exec(prompt))) {
        const info = map[m[1]];
        if (!info || seen.has(info.url)) continue;
        seen.add(info.url);
        counts[info.kind] += 1;
      }
    }
    return counts;
  });
  const refTotal = () => refCounts().image + refCounts().video + refCounts().audio;

  /** 添加参考素材（去重 + 上限） */
  function addRefUrl(url: string, name?: string) {
    const r = props.rec();
    if (!r || !url) return;
    const refs = r.draft.refAssets || [];
    if (refs.includes(url)) {
      showToast('该素材已在参考列表中', 'warning');
      return;
    }
    if (refs.length >= props.maxRefs()) {
      showToast(`参考素材最多 ${props.maxRefs()} 个，请先删除再添加`, 'warning');
      return;
    }
    studioActions.updateDraftLocal(r.type, r.draft.id, { refAssets: [...refs, url] });
    showToast(`已添加参考素材${name ? `：${name}` : ''}`, 'success');
  }

  function handlePick(items: RefAssetItem[]) {
    for (const item of items) {
      addRefUrl(item.url, item.name);
    }
  }

  function handleRefUpload(file: File) {
    return uploadRefFile(props.rec(), props.maxRefs(), file)
      .catch((e) => showToast((e as Error).message || '参考素材上传失败', 'error'));
  }

  function removeRef(url: string) {
    const r = props.rec();
    if (!r) return;
    studioActions.updateDraftLocal(r.type, r.draft.id, {
      refAssets: (r.draft.refAssets || []).filter((u) => u !== url),
    });
  }

  function onRefDrop(e: DragEvent) {
    e.preventDefault();
    const file = e.dataTransfer?.files?.[0];
    if (file) void handleRefUpload(file);
  }

  return (
    <>
      {/* 参考素材横条：缩略图 + 添加按钮 + 提示文字，整框接收拖拽 */}
      <div
        class="ref-drop-zone ref-drop-box"
        onDragOver={(e) => e.preventDefault()}
        onDrop={onRefDrop}
      >
        <div class="ref-thumbs flex-wrap">
          {/* 分镜：绑定元素参考（只读 chips，不显示标题文字） */}
          <Show when={state.selectedType === 'shot'}>
            <div class="scene-refs">
              <For each={props.refAssets().filter((u) => boundAssetTitle(u, state.keyElements))}>
                {(url) => (
                  <span class="scene-ref-chip">
                    <img src={safeUrl(url)} alt="" />
                    {boundAssetTitle(url, state.keyElements)}
                  </span>
                )}
              </For>
            </div>
          </Show>

          {/* 自有参考素材（按类型渲染，可删） */}
          <For each={props.refAssets()}>
            {(url, idx) => (
              <div class="ref-thumb-wrap" title={refAssetName(url, idx(), state.keyElements)}>
                <Show when={refAssetType(url, state.keyElements) === 'video'}>
                  <span class="ref-video-wrap">
                    <video src={videoThumb(url)} class="ref-thumb" muted playsinline preload="metadata" />
                    <span class="ref-video-badge">▶</span>
                  </span>
                </Show>
                <Show when={refAssetType(url, state.keyElements) === 'audio'}>
                  <div class="ref-thumb ref-thumb-audio"><FiMusic size={16} /></div>
                </Show>
                <Show when={refAssetType(url, state.keyElements) === 'image'}>
                  <img
                    src={safeUrl(url)}
                    alt={`参考素材 ${idx() + 1}`}
                    class="ref-thumb"
                  />
                </Show>
                <button
                  type="button"
                  class="ref-thumb-remove"
                  title="移除参考素材"
                  onClick={() => removeRef(url)}
                >
                  <FiX size={14} />
                </button>
                {/* 首尾帧功能暂未实现：统一显示“参考”，不标注首帧/尾帧 */}
                <Show when={state.selectedType === 'shot'}>
                  <span class="ref-thumb-badge">参考</span>
                </Show>
              </div>
            )}
          </For>

          {/* 添加按钮（+号菜单：本地上传 / 画布；点击外部关闭） */}
          <Show when={props.refAssets().length < props.maxRefs()}>
            <div class="ref-add-wrap">
              <button
                type="button"
                class="ref-upload-btn"
                title="添加参考素材"
                onClick={() => setAddMenuOpen((v) => !v)}
              >
                +
              </button>
              <Show when={addMenuOpen()}>
                <div class="ref-add-menu">
                  <button
                    type="button"
                    class="ref-add-menu-item"
                    onClick={() => { setAddMenuOpen(false); fileInputRef?.click(); }}
                  >
                    <FiUpload size={13} /> 本地上传
                  </button>
                  <button
                    type="button"
                    class="ref-add-menu-item"
                    onClick={() => { setAddMenuOpen(false); audioInputRef?.click(); }}
                  >
                    <FiMusic size={13} /> 上传音频
                  </button>
                  <button
                    type="button"
                    class="ref-add-menu-item"
                    onClick={() => { setAddMenuOpen(false); setPickerOpen(true); }}
                  >
                    <FiLayers size={13} /> 画布
                  </button>
                </div>
              </Show>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*,video/*,audio/*"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const file = e.currentTarget.files?.[0];
                  if (file) void handleRefUpload(file);
                  e.currentTarget.value = '';
                }}
              />
              <input
                ref={audioInputRef}
                type="file"
                accept="audio/*"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const file = e.currentTarget.files?.[0];
                  if (file) void handleRefUpload(file);
                  e.currentTarget.value = '';
                }}
              />
            </div>
          </Show>
        </div>

        {/* 拖放提示文字 */}
        <div class="ref-drop-hint">
          <FiImage size={16} />
          <span>拖拽/上传素材，或点 + 从画布选取（提示词中按 @ 引用关键元素/分镜/音频素材）</span>
        </div>

        {/* 右侧实时计数：已加载参考素材（含 @ 引用故事板素材） */}
        <div
          class="ref-count-badge"
          title={`已加载参考素材 ${refTotal()} 个（图片 ${refCounts().image} / 视频 ${refCounts().video} / 音频 ${refCounts().audio}，含 @ 引用）`}
        >
          <span class="ref-count-item"><FiImage size={12} />{refCounts().image}</span>
          <span class="ref-count-item"><FiVideo size={12} />{refCounts().video}</span>
          <span class="ref-count-item"><FiMusic size={12} />{refCounts().audio}</span>
        </div>
      </div>

      {/* 参考素材选择弹窗（画布 / 关键元素 / 分镜 / 音频） */}
      <RefAssetPickerModal
        open={pickerOpen()}
        onClose={() => setPickerOpen(false)}
        onPick={handlePick}
      />
    </>
  );
}
