import { Show, For, createMemo, createSignal } from 'solid-js';
import { sendUserMessage } from '@/lib/agent-actions';
import { t } from '@/lib/locale';
import type { ChatMessage, PauseAnswer, PauseQuestion } from '@/types';
import { pickDimension, kindForDim, ConfigProviderModelSelect, type ConfirmOptionItem } from './ConfirmPicker';
import { ConfirmOptionCards } from './ConfirmOptionCards';
import { ConfirmCustomInput } from './ConfirmCustomInput';

/** 无 group 的普通选项组使用的内部键 */
const SINGLE_KEY = '__single__';

/**
 * 确认操作区（当前待回应的 confirm 消息渲染）：引导交互统一放进 confirm-wizard
 * 组容器，按三段式问卷卡组织（批次C）：① 题面（msg.confirm）独立成行；② 选项区
 * 紧随（带 group → 分页向导；无 group → 单选卡片；厂商/模型 → 下拉框 888 反馈）；
 * ③ 「其它（自定义输入）」兜底段组内展开输入框直接发送；无选项时渲染「确认，继续 / 我要调整」按钮。
 *
 * 2026-09-21 批B（事故 5555/Q4，对齐 dsh ask_user_question）：题面之上可再有
 * 短标题（pauseHeader）+ 辅助说明（pauseDetail，**不变成可选项**）。
 * 问句本身仍走 msg.confirm（后端 question 字段落此）。
 */
export function ConfirmActions(props: { message: ChatMessage }) {
  const msg = () => props.message;
  const options = () => (msg().confirmOptions || []) as ConfirmOptionItem[];
  /** 问题级短标题（dsh header；缺省不渲染，防空行） */
  const header = () => (msg().pauseHeader || '').trim();
  /** 问题级辅助说明（dsh detail；**只作说明文本，不参与选项**） */
  const detail = () => (msg().pauseDetail || '').trim();

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
   *  「当时所选」对勾从后端权威登记派生，不再靠文本反推。
   *  2026-09-21 批J：多问题卡另携问题级 `answers`（`{id, selected[], custom?}`，
   *  对齐 dsh `AskUserQuestionAnswerItem`）——后端按 id 精确回填，
   *  不再依赖「逐行拼接文本」的位置约定；`value` 仍派生（旧消费链零改动）。 */
  const pauseOpts = (value: string, answers?: PauseAnswer[], pid = msg().pauseId || '') => (pid
    ? {
      pauseResponse: {
        pause_id: pid,
        value,
        ...(answers && answers.length ? { answers } : {}),
      },
    }
    : {});
  /** 单发语义：暂停回应一经发出即锁，连点/双击不得重复发送
   *  （二次点击若落入排队区，会在任务结束后把同一回答自动重发一遍） */
  const [sent, setSent] = createSignal(false);
  const sendPicked = async (text: string, answers?: PauseAnswer[]) => {
    if (!text || sent()) return;
    setSent(true);
    const ok = await sendUserMessage(text, pauseOpts(text, answers));
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

  const toggleCustom = (key: string, open: boolean) => {
    setCustomOpen({ ...customOpen(), [key]: open });
  };

  /** 「其它（自定义输入）」块（渲染在 ConfirmCustomInput，互斥状态留在本组件） */
  const customBlock = (key: string) => (
    <ConfirmCustomInput
      open={() => !!customOpen()[key]}
      text={() => customText()[key] || ''}
      onToggle={(open) => toggleCustom(key, open)}
      onText={(v) => {
        setCustomText({ ...customText(), [key]: v });
        // 输入自定义内容即取消卡片选择（单选互斥）
        if (v.trim() && picks()[key]) {
          const next = { ...picks() };
          delete next[key];
          setPicks(next);
        }
      }}
      onSend={(txt) => void sendPicked(txt)}
    />
  );

  /** 问题级短标题 + 辅助说明（dsh header/detail；两分支共用，缺省不渲染） */
  const headerBlock = () => (
    <>
      <Show when={header()}>
        <div class="confirm-wizard-header">{header()}</div>
      </Show>
      <Show when={detail()}>
        <div class="confirm-wizard-detail">{detail()}</div>
      </Show>
    </>
  );

  // ---------- 批F：多问题分支（一次问 N 个问题，对齐 dsh questions[]） ----------
  /** 问题级列表（非空才走多问分支；旧消息无此字段 → 逐字走原单问/向导分支） */
  const questions = () => (msg().pauseQuestions || []) as PauseQuestion[];
  const hasQuestions = () => questions().length > 0;
  /** 每问的选择：单选存 label，多选存 label 数组（键 = 问题下标） */
  const [qPick, setQPick] = createSignal<Record<number, string[]>>({});
  /** 每问的组内自定义输入（非空时优先于卡片选择，单选语义） */
  const [qCustom, setQCustom] = createSignal<Record<number, string>>({});
  const [qCustomOpen, setQCustomOpen] = createSignal<Record<number, boolean>>({});

  /** 选项携带 value 时发送 value（后端确定性消费），否则发送 label */
  const optValue = (q: PauseQuestion, label: string) =>
    ((q.options || []) as ConfirmOptionItem[])
      .find((o) => o.label === label && (o.value || '').trim())?.value || label;

  const pickedOf = (idx: number) => qPick()[idx] || [];

  /** 某问当前生效值：自定义输入优先，否则取卡片选择（多选逐项，顺序 = 勾选顺序） */
  const effectiveQ = (idx: number): string[] => {
    const txt = (qCustom()[idx] || '').trim();
    if (txt) return [txt];
    const q = questions()[idx];
    return pickedOf(idx).map((label) => optValue(q, label));
  };

  const toggleQ = (idx: number, label: string) => {
    const q = questions()[idx];
    // 勾选卡片即放弃该问的自定义输入
    if ((qCustom()[idx] || '').trim()) setQCustom({ ...qCustom(), [idx]: '' });
    if (q?.multi_select) {
      const cur = pickedOf(idx);
      setQPick({
        ...qPick(),
        [idx]: cur.includes(label) ? cur.filter((x) => x !== label) : [...cur, label],
      });
    } else {
      setQPick({ ...qPick(), [idx]: [label] });
    }
  };

  /** 全部问题都有答案才能发送（与向导 allPicked 同口径） */
  const allQAnswered = () => questions().every((_, i) => effectiveQ(i).length > 0);

  /** 发送：各问所选**按问题顺序逐行拼接**（与既有向导的分组拼接口径一致）；
   *  多选题内多个选中项同样各占一行。
   *  2026-09-21 批J：另按问题 `id` 组装结构化 `answers` 一并回携——
   *  `value`（逐行文本）保持旧消费链兼容，`answers` 供后端按 id 精确回填。 */
  const sendQuestions = () => {
    const qs = questions();
    const answers: PauseAnswer[] = [];
    const lines: string[] = [];
    qs.forEach((q, i) => {
      const txt = (qCustom()[i] || '').trim();
      const picked = effectiveQ(i);
      if (!picked.length) return;
      const qid = (q.id || '').trim() || `q${i + 1}`;
      // 自定义输入 → custom 槽（对齐 dsh：不用 custom 时该字段省略）
      answers.push(txt
        ? { id: qid, selected: [], custom: txt }
        : { id: qid, selected: picked });
      lines.push(...picked);
    });
    void sendPicked(lines.filter(Boolean).join('\n'), answers);
  };

  const customBlockQ = (idx: number) => (
    <ConfirmCustomInput
      open={() => !!qCustomOpen()[idx]}
      text={() => qCustom()[idx] || ''}
      onToggle={(open) => setQCustomOpen({ ...qCustomOpen(), [idx]: open })}
      onText={(v) => {
        setQCustom({ ...qCustom(), [idx]: v });
        // 输入自定义内容即取消卡片选择（互斥）
        if (v.trim() && pickedOf(idx).length) setQPick({ ...qPick(), [idx]: [] });
      }}
      onSend={(txt) => void sendPicked(txt)}
    />
  );

  /** 多问题卡：逐问一块（各带 header/问句/detail + 各自选项），底部单一发送 */
  const questionsBlock = () => (
    <div class="confirm-wizard confirm-wizard-multi">
      <For each={questions()}>
        {(q, i) => (
          <div class="confirm-question-block" data-testid="pause-question-block">
            <Show when={(q.header || '').trim()}>
              <div class="confirm-wizard-header">{q.header}</div>
            </Show>
            <Show when={(q.question || '').trim()}>
              <div class="confirm-wizard-question">{q.question}</div>
            </Show>
            <Show when={(q.detail || '').trim()}>
              <div class="confirm-wizard-detail">{q.detail}</div>
            </Show>
            <Show
              when={(q.options || []).length > 0}
              fallback={
                /* 无选项的问题：说明用户可在此问下方自定义输入作答 */
                <div class="confirm-question-hint">{t('rp.confirm.qNoOptions')}</div>
              }
            >
              <ConfirmOptionCards
                opts={(q.options || []) as ConfirmOptionItem[]}
                selectedLabel={q.multi_select ? '' : (pickedOf(i())[0] || '')}
                selectedLabels={pickedOf(i())}
                multi={!!q.multi_select}
                onPick={(label) => toggleQ(i(), label)}
              />
            </Show>
            {customBlockQ(i())}
          </div>
        )}
      </For>
      <div class="confirm-wizard-footer">
        <span class="confirm-wizard-hint">
          {allQAnswered() ? t('rp.confirm.hintSendAll') : t('rp.confirm.hintAnswerAll')}
        </span>
        <button
          type="button"
          class="confirm-btn primary"
          disabled={!allQAnswered() || sent()}
          onClick={sendQuestions}
        >
          {t('rp.confirm.send')}
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* 批F：多问题分支优先（pauseQuestions 非空）；否则逐字走既有单问/向导分支 */}
      <Show when={hasQuestions()}>
        {questionsBlock()}
      </Show>
      <Show when={!hasQuestions()}>
      <Show when={options().length > 0}>
        <Show
          when={hasGroups()}
          fallback={
            /* 无翻页的单组选项：选中卡片后点右下角「发送」；
               厂商/模型维度直接下拉选择（888 反馈） */
            <div class="confirm-wizard">
              {/* 批次C 三段式①题面独立成行（StageCard 判重同步调位防双显） */}
              {headerBlock()}
              <Show when={msg().confirm}><div class="confirm-wizard-question">{msg().confirm}</div></Show>
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
            {/* 批次C 三段式①总题面独立成行；与页内子题面（组标题）同句时隐去防双显 */}
            {headerBlock()}
            <Show
              when={msg().confirm && (msg().confirm || '').trim() !== (curGroup().title || '').trim()}
            ><div class="confirm-wizard-question">{msg().confirm}</div></Show>
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
      </Show>
    </>
  );
}
