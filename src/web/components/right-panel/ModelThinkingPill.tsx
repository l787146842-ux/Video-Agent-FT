import { createSignal, For, Show, onMount, onCleanup } from 'solid-js';
import { FiChevronDown, FiCpu, FiEdit3, FiX } from 'solid-icons/fi';
import {
  agentModel, setAgentModel, agentProvider,
  setAgentThinkingLevel, THINKING_LEVEL_OPTIONS,
} from '@/stores/agent-prefs';
import { providerModels, chatModelMeta, saveChatModelMeta } from '@/lib/providers';
import { t } from '@/lib/locale';

/**
 * 模型选择胶囊（Codex 样式）：下拉面板 = 模型列表；模型项悬停出「编辑」，
 * 侧边展开编辑面板——上下文窗口三挡 + 思考模式开关 + 推理档位，写入
 * chat_models_meta 按 provider+model 精确生效（模型编辑面板批 2026-09-08）。
 *
 * 会话级推理档位 UI 已删（用户裁决：配置统一归编辑面板，一处管）；存量
 * localStorage 档位挂载时清零，注入统一走 meta/兜底链。
 */
/** 窗口三挡（token 数；未配置 = 200K 默认挡回落） */
const WINDOW_TIERS = [
  { label: '200K 默认', value: 200000 },
  { label: '400K', value: 400000 },
  { label: '1M', value: 1000000 },
] as const;

export function ModelThinkingPill() {
  const [open, setOpen] = createSignal(false);
  /** 编辑态：当前正在编辑的模型名（空 = 关闭编辑面板） */
  const [editing, setEditing] = createSignal('');
  /** 编辑面板的本地草稿（打开时从 meta 快照，改动即时保存） */
  const [draft, setDraft] = createSignal({ context_window: 0, thinking_enabled: true, thinking_level: '' });
  let ref: HTMLDivElement | undefined;

  function onDocClick(e: MouseEvent) {
    // 点击面板外关闭下拉，同时收起编辑面板（下次点「编辑」才再出现）
    if (ref && !ref.contains(e.target as Node)) {
      setOpen(false);
      setEditing('');
    }
  }
  document.addEventListener('click', onDocClick);
  onCleanup(() => document.removeEventListener('click', onDocClick));
  // 会话级档位 UI 已删：清掉存量 localStorage 档位，注入统一走模型 meta 链
  onMount(() => setAgentThinkingLevel(''));

  const modelOptions = () =>
    providerModels(agentProvider(), 'chat').map((m) => ({ value: m, label: m }));

  /** 打开编辑面板：从 meta 读当前值（未配置 = 平台默认：200K/思考开/原生档） */
  function openEditor(model: string) {
    const meta = chatModelMeta(agentProvider(), model);
    setDraft({
      context_window: meta?.context_window || WINDOW_TIERS[0].value,
      thinking_enabled: meta?.thinking_enabled !== false,
      thinking_level: meta?.thinking_level || '',
    });
    setEditing(model);
  }

  /** 面板改动即时落库（chat_models_meta，按 provider+model 精确生效） */
  function applyDraft(patch: Partial<typeof draft>) {
    const model = editing();
    if (!model) return;
    const next = { ...draft(), ...patch };
    setDraft(next);
    void saveChatModelMeta(agentProvider(), model, {
      context_window: next.context_window,
      thinking_enabled: next.thinking_enabled,
      thinking_level: next.thinking_level,
    });
  }

  return (
    <div class="pill-anchor" ref={ref}>
      <button
        type="button"
        class="toolbar-pill-btn pill-bounded"
        title={`模型：${agentModel()}`}
        onClick={() => {
          // 重开下拉时清掉上次的编辑态：编辑面板只在点了「编辑」后才出现
          if (!open()) setEditing('');
          setOpen(!open());
        }}
      >
        <FiCpu size={11} />
        <span class="pill-option-label">{agentModel()}</span>
        <FiChevronDown size={10} class="pill-chevron" />
      </button>

      <Show when={open()}>
        <div class="pill-dropdown pill-dropdown-wide">
          <div class="pill-section-title">{t('rp.pill.model')}</div>
          <div class="pill-section-scroll">
            <For each={modelOptions()}>
              {(opt) => (
                <div
                  class={`pill-option-row ${opt.value === agentModel() ? 'selected' : ''}`}
                  onClick={() => setAgentModel(opt.value)}
                  role="button"
                  tabindex={-1}
                >
                  <span class="pill-option-text">
                    <span class="pill-option-label">{opt.label}</span>
                  </span>
                  <button
                    type="button"
                    class={`pill-edit-btn${editing() === opt.value ? ' active' : ''}`}
                    title={`编辑 ${opt.label}（窗口/思考/档位）`}
                    onClick={(e) => {
                      e.stopPropagation();
                      openEditor(opt.value);
                    }}
                  >
                    <FiEdit3 size={11} />
                  </button>
                </div>
              )}
            </For>
            <Show when={!modelOptions().length}>
              <div class="empty-state">{t('rp.pill.noModel')}</div>
            </Show>
          </div>
        </div>
        {/* 模型编辑面板（侧边展开）：窗口三挡 + 思考模式开关 + 推理档位 */}
        <Show when={editing()}>
          <div class="pill-dropdown pill-model-editor" data-model={editing()}>
            <div class="pill-model-editor-head">
              <span class="pill-model-editor-title">{editing()}</span>
              <button
                type="button"
                class="pill-model-editor-close"
                title="关闭编辑"
                onClick={() => setEditing('')}
              >
                <FiX size={12} />
              </button>
            </div>
            <div class="pill-editor-label">上下文窗口</div>
            <For each={WINDOW_TIERS}>
              {(tier) => (
                <button
                  type="button"
                  class={`pill-option ${draft().context_window === tier.value ? 'selected' : ''}`}
                  onClick={() => applyDraft({ context_window: tier.value })}
                >
                  <span class="pill-option-text">
                    <span class="pill-option-label">{tier.label}</span>
                  </span>
                </button>
              )}
            </For>
            {/* 思考模式：label + 右侧 toggle 开关（对齐参考样式） */}
            <div class="pill-editor-row">
              <span class="pill-editor-label inline">思考模式</span>
              <button
                type="button"
                role="switch"
                aria-checked={draft().thinking_enabled}
                class={`pill-toggle${draft().thinking_enabled ? ' on' : ''}`}
                title={draft().thinking_enabled ? '思考开启（点此关闭）' : '思考关闭（点此开启）'}
                onClick={() => applyDraft({ thinking_enabled: !draft().thinking_enabled })}
              >
                <span class="pill-toggle-knob" />
              </button>
            </div>
            {/* 推理档位：直接列在思考开关下（无标题）；思考关闭时置灰 */}
            <div class={`pill-editor-levels${draft().thinking_enabled ? '' : ' disabled'}`}>
              <For each={THINKING_LEVEL_OPTIONS}>
                {(opt) => (
                  <button
                    type="button"
                    class={`pill-option ${draft().thinking_level === opt.value ? 'selected' : ''}`}
                    title={opt.value === '' ? '按模型原生能力，不下发推理档位' : `请求推理档位：${opt.value}`}
                    onClick={() => draft().thinking_enabled && applyDraft({ thinking_level: opt.value })}
                  >
                    <span class="pill-option-text">
                      <span class="pill-option-label">{opt.label}</span>
                    </span>
                  </button>
                )}
              </For>
            </div>
          </div>
        </Show>
      </Show>
    </div>
  );
}
