import { For, Show, createEffect } from 'solid-js';
import { FiChevronDown, FiChevronUp, FiImage, FiVideo, FiMusic } from 'solid-icons/fi';
import {
  state, studioActions, findDraftRecord, persistBoard,
} from '@/stores/studio';
import { safeUrl } from '@/lib/utils';
import {
  buildRefAssetMap, renderPromptToDOM, serializeDOMToText,
} from '@/lib/prompt-ref-utils';
import { usePromptMention } from '@/hooks/use-prompt-mention';
import { RefAssetBar } from './RefAssetBar';

/**
 * Prompt 编辑器：折叠/展开 + 参考素材横条（RefAssetBar）
 * + contenteditable 提示词框（@ 引用参考素材，插入为内联缩略块 chip；
 *   提及逻辑见 usePromptMention，DOM/文本互转见 prompt-ref-utils）
 * keyElement：可增删参考素材（≤5）；shot：绑定元素参考（只读 chips）+ 首尾帧（≤2）
 */
export function PromptEditor() {
  const rec = () => findDraftRecord(state.selectedDraftId, state.selectedType) ?? undefined;
  const draft = () => rec()?.draft;
  const collapsed = () => state.isPromptCollapsed;

  let editorRef: HTMLDivElement | undefined;

  const refAssets = () => draft()?.refAssets || [];
  const maxRefs = () => (state.selectedType === 'shot' ? 2 : 5);

  function updatePrompt(value: string) {
    const r = rec();
    if (!r) return;
    studioActions.updateDraftLocal(r.type, r.draft.id, { prompt: value });
  }

  /** 编辑器 DOM → 草稿 prompt（chip 还原为 @名称） */
  function syncPrompt() {
    const el = editorRef;
    if (!el) return;
    updatePrompt(serializeDOMToText(el));
  }

  function persistPrompt() {
    // blur 时立即冲刷防抖保存
    persistBoard();
    persistBoard.flush();
  }

  // ===== @ 提及（拆出 hook） =====
  const mention = usePromptMention({
    editor: () => editorRef,
    rec,
    refAssets,
    maxRefs,
    syncPrompt,
  });

  function handleEditorInput() {
    syncPrompt();
    mention.detectMention();
  }

  // 外部更新（切换草稿 / Agent 写入 / 折叠展开）时，把纯文本重新渲染为缩略块
  createEffect(() => {
    state.selectedDraftId; // 跟踪草稿切换
    collapsed(); // 跟踪折叠展开（重新挂载编辑器）
    const text = draft()?.prompt || '';
    const el = editorRef;
    if (!el) return;
    if (document.activeElement !== el) {
      renderPromptToDOM(el, text, buildRefAssetMap(refAssets(), state.keyElements));
    }
  });

  return (
    <Show when={draft()}>
      <div class="prompt-editor">
        {/* 折叠开关条（旧版 prompt-toggle-bar：线 + 中央箭头钮 + 线） */}
        <div
          class={`prompt-toggle-bar ${collapsed() ? 'collapsed' : ''}`}
          title="收放提示词窗口"
          onClick={() => studioActions.togglePromptCollapse()}
        >
          <div class="prompt-toggle-line" />
          <div class="prompt-toggle-btn">
            {collapsed() ? <FiChevronUp size={13} /> : <FiChevronDown size={13} />}
          </div>
          <div class="prompt-toggle-line" />
        </div>

        <Show when={!collapsed()}>
          <div class="prompt-collapse-area" onScroll={() => { if (mention.mentionActive()) mention.closeMention(); }}>
            {/* 参考素材横条（音频草稿无参考素材概念，不显示） */}
            <Show when={state.selectedType !== 'audio'}>
              <RefAssetBar rec={rec} refAssets={refAssets} maxRefs={maxRefs} />
            </Show>

            {/* 提示词输入框（contenteditable，@ 插入缩略块）+ 提及弹层 */}
            <div class="prompt-textarea-wrap">
              <div
                ref={editorRef}
                class="prompt-textarea prompt-editor-input"
                contentEditable={true}
                role="textbox"
                data-placeholder="Agent 将在此输出推演出的详细提示词…（输入 @ 引用参考素材或故事板媒体）"
                onInput={handleEditorInput}
                onPaste={(e) => {
                  // 粘贴统一转为纯文本，避免富文本格式污染提示词
                  e.preventDefault();
                  const text = e.clipboardData?.getData('text/plain') || '';
                  if (text) document.execCommand('insertText', false, text);
                }}
                onKeyDown={(e) => {
                  if (mention.mentionActive()) {
                    const list = mention.mentionItems();
                    if (e.key === 'ArrowDown') {
                      e.preventDefault();
                      mention.setMentionIdx((i) => (i + 1) % Math.max(1, list.length));
                      return;
                    }
                    if (e.key === 'ArrowUp') {
                      e.preventDefault();
                      mention.setMentionIdx((i) => (i - 1 + list.length) % Math.max(1, list.length));
                      return;
                    }
                    if (e.key === 'Enter' && list.length > 0) {
                      e.preventDefault();
                      const idx = mention.mentionIdx();
                      if (idx >= 0 && idx < list.length) mention.insertMentionChip(list[idx]);
                      return;
                    }
                    if (e.key === 'Escape') {
                      e.preventDefault();
                      mention.closeMention();
                    }
                  }
                }}
                onBlur={() => {
                  persistPrompt();
                  setTimeout(() => {
                    const el = document.activeElement;
                    if (!el || !el.closest('.mention-popup')) mention.closeMention();
                  }, 150);
                }}
              />
              <Show when={mention.mentionActive() && mention.mentionPos()}>
                <div
                  class="mention-popup prompt-mention-popup"
                  role="listbox"
                  aria-label="参考素材选择"
                  style={{
                    position: 'fixed',
                    right: 'auto',
                    bottom: `${mention.mentionPos()!.bottom}px`,
                    left: `${mention.mentionPos()!.left}px`,
                    width: `${mention.mentionPos()!.width}px`,
                  }}
                >
                  <Show when={mention.mentionItems().length === 0}>
                    <div class="mention-popup-status">无匹配的参考素材</div>
                  </Show>
                  <For each={mention.mentionItems()}>
                    {(item, idx) => (
                      <div
                        class={`mention-item${idx() === mention.mentionIdx() ? ' mention-item-active' : ''}`}
                        role="option"
                        aria-selected={idx() === mention.mentionIdx()}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => mention.insertMentionChip(item)}
                      >
                        <Show when={item.type === 'image' && safeUrl(item.url)} fallback={
                          <span class="mention-item-placeholder">
                            {item.type === 'video' ? <FiVideo size={18} /> : item.type === 'audio' ? <FiMusic size={18} /> : <FiImage size={18} />}
                          </span>
                        }>
                          <img src={safeUrl(item.url)} alt={item.name} class="mention-item-thumb" />
                        </Show>
                        <span class="mention-item-name">{item.name}</span>
                      </div>
                    )}
                  </For>
                </div>
              </Show>
            </div>
          </div>
        </Show>
      </div>
    </Show>
  );
}
