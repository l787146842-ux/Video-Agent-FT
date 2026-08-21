/**
 * 聊天输入编辑区（P4-23 结构清欠从 ChatInput 拆出）：
 * contenteditable 编辑器 + @ 提及弹层。DOM 结构不变——
 * #chatInputTextarea / .rich-chat-input / .mention-popup 等选择器原样保留。
 * 编辑器逻辑（光标记忆/桥接插入/回填/序列化）由 lib/chat-editor 的 useChatEditor 提供，
 * 父组件创建后整体传入，保证发送与排队回填仍可触达同一编辑器实例。
 */
import { Show } from 'solid-js';
import { t } from '@/lib/locale';
import { handlePasteImages } from '@/lib/chat-input-media';
import type { useChatEditor } from '@/lib/chat-editor';
import type { CanvasNodeImageItem } from '@/api/canvas';
import { MentionPopup } from './MentionPopup';

export function ChatInputEditor(props: {
  editor: ReturnType<typeof useChatEditor>;
  onKeyDown: (e: KeyboardEvent) => void;
  /** 双击缩略块放大预览（url + 类型） */
  onPreview: (p: { url: string; kind: string }) => void;
}) {
  const ed = () => props.editor;

  return (
    <>
      {/* 富文本编辑器（contenteditable，文字与缩略块混排；推理中仍可输入，发送进排队） */}
      <div
        id="chatInputTextarea"
        ref={ed().setEditor}
        class="rich-chat-input"
        contentEditable
        role="textbox"
        aria-label={t('rp.input.aria')}
        data-placeholder={t('rp.input.placeholder')}
        onInput={ed().handleInput}
        onKeyDown={props.onKeyDown}
        onDblClick={(e) => {
          const p = ed().handleChipDblClick(e);
          if (p) props.onPreview(p);
        }}
        onPaste={(e) => void handlePasteImages(e, ed().insertMedia)}
        onBlur={() => {
          // 点击弹出菜单的 item 会先触发 onBlur → 延迟关闭，让 onClick 先执行
          setTimeout(() => {
            const el = document.activeElement;
            if (!el || !el.closest('.mention-popup')) ed().mention.closeMention();
          }, 150);
        }}
      />
      <Show when={ed().mention.mentionActive()}>
        <MentionPopup
          loading={ed().mention.canvasNodeImages.loading}
          canvasOnline={ed().mention.canvasNodeImages()?.canvas_online}
          items={ed().mention.mentionItems()}
          activeIdx={ed().mention.mentionIdx()}
          query={ed().mention.mentionQuery()}
          onSelect={(item: CanvasNodeImageItem) => ed().selectMentionItem(item)}
        />
      </Show>
    </>
  );
}
