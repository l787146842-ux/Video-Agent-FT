/**
 * 已回应暂停卡的「当时所选」只读标注（回看对勾）——从 ChatMessageItem 抽出，
 * 消息条目组件专注气泡/工具条挂载（任务 #17 红线瘦身）。
 */
import { For, Show } from 'solid-js';
import { FiCheckCircle } from 'solid-icons/fi';
import { t } from '@/lib/locale';

/** 确认卡候选项（与 ChatMessage.confirmOptions 元素同形） */
export interface ConfirmOption {
  label: string;
  description?: string;
  group?: string;
  value?: string;
}

export function AnsweredOptions(props: {
  options: ConfirmOption[];
  answeredValue: string;
}) {
  return (
    <div class="answered-options">
      <For each={props.options}>
        {(opt) => {
          const lines = (props.answeredValue || '')
            .split('\n').map((s) => s.trim()).filter(Boolean);
          const chosen = () =>
            opt.value === props.answeredValue || opt.label === props.answeredValue
            || lines.includes(opt.value ?? '') || lines.includes(opt.label ?? '');
          return (
            <span class={`answered-option${chosen() ? ' chosen' : ''}`}>
              <Show when={chosen()}>
                <FiCheckCircle size={12} class="answered-option-check" />
              </Show>
              {opt.label}
              <Show when={chosen()}>
                <span class="answered-option-tag">{t('rp.msg.chosen')}</span>
              </Show>
            </span>
          );
        }}
      </For>
    </div>
  );
}
