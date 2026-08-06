import { createSignal, createEffect, Show, onMount, onCleanup } from 'solid-js';
import { state, studioActions } from '@/stores/studio';
import { chatState, chatActions } from '@/stores/chat';
import { showToast } from '@/stores/toast';
import { sendUserMessage } from '@/lib/agent-actions';
import { stopAgentStream } from '@/hooks/use-sse';
import { uid } from '@/lib/utils';
import {
  createMediaChip, createSkillChip, insertNodeAtCursor, insertTextAtCursor,
  serializeEditorToParts, editorToPlainText, getEditorSelection,
} from '@/lib/rich-input';
import { uploadAndInsert, handlePasteImages, handleUrlDrop } from '@/lib/chat-input-media';
import { insertRequestCount, takeInsertRequests } from '@/lib/chat-input-bridge';
import { t } from '@/lib/locale';
import { agentSkill, agentProvider, agentModel } from '@/stores/agent-prefs';
import { openDocsPanel } from '@/stores/docs';
import { useCanvasMention } from '@/hooks/use-canvas-mention';
import { ChatInputToolbar } from './ChatInputToolbar';
import { MentionPopup } from './MentionPopup';
import { PendingAttachmentBar } from './PendingAttachmentBar';
import { QueuedMessagesBar } from './QueuedMessagesBar';
import { MediaLightbox } from './MediaLightbox';
import type { CanvasNodeImageItem } from '@/api/canvas';
import type { InlineMedia } from '@/types';

/**
 * 聊天输入区（富文本版）：
 * contenteditable 编辑器支持文字与「内联缩略块」自由混排——左栏卡片右击
 * 「添加到对话」、@ 提及、粘贴、拖拽、上传的媒体都以缩略块插入到光标处，
 * 发送时序列化为有序 parts，让 LLM 精确识别文字与媒体的对应关系。
 */
export function ChatInput() {
  const [dragOver, setDragOver] = createSignal(false);
  /** 双击缩略块放大预览（url + 类型） */
  const [preview, setPreview] = createSignal<{ url: string; kind: string } | null>(null);
  let fileInputRef: HTMLInputElement | undefined;
  let editorRef: HTMLDivElement | undefined;
  /** 记忆的编辑器内光标（失焦后右击卡片插入时恢复，保证插在光标处而非开头） */
  let savedRange: Range | null = null;

  const mention = useCanvasMention();

  /** 持续记录编辑器内的光标位置（selectionchange 全局监听） */
  function captureSelection() {
    const el = editorRef;
    if (!el) return;
    const r = getEditorSelection(el);
    if (r) savedRange = r;
  }
  onMount(() => document.addEventListener('selectionchange', captureSelection));
  onCleanup(() => document.removeEventListener('selectionchange', captureSelection));

  /** 插入一个内联媒体缩略块到当前光标处，并同步纯文本状态 */
  function insertMedia(media: InlineMedia) {
    const el = editorRef;
    if (!el) return;
    insertNodeAtCursor(el, createMediaChip(media), savedRange);
    chatActions.setInput(editorToPlainText(el));
  }

  /**
   * 消费左栏卡片右击 / Skill 下拉「+」发来的插入请求：
   * 媒体 → 缩略块，Skill → 引用块（图标+名称），文本 → 直接插入，
   * 均落在记忆的光标处（无光标时追加到末尾）。
   */
  createEffect(() => {
    if (insertRequestCount() === 0) return;
    const reqs = takeInsertRequests();
    const el = editorRef;
    if (!el || reqs.length === 0) return;
    for (const req of reqs) {
      if (req.kind === 'media') {
        insertNodeAtCursor(el, createMediaChip(req.media), savedRange);
      } else if (req.kind === 'skill') {
        // 同名 Skill 块已存在时不重复插入
        const exists = Array.from(el.querySelectorAll('.skill-chip'))
          .some((n) => (n as HTMLElement).dataset.skillName === req.name);
        if (!exists) insertNodeAtCursor(el, createSkillChip(req.name), savedRange);
      } else {
        insertTextAtCursor(el, req.text, savedRange);
      }
    }
    chatActions.setInput(editorToPlainText(el));
  });

  /** 双击缩略块：图片/视频放大预览（音频无画面，不处理） */
  function handleChipDblClick(e: MouseEvent) {
    const chip = (e.target as HTMLElement).closest('.inline-media') as HTMLElement | null;
    if (!chip) return;
    const url = chip.dataset.url || '';
    const kind = chip.dataset.kind || 'image';
    if (url && kind !== 'audio') setPreview({ url, kind });
  }

  /** 选中一个 @ 图片：把光标处的 @query 替换为内联缩略块 */
  function selectMentionItem(item: CanvasNodeImageItem) {
    const el = editorRef;
    const sel = window.getSelection();
    if (!el || !sel || !sel.rangeCount) { mention.closeMention(); return; }
    const range = sel.getRangeAt(0);
    const node = range.startContainer;
    const offset = range.startOffset;
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.nodeValue || '';
      const before = text.slice(0, offset);
      const m = /@[^\s@]*$/.exec(before);
      if (m && node.parentNode) {
        node.nodeValue = before.slice(0, before.length - m[0].length);
        const afterText = text.slice(offset);
        const chip = createMediaChip({
          id: uid('im'), name: item.name, url: item.url,
          kind: 'image', thumb: item.thumb || item.url,
        });
        const space = document.createTextNode('\u00a0');
        const parent = node.parentNode;
        parent.insertBefore(chip, node.nextSibling);
        parent.insertBefore(space, chip.nextSibling);
        if (afterText) parent.insertBefore(document.createTextNode(afterText), space.nextSibling);
        const nr = document.createRange();
        nr.setStartAfter(space);
        nr.collapse(true);
        sel.removeAllRanges();
        sel.addRange(nr);
      }
    }
    mention.closeMention();
    chatActions.setInput(editorToPlainText(el));
    showToast(t('rp.input.added', { name: item.name }), 'success');
  }

  function handleInput() {
    const el = editorRef;
    if (!el) return;
    chatActions.setInput(editorToPlainText(el));
    mention.detectMention();
  }

  /** 排队消息「编辑」：文本追加回填输入框（换行分隔，不冲掉正在输入的内容） */
  function handleEditQueued(text: string) {
    const el = editorRef;
    if (!el || !text) return;
    insertTextAtCursor(el, (el.textContent ? '\n' : '') + text, savedRange);
    chatActions.setInput(editorToPlainText(el));
    el.focus();
  }

  // 排队自动出队：Agent 一空闲就把队首引导消息按序发出（未选供应商时留在队里不丢）
  createEffect(() => {
    if (state.agentBusy) return;
    if (!agentProvider() || !agentModel()) return;
    const q = chatState.queuedMessages;
    if (!q.length) return;
    const first = q[0];
    chatActions.removeQueuedMessage(first.id);
    void sendUserMessage(first.parts.length ? first.parts : first.text);
  });

  /** 序列化编辑器并发送；成功后清空 */
  function doSend() {
    const el = editorRef;
    if (!el) return;
    const parts = serializeEditorToParts(el);
    if (parts.length === 0 && state.pendingAttachments.length === 0) return;
    void sendUserMessage(parts).then((ok) => {
      if (!ok) return;
      el.innerHTML = '';
      chatActions.setInput('');
    });
  }

  function onKeyDown(e: KeyboardEvent) {
    // @ 菜单键盘导航
    if (mention.mentionActive()) {
      const items = mention.mentionItems();
      if (e.key === 'ArrowDown') { e.preventDefault(); mention.setMentionIdx((i) => (i + 1) % items.length); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); mention.setMentionIdx((i) => (i - 1 + items.length) % items.length); return; }
      if (e.key === 'Enter' && items.length > 0) {
        e.preventDefault();
        const idx = mention.mentionIdx();
        if (idx >= 0 && idx < items.length) selectMentionItem(items[idx]);
        return;
      }
      if (e.key === 'Escape') { e.preventDefault(); mention.closeMention(); return; }
    }
    // 中文输入法选词期间的 Enter 不触发发送
    if (e.isComposing || e.keyCode === 229) return;
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      doSend();
    }
  }

  /** 查看当前 Skill 流程文档 */
  function viewCurrentSkillDoc() {
    const sk = agentSkill();
    void openDocsPanel(sk?.id?.startsWith('doc:') ? sk.id.slice(4) : undefined);
  }

  const busy = () => state.agentBusy;

  return (
    <div class="chat-input-area h-full">
      <div
        class={`chat-input-box h-full min-h-0 ${dragOver() ? 'drag-over' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={(e) => {
          e.preventDefault();
          if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const dt = e.dataTransfer;
          if (!dt) return;
          if (handleUrlDrop(dt, insertMedia)) return;
          Array.from(dt.files || []).forEach((f) => void uploadAndInsert(f, insertMedia));
        }}
      >
        <QueuedMessagesBar onEdit={handleEditQueued} />

        <PendingAttachmentBar />

        {/* 富文本编辑器（contenteditable，文字与缩略块混排；推理中仍可输入，发送进排队） */}
        <div
          id="chatInputTextarea"
          ref={editorRef}
          class="rich-chat-input"
          contentEditable
          role="textbox"
          aria-label={t('rp.input.aria')}
          data-placeholder={t('rp.input.placeholder')}
          onInput={handleInput}
          onKeyDown={onKeyDown}
          onDblClick={handleChipDblClick}
          onPaste={(e) => void handlePasteImages(e, insertMedia)}
          onBlur={() => {
            // 点击弹出菜单的 item 会先触发 onBlur → 延迟关闭，让 onClick 先执行
            setTimeout(() => {
              const el = document.activeElement;
              if (!el || !el.closest('.mention-popup')) mention.closeMention();
            }, 150);
          }}
        />
        <Show when={mention.mentionActive()}>
          <MentionPopup
            loading={mention.canvasNodeImages.loading}
            canvasOnline={mention.canvasNodeImages()?.canvas_online}
            items={mention.mentionItems()}
            activeIdx={mention.mentionIdx()}
            query={mention.mentionQuery()}
            onSelect={selectMentionItem}
          />
        </Show>

        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="image/*,video/*,audio/*,.md,.txt"
          class="hidden"
          onChange={(e) => {
            Array.from(e.currentTarget.files || []).forEach((f) => void uploadAndInsert(f, insertMedia));
            e.currentTarget.value = '';
          }}
        />

        <ChatInputToolbar
          busy={busy()}
          onUpload={() => fileInputRef?.click()}
          onSend={doSend}
          onStop={stopAgentStream}
          onOpenCanvas={() => studioActions.openAssetLibrary()}
          onViewSkillDoc={viewCurrentSkillDoc}
        />
      </div>

      {/* 双击缩略块放大预览原图/原视频 */}
      <Show when={preview()}>
        <MediaLightbox
          url={preview()!.url}
          kind={preview()!.kind}
          onClose={() => setPreview(null)}
        />
      </Show>
    </div>
  );
}
