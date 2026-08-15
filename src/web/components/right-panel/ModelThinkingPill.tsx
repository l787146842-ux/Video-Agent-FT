import { createSignal, For, Show, onCleanup } from 'solid-js';
import { FiChevronDown, FiCpu } from 'solid-icons/fi';
import {
  agentModel, setAgentModel, agentProvider, agentThinkingLevel,
  setAgentThinkingLevel, thinkingLevelLabel, THINKING_LEVEL_OPTIONS,
} from '@/stores/agent-prefs';
import { providerModels } from '@/lib/providers';
import { t } from '@/lib/locale';

/**
 * 模型+推理等级组合胶囊（814H7，Codex 样式）：
 * 一个下拉面板两节——「模型」列表 + 「推理等级」四档（高/中/低/默认）。
 * 默认 = 模型原生能力（不下发 reasoning_effort）。
 * 胶囊文字：模型名 + 档位（非默认时），如「gemini-3.1-pro 高」。
 * 选中态对勾由 .pill-option.selected::after 统一渲染。
 */
export function ModelThinkingPill() {
  const [open, setOpen] = createSignal(false);
  let ref: HTMLDivElement | undefined;

  function onDocClick(e: MouseEvent) {
    if (ref && !ref.contains(e.target as Node)) setOpen(false);
  }
  document.addEventListener('click', onDocClick);
  onCleanup(() => document.removeEventListener('click', onDocClick));

  const modelOptions = () =>
    providerModels(agentProvider(), 'chat').map((m) => ({ value: m, label: m }));

  const pillLabel = () => {
    const lv = thinkingLevelLabel();
    return lv === '默认' ? agentModel() : `${agentModel()} ${lv}`;
  };

  return (
    <div class="pill-anchor" ref={ref}>
      <button
        type="button"
        class="toolbar-pill-btn pill-bounded"
        title={`模型：${agentModel()}；推理等级：${thinkingLevelLabel()}`}
        onClick={() => setOpen(!open())}
      >
        <FiCpu size={11} />
        <span class="pill-option-label">{pillLabel()}</span>
        <FiChevronDown size={10} class="pill-chevron" />
      </button>

      <Show when={open()}>
        <div class="pill-dropdown pill-dropdown-wide">
          <div class="pill-section-title">{t('rp.pill.model')}</div>
          <div class="pill-section-scroll">
            <For each={modelOptions()}>
              {(opt) => (
                <button
                  type="button"
                  class={`pill-option ${opt.value === agentModel() ? 'selected' : ''}`}
                  onClick={() => setAgentModel(opt.value)}
                >
                  <span class="pill-option-text">
                    <span class="pill-option-label">{opt.label}</span>
                  </span>
                </button>
              )}
            </For>
            <Show when={!modelOptions().length}>
              <div class="empty-state">{t('rp.pill.noModel')}</div>
            </Show>
          </div>
          <div class="pill-section-title">{t('rp.pill.thinking')}</div>
          <For each={THINKING_LEVEL_OPTIONS}>
            {(opt) => (
              <button
                type="button"
                class={`pill-option ${opt.value === agentThinkingLevel() ? 'selected' : ''}`}
                title={opt.value === '' ? '按模型原生能力，不下发推理档位' : `请求推理档位：${opt.value}`}
                onClick={() => setAgentThinkingLevel(opt.value)}
              >
                <span class="pill-option-text">
                  <span class="pill-option-label">{opt.label}</span>
                </span>
              </button>
            )}
          </For>
        </div>
      </Show>
    </div>
  );
}
