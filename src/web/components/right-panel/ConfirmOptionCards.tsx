import { For, Show } from 'solid-js';
import type { ConfirmOptionItem } from './ConfirmPicker';

/**
 * 确认选项卡列表（单组单选卡与向导页选项卡共用单一组件，
 * 样式/行为改动不需双改）。
 *
 * 2026-09-21 批F（事故 4444/Q2③+Q3，对齐 dsh `multi_select`）：`multi` 为真时
 * 渲染为**复选框**（可勾多个），`selectedLabels` 持多值；为假时逐字保留原
 * 单选行为（`selectedLabel` 单值，旧路径零变化）。
 */
export function ConfirmOptionCards(props: {
  opts: ConfirmOptionItem[];
  /** 单选：当前选中项 */
  selectedLabel: string;
  /** 多选：当前已勾选集合（multi=true 时使用） */
  selectedLabels?: string[];
  /** 是否多选（缺省 false = 单选） */
  multi?: boolean;
  onPick: (label: string) => void;
}) {
  const isOn = (label: string): boolean => (props.multi
    ? (props.selectedLabels || []).includes(label)
    : props.selectedLabel === label);

  return (
    <div class={`confirm-options${props.multi ? ' multi' : ''}`}>
      <For each={props.opts}>
        {(opt) => (
          <button
            type="button"
            class={`confirm-option-card${isOn(opt.label) ? ' selected' : ''}`}
            aria-pressed={props.multi ? isOn(opt.label) : undefined}
            onClick={() => props.onPick(opt.label)}
          >
            <span class={`confirm-option-radio${props.multi ? ' checkbox' : ''}`} />
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
