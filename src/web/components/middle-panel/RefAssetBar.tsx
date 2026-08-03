/**
 * 参考素材横条（从 PromptEditor.tsx 拆出）
 *
 * 缩略图列表 + 分镜绑定元素参考 chips + 「+」添加菜单（本地上传 / 故事板选取）
 * + 拖拽上传 + RefAssetPickerModal。
 */
import { For, Show, createSignal } from 'solid-js';
import { FiImage, FiX, FiMusic, FiLayers, FiUpload } from 'solid-icons/fi';
import { state, studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { uploadFiles } from '@/api/upload';
import { safeUrl } from '@/lib/utils';
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

  function handlePick(item: RefAssetItem) {
    addRefUrl(item.url, item.name);
  }

  async function handleRefUpload(file: File) {
    const r = props.rec();
    if (!r) return;
    if ((r.draft.refAssets || []).length >= props.maxRefs()) {
      showToast(`参考素材最多 ${props.maxRefs()} 个，请先删除再上传`, 'warning');
      return;
    }
    try {
      showToast(`正在上传：${file.name}`, 'info');
      const files = await uploadFiles([file]);
      const url = files[0]?.url;
      if (!url) throw new Error('上传接口没有返回素材地址');
      addRefUrl(url, file.name);
    } catch (e) {
      showToast((e as Error).message || '参考素材上传失败', 'error');
    }
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
          {/* 分镜：绑定元素参考（只读 chips） */}
          <Show when={state.selectedType === 'shot'}>
            <div class="scene-refs">
              <span class="scene-refs-label">绑定元素参考:</span>
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
                  <video src={videoThumb(url)} class="ref-thumb" muted playsinline preload="metadata" />
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
                <Show when={state.selectedType === 'shot'}>
                  <span class="ref-thumb-badge">
                    {idx() === 0 ? '首帧' : idx() === 1 ? '尾帧' : '参考'}
                  </span>
                </Show>
              </div>
            )}
          </For>

          {/* 添加按钮（+号菜单：本地上传 / 画布·关键元素） */}
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
                    onClick={() => { setAddMenuOpen(false); setPickerOpen(true); }}
                  >
                    <FiLayers size={13} /> 画布 / 关键元素
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
            </div>
          </Show>
        </div>

        {/* 拖放提示文字 */}
        <div class="ref-drop-hint">
          <FiImage size={16} />
          <span>拖拽/上传素材，或点 + 从故事板/画布选取（提示词中按 @ 引用关键元素/分镜/音频素材）</span>
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
