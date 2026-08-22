import { For, Show } from 'solid-js';
import type { ConfirmOptionItem } from './ConfirmPicker';

/**
 * 确认选项卡列表（单组单选卡与向导页选项卡共用单一组件，
 * 样式/行为改动不需双改）
 */
export function ConfirmOptionCards(props: {
  opts: ConfirmOptionItem[];
  selectedLabel: string;
  onPick: (label: string) => void;
}) {
  return (
    <div class="confirm-options">
      <For each={props.opts}>
        {(opt) => (
          <button
            type="button"
            class={`confirm-option-card${props.selectedLabel === opt.label ? ' selected' : ''}`}
            onClick={() => props.onPick(opt.label)}
          >
            <span class="confirm-option-radio" />
            <span class="confirm-option-body">
              <span class="confirm-option-label">{opt.display || opt.label}</span>
              <Show when={opt.description}>
                <span class="confirm-option-desc">{opt.description}</span>
              </Show>
            </span>
          </button>
        )}
      </For>
    </div>
  );
}
