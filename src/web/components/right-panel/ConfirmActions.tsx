import { For, Show, createMemo, createSignal } from 'solid-js';
import { sendUserMessage } from '@/lib/agent-actions';
import { t } from '@/lib/locale';
import type { ChatMessage } from '@/types';
import { pickDimension, kindForDim, ConfigProviderModelSelect, type ConfirmOptionItem } from './ConfirmPicker';

/** 无 group 的普通选项组使用的内部键 */
const SINGLE_KEY = '__single__';

/**
 * 确认操作区（当前待回应的 confirm 消息渲染）：所有引导交互统一放进
 * confirm-wizard 组容器：带 group 的选项渲染分页向导（逐页选择，末页发送，
 * 各维度合并为一条消息）；无 group 的渲染单选卡片；厂商/模型维度改用下拉框
 * （ConfirmPicker，888 反馈）；「其它（自定义输入）」在组内展开输入框直接发送；
 * 无候选选项时渲染「确认，继续 / 我要调整」按钮。
 */
export function ConfirmActions(props: { message: ChatMessage }) {
  const msg = () => props.message;
  const options = () => (msg().confirmOptions || []) as ConfirmOptionItem[];

  const focusChatInput = () => document.getElementById('chatInputTextarea')?.focus();

  // ---------- 分页向导 / 选择状态 ----------
  const hasGroups = createMemo(() => options().some((o) => (o.group || '').trim() !== ''));
  const groups = createMemo(() => {
    const order: string[] = [];
    const map = new Map<string, ConfirmOptionItem[]>();
    for (const o of options()) {
      const g = (o.group || '').trim() || '其它';
      if (!map.has(g)) {
        map.set(g, []);
        order.push(g);
      }
      map.get(g)!.push(o);
    }
    return order.map((title) => ({ title, opts: map.get(title) || [] }));
  });

  const [page, setPage] = createSignal(0);
  /** 各组的卡片选择（group 标题 / SINGLE_KEY → label） */
  const [picks, setPicks] = createSignal<Record<string, string>>({});
  /** 各组的组内自定义输入文本（非空时优先于卡片选择） */
  const [customText, setCustomText] = createSignal<Record<string, string>>({});
  /** 各组自定义输入框是否展开 */
  const [customOpen, setCustomOpen] = createSignal<Record<string, boolean>>({});

  const curGroup = () => groups()[Math.min(page(), groups().length - 1)];
  /** 当前向导页/单组是否为厂商/模型维度（渲染下拉框而非选项卡，888 反馈） */
  const wizardDim = () => pickDimension(curGroup()?.title || '', curGroup()?.opts || []);
  const singleDim = () => pickDimension('', options());
  /** 某组当前生效的选择：自定义输入非空时优先，否则取卡片选择 */
  const effective = (key: string) => {
    const txt = (customText()[key] || '').trim();
    return txt || picks()[key] || '';
  };
  const allPicked = () => groups().every((g) => Boolean(effective(g.title)));

  const sendAll = () => {
    const lines = groups().map((g) => effective(g.title)).filter(Boolean);
    if (lines.length) void sendUserMessage(lines.join('\n'));
  };
  const sendSingle = () => {
    const v = effective(SINGLE_KEY);
    if (v) void sendUserMessage(v);
  };

  const pickCard = (key: string, label: string) => {
    setPicks({ ...picks(), [key]: label });
    // 选中卡片即放弃自定义输入（单选互斥）
    if ((customText()[key] || '').trim()) {
      setCustomText({ ...customText(), [key]: '' });
    }
  };

  const toggleCustom = (key: string, el?: HTMLButtonElement) => {
    const open = !customOpen()[key];
    setCustomOpen({ ...customOpen(), [key]: open });
    if (open) {
      // 展开后聚焦组内输入框
      requestAnimationFrame(() => {
        el?.closest('.confirm-wizard')?.querySelector<HTMLTextAreaElement>('.confirm-custom-input')?.focus();
      });
    }
  };

  /** 「其它（自定义输入）」按钮 + 组内输入框 */
  const customBlock = (key: string) => (
    <>
      <button
        type="button"
        class={`confirm-btn secondary${customOpen()[key] || (customText()[key] || '').trim() ? ' active' : ''}`}
        onClick={(e) => toggleCustom(key, e.currentTarget)}
      >
        {t('rp.confirm.customBtn')}
      </button>
      <Show when={customOpen()[key]}>
        <textarea
          class="confirm-custom-input"
          rows={2}
          placeholder={t('rp.confirm.customPlaceholder')}
          value={customText()[key] || ''}
          onInput={(e) => {
            const v = e.currentTarget.value;
            setCustomText({ ...customText(), [key]: v });
            // 输入自定义内容即取消卡片选择（单选互斥）
            if (v.trim() && picks()[key]) {
              const next = { ...picks() };
              delete next[key];
              setPicks(next);
            }
          }}
          onKeyDown={(e) => {
            // Ctrl/Cmd+Enter 快捷发送（普通回车允许换行写多行）
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              const v = (customText()[key] || '').trim();
              if (v) void sendUserMessage(v);
            }
          }}
        />
      </Show>
    </>
  );

  return (
    <>
      <Show when={options().length > 0}>
        <Show
          when={hasGroups()}
          fallback={
            /* 无翻页的单组选项：选中卡片后点右下角「发送」；
               厂商/模型维度直接下拉选择（888 反馈） */
            <div class="confirm-wizard">
              <Show
                when={singleDim()}
                fallback={
                  <div class="confirm-options">
                    <For each={options()}>
                      {(opt) => (
                        <button
                          type="button"
                          class={`confirm-option-card${picks()[SINGLE_KEY] === opt.label ? ' selected' : ''}`}
                          onClick={() => pickCard(SINGLE_KEY, opt.label)}
                        >
                          <span class="confirm-option-radio" />
                          <span class="confirm-option-body">
                            <span class="confirm-option-label">{opt.label}</span>
                            <Show when={opt.description}>
                              <span class="confirm-option-desc">{opt.description}</span>
                            </Show>
                          </span>
                        </button>
                      )}
                    </For>
                  </div>
                }
              >
                <ConfigProviderModelSelect
                  kind={kindForDim(singleDim(), '')}
                  value={picks()[SINGLE_KEY] || ''}
                  onPick={(v) => pickCard(SINGLE_KEY, v)}
                />
              </Show>
              {customBlock(SINGLE_KEY)}
              <div class="confirm-wizard-footer">
                <span class="confirm-wizard-hint">
                  {(customText()[SINGLE_KEY] || '').trim() ? t('rp.confirm.hintCustom') : t('rp.confirm.hintPick')}
                </span>
                <button
                  type="button"
                  class="confirm-btn primary"
                  disabled={!effective(SINGLE_KEY)}
                  onClick={sendSingle}
                >
                  {t('rp.confirm.send')}
                </button>
              </div>
            </div>
          }
        >
          <div class="confirm-wizard">
            <div class="confirm-wizard-question">{curGroup().title}</div>
            <Show
              when={wizardDim()}
              fallback={
                <div class="confirm-options">
                  <For each={curGroup().opts}>
                    {(opt) => (
                      <button
                        type="button"
                        class={`confirm-option-card${picks()[curGroup().title] === opt.label ? ' selected' : ''}`}
                        onClick={() => pickCard(curGroup().title, opt.label)}
                      >
                        <span class="confirm-option-radio" />
                        <span class="confirm-option-body">
                          <span class="confirm-option-label">{opt.label}</span>
                          <Show when={opt.description}>
                            <span class="confirm-option-desc">{opt.description}</span>
                          </Show>
                        </span>
                      </button>
                    )}
                  </For>
                </div>
              }
            >
              <ConfigProviderModelSelect
                kind={kindForDim(wizardDim(), curGroup().title)}
                value={picks()[curGroup().title] || ''}
                onPick={(v) => pickCard(curGroup().title, v)}
              />
            </Show>
            {customBlock(curGroup().title)}
            <div class="confirm-wizard-footer">
              <div class="confirm-wizard-pager">
                <button
                  type="button"
                  class="confirm-wizard-arrow"
                  disabled={page() === 0}
                  onClick={() => setPage(Math.max(0, page() - 1))}
                >
                  ‹
                </button>
                <span class="confirm-wizard-indicator">
                  {page() + 1}/{groups().length}
                </span>
                <button
                  type="button"
                  class="confirm-wizard-arrow"
                  disabled={page() >= groups().length - 1}
                  onClick={() => setPage(Math.min(groups().length - 1, page() + 1))}
                >
                  ›
                </button>
              </div>
              <div class="confirm-wizard-actions">
                <Show
                  when={page() < groups().length - 1}
                  fallback={
                    <button
                      type="button"
                      class="confirm-btn primary"
                      disabled={!allPicked()}
                      onClick={sendAll}
                    >
                      {t('rp.confirm.send')}
                    </button>
                  }
                >
                  <button
                    type="button"
                    class="confirm-btn primary"
                    disabled={!effective(curGroup().title)}
                    onClick={() => setPage(page() + 1)}
                  >
                    {t('rp.confirm.next')}
                  </button>
                </Show>
              </div>
            </div>
          </div>
        </Show>
      </Show>
      <div class="confirm-actions">
        <Show when={!options().length}>
          <button
            type="button"
            class="confirm-btn primary"
            onClick={() => void sendUserMessage(t('rp.msg.confirmText'))}
          >
            {t('rp.msg.confirmContinue')}
          </button>
          <button type="button" class="confirm-btn secondary" onClick={focusChatInput}>
            {t('rp.msg.adjust')}
          </button>
        </Show>
      </div>
    </>
  );
}
