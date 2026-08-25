/**
 * 「其它（自定义输入）」按钮 + 组内输入框——自 ConfirmActions 切出。
 * 展开态/文本/单发动作仍由父组件持有（单选互斥语义在父侧），本组件纯渲染。
 */
import { Show } from 'solid-js';
import { t } from '@/lib/locale';

export function ConfirmCustomInput(props: {
  open: () => boolean;
  text: () => string;
  onToggle: (open: boolean) => void;
  onText: (value: string) => void;
  onSend: (text: string) => void;
}) {
  const toggle = (el: HTMLButtonElement) => {
    const open = !props.open();
    props.onToggle(open);
    if (open) {
      // 展开后聚焦组内输入框
      requestAnimationFrame(() => {
        el?.closest('.confirm-wizard')?.querySelector<HTMLTextAreaElement>('.confirm-custom-input')?.focus();
      });
    }
  };

  return (
    <>
      <button
        type="button"
        class={`confirm-btn secondary${props.open() || props.text().trim() ? ' active' : ''}`}
        onClick={(e) => toggle(e.currentTarget)}
      >
        {t('rp.confirm.customBtn')}
      </button>
      <Show when={props.open()}>
        <textarea
          class="confirm-custom-input"
          rows={2}
          placeholder={t('rp.confirm.customPlaceholder')}
          value={props.text()}
          onInput={(e) => props.onText(e.currentTarget.value)}
          onKeyDown={(e) => {
            // Ctrl/Cmd+Enter 快捷发送（普通回车允许换行写多行）
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              props.onSend(props.text().trim());
            }
          }}
        />
      </Show>
    </>
  );
}
