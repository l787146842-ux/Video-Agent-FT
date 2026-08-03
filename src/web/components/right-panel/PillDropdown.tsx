import {
  createSignal, onCleanup, For, Show,
} from 'solid-js';
import { Dynamic } from 'solid-js/web';
import { FiChevronDown } from 'solid-icons/fi';
import type { Component } from 'solid-js';

export interface PillOption {
  value: string;
  label: string;
  hint?: string;
}

/**
 * 胶囊下拉选择器（聊天工具栏用）
 */
export function PillDropdown(props: {
  icon: Component<{ size?: number | string }>;
  value: string;
  options: PillOption[];
  title?: string;
  onSelect: (value: string) => void;
}) {
  const [open, setOpen] = createSignal(false);
  let ref: HTMLDivElement | undefined;

  function onDocClick(e: MouseEvent) {
    if (ref && !ref.contains(e.target as Node)) setOpen(false);
  }
  document.addEventListener('click', onDocClick);
  onCleanup(() => document.removeEventListener('click', onDocClick));

  const Icon = () => <Dynamic component={props.icon} size={11} />;
  /** 显示选中项的 label（而非原始 value/ID） */
  const displayLabel = () => {
    const match = props.options.find((o) => o.value === props.value);
    return match?.label || props.value || '未选择';
  };

  return (
    <div class="pill-anchor" ref={ref}>
      <button
        type="button"
        class="toolbar-pill-btn max-w-36"
        title={props.title || props.value}
        onClick={() => setOpen(!open())}
      >
        <Icon />
        <span class="pill-option-label">{displayLabel()}</span>
        <FiChevronDown size={10} class="pill-chevron" />
      </button>

      <Show when={open()}>
        <div class="pill-dropdown">
          <For each={props.options}>
            {(opt) => (
              <button
                type="button"
                class={`pill-option w-full text-left ${
                  opt.value === props.value ? 'selected' : ''
                }`}
                onClick={() => {
                  props.onSelect(opt.value);
                  setOpen(false);
                }}
              >
                <span class="pill-option-text">
                  <span class="pill-option-label">{opt.label}</span>
                  <Show when={opt.hint}>
                    <span class="pill-option-hint">{opt.hint}</span>
                  </Show>
                </span>
              </button>
            )}
          </For>
          <Show when={!props.options.length}>
            <div class="empty-state">暂无可用选项</div>
          </Show>
        </div>
      </Show>
    </div>
  );
}
