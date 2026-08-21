import { createSignal, Show } from 'solid-js';
import { state, studioActions } from '@/stores/studio';
import { sendUserMessage } from '@/lib/agent-actions';
import { stopAgentStream } from '@/hooks/use-sse';
import { uploadAndInsert, handleUrlDrop } from '@/lib/chat-input-media';
import { useChatEditor } from '@/lib/chat-editor';
import { startQueuedAutosend } from '@/lib/chat-queue-autosend';
import { t } from '@/lib/locale';
import { agentSkill } from '@/stores/agent-prefs';
import { openDocsPanel } from '@/stores/docs';
import { ChatInputToolbar } from './ChatInputToolbar';
import { ChatInputEditor } from './ChatInputEditor';
import { PendingAttachmentBar } from './PendingAttachmentBar';
import { QueuedMessagesBar } from './QueuedMessagesBar';
import { MediaLightbox } from './MediaLightbox';

/**
 * 聊天输入区（富文本版）：
 * contenteditable 编辑器支持文字与「内联缩略块」自由混排——左栏卡片右击
 * 「添加到对话」、@ 提及、粘贴、拖拽、上传的媒体都以缩略块插入到光标处，
 * 发送时序列化为有序 parts，让 LLM 精确识别文字与媒体的对应关系。
 *
 * P4-23 结构清欠三分：编辑区（ChatInputEditor + lib/chat-editor）、
 * 排队区（QueuedMessagesBar + lib/chat-queue-autosend）、粘贴拖拽（lib/chat-input-media），
 * 本文件只留组装与拖拽摄取入口，DOM 结构不变。
 */
export function ChatInput() {
  const [dragOver, setDragOver] = createSignal(false);
  /** 双击缩略块放大预览（url + 类型） */
  const [preview, setPreview] = createSignal<{ url: string; kind: string } | null>(null);
  let fileInputRef: HTMLInputElement | undefined;

  const ed = useChatEditor();

  // 排队自动出队（lib/chat-queue-autosend）：Agent 空闲即按序发队首消息
  startQueuedAutosend();

  /** 序列化编辑器并发送；成功后清空 */
  function doSend() {
    const parts = ed.serializeParts();
    if (parts.length === 0 && state.pendingAttachments.length === 0) return;
    void sendUserMessage(parts).then((ok) => {
      if (!ok) return;
      ed.clearEditor();
    });
  }

  function onKeyDown(e: KeyboardEvent) {
    // @ 菜单键盘导航（消费后不再走发送逻辑）
    if (ed.handleMentionKeys(e)) return;
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
    <div class="chat-input-area">
      <div
        class={`chat-input-box ${dragOver() ? 'drag-over' : ''}`}
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
          if (handleUrlDrop(dt, ed.insertMedia)) return;
          Array.from(dt.files || []).forEach((f) => void uploadAndInsert(f, ed.insertMedia));
        }}
      >
        <QueuedMessagesBar onEdit={ed.backfillText} />

        <PendingAttachmentBar />

        <ChatInputEditor editor={ed} onKeyDown={onKeyDown} onPreview={setPreview} />

        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="image/*,video/*,audio/*,.md,.txt"
          class="hidden"
          onChange={(e) => {
            Array.from(e.currentTarget.files || []).forEach((f) => void uploadAndInsert(f, ed.insertMedia));
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
