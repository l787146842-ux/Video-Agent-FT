import { Show, createEffect, createSignal } from 'solid-js';
import { FiChevronDown, FiChevronUp } from 'solid-icons/fi';
import {
  state, setState, studioActions, findDraftRecord, persistBoard,
} from '@/stores/studio';
import {
  buildRefAssetMap, renderPromptToDOM, serializeDOMToText,
} from '@/lib/prompt-ref-utils';
import { usePromptMention, type MentionItem } from '@/hooks/use-prompt-mention';
import { usePromptMediaDrop } from '@/hooks/use-prompt-media-drop';
import { Lightbox } from '@/components/Lightbox';
import { RefAssetBar } from './RefAssetBar';
import { PromptMentionPopup } from './PromptMentionPopup';
import { promptEditorKeyDown } from './prompt-editor-keys';

/**
 * Prompt 编辑器：折叠/展开 + 参考素材横条（RefAssetBar）
 * + contenteditable 提示词框（@ 引用参考素材，插入为内联缩略块 chip；
 *   提及逻辑见 usePromptMention，粘贴/拖入媒体见 usePromptMediaDrop，
 *   @ 弹层见 PromptMentionPopup，DOM/文本互转见 prompt-ref-utils）
 * keyElement：可增删参考素材（≤5）；shot：绑定元素参考（只读 chips）+ 首尾帧（不设上限）
 */
export function PromptEditor() {
  const rec = () => findDraftRecord(state.selectedDraftId, state.selectedType) ?? undefined;
  const draft = () => rec()?.draft;
  const collapsed = () => state.isPromptCollapsed;

  let editorRef: HTMLDivElement | undefined;
  /** 编辑器当前已渲染的草稿 id（识别“草稿切换”，保证切换后必刷新内容） */
  let renderedDraftId = '';

  /** 把当前选中草稿的提示词渲染进指定编辑器（@引用 chip 化） */
  function renderInto(el: HTMLElement) {
    const text = draft()?.prompt || '';
    renderPromptToDOM(el, text, buildRefAssetMap(refAssets(), state.keyElements));
  }

  /** 回调用 ref：编辑器节点挂载/重新挂载（草稿切换、折叠展开、项目切换）时
   * 立即渲染内容，消除“渲染 effect 与节点重建时序竞争”导致提示词不显示、
   * 刷新页面才恢复的问题。 */
  function attachEditor(el: HTMLDivElement) {
    editorRef = el;
    renderedDraftId = state.selectedDraftId;
    if (document.activeElement !== el) renderInto(el);
  }

  /** 点击 @ 缩略块放大预览（url + 类型） */
  const [preview, setPreview] = createSignal<{ url: string; kind: string } | null>(null);

  /** 点击编辑器内的 @ 缩略块（图片/视频/音频）→ 灯箱放大查看 */
  function handleChipClick(e: MouseEvent) {
    const chip = (e.target as HTMLElement).closest('.mention-chip') as HTMLElement | null;
    if (!chip) return;
    const url = chip.dataset.url || '';
    if (!url) return;
    e.preventDefault();
    setPreview({ url, kind: chip.dataset.kind || 'image' });
  }

  const refAssets = () => draft()?.refAssets || [];
  /** 参考素材上限：keyElement≤5；shot 不设上限（用户决策） */
  const maxRefs = () => (state.selectedType === 'shot' ? Infinity : 5);

  /** 粘贴/拖入媒体文件进参考素材栏（高亮态 + 上传） */
  const drop = usePromptMediaDrop({ rec, maxRefs });

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

  /** 键盘导航当前高亮项判定（供 @ 弹层渲染 active 态） */
  const isMentionActive = (item: MentionItem) => {
    const cur = mention.mentionItems()[mention.mentionIdx()];
    return !!cur && cur.url === item.url && cur.name === item.name;
  };

  function handleEditorInput() {
    syncPrompt();
    mention.detectMention();
  }

  // 外部更新（切换草稿 / Agent 写入 / 折叠展开）时，把纯文本重新渲染为缩略块
  createEffect(() => {
    const id = state.selectedDraftId; // 跟踪草稿切换
    collapsed(); // 跟踪折叠展开（重新挂载编辑器）
    const storePrompt = draft()?.prompt; // 跟踪提示词外部更新（Agent 写回等）
    const el = editorRef;
    // 未挂载/已脱离文档：重新挂载时回调 ref 会负责渲染，这里不处理
    if (!el || !el.isConnected) return;
    const draftChanged = id !== renderedDraftId;
    renderedDraftId = id;
    if (document.activeElement === el) {
      if (!draftChanged) {
        // 同草稿编辑中：store 值与编辑器内容一致（自己输入的回声）则跳过，不打断输入；
        // 不一致说明被外部覆盖（Agent done 快照/撤销重做），失焦后按最新值渲染
        if (serializeDOMToText(el) === (storePrompt || '')) return;
      }
      // 切到别的草稿/项目/被外部覆盖：先失焦（避免旧内容被后续输入写进新草稿），再渲染新内容
      el.blur();
    }
    renderInto(el);
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

            {/* 提示词输入框（contenteditable，@ 插入缩略块；粘贴/拖入媒体进参考栏）+ 提及弹层 */}
            <div class={`prompt-textarea-wrap${drop.dragOver() ? ' drag-over' : ''}`}>
              <div
                ref={attachEditor}
                class="prompt-textarea prompt-editor-input"
                contentEditable={true}
                role="textbox"
                data-placeholder="Agent 将在此输出推演出的详细提示词…（输入 @ 引用参考素材或故事板媒体）"
                onInput={handleEditorInput}
                onFocus={() => setState('editingDraftId', state.selectedDraftId)}
                onClick={handleChipClick}
                onPaste={(e) => {
                  // 粘贴媒体文件（截图/复制的视频音频等）→ 上传进参考素材栏，不插入提示词
                  const files = drop.handlePaste(e);
                  if (files.length) {
                    void drop.addFiles(files);
                    return;
                  }
                  // 粘贴统一转为纯文本，避免富文本格式污染提示词
                  e.preventDefault();
                  const text = e.clipboardData?.getData('text/plain') || '';
                  if (text) document.execCommand('insertText', false, text);
                }}
                onDragOver={(e) => drop.onDragOver(e)}
                onDragLeave={() => drop.onDragLeave()}
                onDrop={(e) => {
                  const files = drop.onDrop(e);
                  if (files.length) void drop.addFiles(files);
                }}
                onKeyDown={(e) => promptEditorKeyDown(e, mention, syncPrompt)}
                onBlur={() => {
                  setState('editingDraftId', '');
                  persistPrompt();
                  setTimeout(() => {
                    const el = document.activeElement;
                    if (!el || !el.closest('.mention-popup')) mention.closeMention();
                  }, 150);
                }}
              />
              <Show when={mention.mentionActive() && mention.mentionPos()}>
                <PromptMentionPopup
                  pos={mention.mentionPos()!}
                  query={mention.mentionQuery()}
                  onQuery={mention.setMentionQuery}
                  boardItems={mention.boardItems}
                  refItems={mention.refItems}
                  isActive={isMentionActive}
                  onPick={(item) => mention.insertMentionChip(item)}
                />
              </Show>
            </div>
          </div>
        </Show>

        {/* @ 缩略块点击放大预览 */}
        <Show when={preview()}>
          <Lightbox
            mode="media"
            url={preview()!.url}
            kind={preview()!.kind}
            onClose={() => setPreview(null)}
          />
        </Show>
      </div>
    </Show>
  );
}
