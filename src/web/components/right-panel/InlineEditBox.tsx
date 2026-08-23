/**
 * 原地编辑框（任务 #17：最后一条用户消息「编辑」的唯一形态）。
 *
 * 点击编辑后该用户消息原地变为编辑框：多行 textarea + 框内右下
 * 取消/发送按钮。发送 = 截断重答（POST /chat/truncate-resend {text}），
 * 由父组件 onSubmit 承接（返回 false 时编辑框保持打开不丢草稿）。
 * 键盘：Enter 发送 / Shift+Enter 换行 / Esc 取消（IME 组合期不触发）。
 */
import { createSignal, onMount } from 'solid-js';
import { t } from '@/lib/locale';

export function InlineEditBox(props: {
  /** 原消息正文（预填） */
  initial: string;
  onCancel: () => void;
  /** 返回 true = 受理成功（父组件关闭编辑框）；false = 保持打开 */
  onSubmit: (text: string) => Promise<boolean> | boolean;
}) {
  let taRef: HTMLTextAreaElement | undefined;
  const [sending, setSending] = createSignal(false);

  onMount(() => {
    taRef?.focus();
    // 光标置尾（预填全文后继续输入的自然位）
    const len = taRef?.value.length ?? 0;
    taRef?.setSelectionRange(len, len);
  });

  async function send() {
    const text = (taRef?.value || '').trim();
    if (!text || sending()) return;
    setSending(true);
    try {
      await props.onSubmit(text);
    } finally {
      setSending(false);
    }
  }

  function onKeyDown(e: KeyboardEvent & { currentTarget: HTMLTextAreaElement }) {
    if (e.key === 'Escape') {
      e.preventDefault();
      if (!sending()) props.onCancel();
      return;
    }
    // IME 组合输入保护（与主输入框同口径）
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      void send();
    }
  }

  return (
    <div class="inline-edit-box" data-testid="inline-edit-box">
      <textarea
        ref={taRef}
        class="inline-edit-textarea"
        rows={3}
        value={props.initial}
        onKeyDown={onKeyDown}
        aria-label={t('rp.msg.edit')}
        disabled={sending()}
      />
      <div class="inline-edit-footer">
        <button
          type="button"
          class="inline-edit-cancel"
          data-testid="inline-edit-cancel"
          onClick={() => props.onCancel()}
          disabled={sending()}
        >
          {t('rp.msg.editCancel')}
        </button>
        <button
          type="button"
          class="inline-edit-send"
          data-testid="inline-edit-send"
          onClick={() => void send()}
          disabled={sending()}
        >
          {t('rp.msg.editSend')}
        </button>
      </div>
    </div>
  );
}
