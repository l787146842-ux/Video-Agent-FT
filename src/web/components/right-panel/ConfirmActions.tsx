import { Show, createMemo, createSignal } from 'solid-js';
import { sendUserMessage } from '@/lib/agent-actions';
import { t } from '@/lib/locale';
import type { ChatMessage } from '@/types';
import { pickDimension, kindForDim, ConfigProviderModelSelect, type ConfirmOptionItem } from './ConfirmPicker';
import { ConfirmOptionCards } from './ConfirmOptionCards';

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

  /** B2/F16：选项携带 value 时发送 value（后端确定性消费），否则发送 label */
  const valueFor = (label: string) =>
    (options() || []).find((o) => o.label === label && (o.value || '').trim())?.value || label;

  /** 暂停回应结构化回携（AskUserQuestion 范式）：点选发送携带 pause_id，
   *  「当时所选」对勾从后端权威登记派生，不再靠文本反推 */
  const pauseOpts = (value: string, pid = msg().pauseId || '') => (pid
    ? { pauseResponse: { pause_id: pid, value } } : {});
  /** 单发语义：暂停回应一经发出即锁，连点/双击不得重复发送
   *  （二次点击若落入排队区，会在任务结束后把同一回答自动重发一遍） */
  const [sent, setSent] = createSignal(false);
  const sendPicked = async (text: string) => {
    if (!text || sent()) return;
    setSent(true);
    const ok = await sendUserMessage(text, pauseOpts(text));
    if (!ok) setSent(false); // 被拦截（无供应商等）时解锁，允许重试
  };
  const sendAll = () => void sendPicked(groups().map((g) => valueFor(effective(g.title))).filter(Boolean).join('\n'));
  const sendSingle = () => void sendPicked(valueFor(effective(SINGLE_KEY)));

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
              void sendPicked((customText()[key] || '').trim());
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
                fallback={(
                  <ConfirmOptionCards
                    opts={options()}
                    selectedLabel={picks()[SINGLE_KEY] || ''}
                    onPick={(v) => pickCard(SINGLE_KEY, v)}
                  />
                )}
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
                  disabled={!effective(SINGLE_KEY) || sent()}
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
              fallback={(
                <ConfirmOptionCards
                  opts={curGroup().opts}
                  selectedLabel={picks()[curGroup().title] || ''}
                  onPick={(v) => pickCard(curGroup().title, v)}
                />
              )}
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
                      disabled={!allPicked() || sent()}
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
            disabled={sent()}
            onClick={() => {
              // 无选项确认同样携带 pause_response（结构化回携全覆盖，
              // 对勾从后端权威登记派生，不再回落文本反推）
              const text = t('rp.msg.confirmText');
              void sendPicked(text);
            }}
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
