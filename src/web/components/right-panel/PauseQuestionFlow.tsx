/**
 * 暂停卡多问题**分页作答**（2026-09-21 A 批，对齐 dsh
 * `packages/client/ui-user-questions/src/client/QuestionComposer.tsx::QuestionFlow`）。
 *
 * 形态：一页一题（header + 问句 + detail + 选项 + 自定义输入）；
 * 单选点选自动翻页（非末题）；底部 pager「‹ i / N ›」+「跳过」+ 主按钮
 * （非末题=「下一题」，末题=「发送」）；发送时整组校验，缺项跳回缺题；
 * 草稿（各题所选/自定义/跳过）随页切换保留。
 *
 * 提交仍组装两份面：逐行文本（旧消费链 `value`）+ 问题级 `answers`
 * （批J 结构化回携），与既有口径一致。
 */
import { Show, createSignal } from 'solid-js';
import { t } from '@/lib/locale';
import type { PauseAnswer, PauseQuestion } from '@/types';
import type { ConfirmOptionItem } from './ConfirmPicker';
import { ConfirmOptionCards } from './ConfirmOptionCards';
import { ConfirmCustomInput } from './ConfirmCustomInput';

export function PauseQuestionFlow(props: {
  questions: PauseQuestion[];
  /** 单发锁（父组件 sent 信号）：为真时全控件冻结 */
  sent: () => boolean;
  /** 发送：逐行文本（旧消费链）+ 问题级结构化 answers */
  onSend: (text: string, answers: PauseAnswer[]) => void;
}) {
  const qs = () => props.questions;
  /** 当前页下标（一页一题） */
  const [index, setIndex] = createSignal(0);
  /** 各题卡片选择（label 数组；键 = 题下标） */
  const [picks, setPicks] = createSignal<Record<number, string[]>>({});
  /** 各题自定义输入（非空时优先于卡片选择，单选语义） */
  const [custom, setCustom] = createSignal<Record<number, string>>({});
  /** 各题自定义输入框是否展开 */
  const [customOpen, setCustomOpen] = createSignal<Record<number, boolean>>({});
  /** 各题显式跳过（dsh 口径：跳过也算完成，发送时记空答案） */
  const [skipped, setSkipped] = createSignal<Record<number, boolean>>({});
  /** 校验反馈（本地文案键；改动任一题即清） */
  const [error, setError] = createSignal<'unanswered' | 'incomplete' | null>(null);

  const cur = (): PauseQuestion =>
    qs()[Math.min(index(), qs().length - 1)] || { id: '', question: '' };
  const isLast = () => index() >= qs().length - 1;
  const pickedOf = (i: number) => picks()[i] || [];
  /** 选项携带 value 时发送 value（后端确定性消费），否则发送 label */
  const optValue = (q: PauseQuestion, label: string) =>
    ((q.options || []) as ConfirmOptionItem[])
      .find((o) => o.label === label && (o.value || '').trim())?.value || label;
  /** 某题当前生效值：自定义输入优先，否则取卡片选择（多选逐项，顺序 = 勾选顺序） */
  const effectiveQ = (i: number): string[] => {
    const txt = (custom()[i] || '').trim();
    if (txt) return [txt];
    return pickedOf(i).map((label) => optValue(qs()[i], label));
  };
  const answeredQ = (i: number) => effectiveQ(i).length > 0;
  const completedQ = (i: number) => answeredQ(i) || !!skipped()[i];

  const toggleQ = (i: number, label: string) => {
    const q = qs()[i];
    // 勾选卡片即放弃该题自定义输入（单选互斥）
    if ((custom()[i] || '').trim()) setCustom({ ...custom(), [i]: '' });
    if (q?.multi_select) {
      const curPicks = pickedOf(i);
      setPicks({
        ...picks(),
        [i]: curPicks.includes(label) ? curPicks.filter((x) => x !== label) : [...curPicks, label],
      });
    } else {
      setPicks({ ...picks(), [i]: [label] });
      // dsh 口径：单选点选即翻页（非末题）
      if (!isLast()) setIndex(index() + 1);
    }
    setSkipped({ ...skipped(), [i]: false });
    setError(null);
  };

  const goPrev = () => {
    if (index() === 0) return;
    setIndex(index() - 1);
    setError(null);
  };
  const goNext = () => {
    if (isLast()) return;
    setIndex(index() + 1);
    setError(null);
  };

  /** 发送：整组校验（缺项跳回缺题）；跳过项记空答案，自定义项走 custom 槽 */
  const submit = () => {
    const missing = qs().findIndex((_, i) => !completedQ(i));
    if (missing >= 0) {
      setIndex(missing);
      setError('incomplete');
      return;
    }
    const answers: PauseAnswer[] = [];
    const lines: string[] = [];
    qs().forEach((q, i) => {
      const qid = (q.id || '').trim() || `q${i + 1}`;
      if (skipped()[i]) {
        // 跳过 = 空答案（后端按「空回答无信息量」丢弃 → 回执显式「未作答」）
        answers.push({ id: qid, selected: [] });
        return;
      }
      const txt = (custom()[i] || '').trim();
      if (txt) {
        answers.push({ id: qid, selected: [], custom: txt });
        lines.push(txt);
        return;
      }
      const picked = effectiveQ(i);
      answers.push({ id: qid, selected: picked });
      lines.push(...picked);
    });
    props.onSend(lines.filter(Boolean).join('\n'), answers);
  };

  /** 主按钮：当前题已答/已跳过 → 下一题；末题 → 发送（缺项由 submit 统一校验） */
  const continueFlow = () => {
    if (!completedQ(index())) {
      setError('unanswered');
      return;
    }
    if (!isLast()) {
      goNext();
      return;
    }
    submit();
  };

  /** 跳过当前题（显式登记；末题跳过即发送） */
  const skipQuestion = () => {
    setSkipped({ ...skipped(), [index()]: true });
    setError(null);
    if (!isLast()) {
      goNext();
      return;
    }
    submit();
  };

  return (
    <div class="confirm-wizard confirm-wizard-multi confirm-wizard-flow">
      <div class="confirm-question-block" data-testid="pause-question-block">
        <Show when={(cur().header || '').trim()}>
          <div class="confirm-wizard-header">{cur().header}</div>
        </Show>
        <Show when={(cur().question || '').trim()}>
          <div class="confirm-wizard-question">{cur().question}</div>
        </Show>
        <Show when={(cur().detail || '').trim()}>
          <div class="confirm-wizard-detail">{cur().detail}</div>
        </Show>
        <Show
          when={(cur().options || []).length > 0}
          fallback={
            /* 无选项的问题：说明用户可在此问下方自定义输入作答 */
            <div class="confirm-question-hint">{t('rp.confirm.qNoOptions')}</div>
          }
        >
          <ConfirmOptionCards
            opts={(cur().options || []) as ConfirmOptionItem[]}
            selectedLabel={cur().multi_select ? '' : (pickedOf(index())[0] || '')}
            selectedLabels={pickedOf(index())}
            multi={!!cur().multi_select}
            onPick={(label) => toggleQ(index(), label)}
          />
        </Show>
        <ConfirmCustomInput
          open={() => !!customOpen()[index()]}
          text={() => custom()[index()] || ''}
          onToggle={(open) => setCustomOpen({ ...customOpen(), [index()]: open })}
          onText={(v) => {
            setCustom({ ...custom(), [index()]: v });
            // 输入自定义内容即取消卡片选择（单选互斥）
            if (v.trim() && pickedOf(index()).length) setPicks({ ...picks(), [index()]: [] });
            setSkipped({ ...skipped(), [index()]: false });
            setError(null);
          }}
          onSend={() => continueFlow()}
        />
      </div>
      <div class="confirm-wizard-footer">
        <div class="confirm-wizard-pager">
          <button
            type="button"
            class="confirm-wizard-arrow"
            data-testid="pause-flow-prev"
            aria-label={t('rp.confirm.prevQuestion')}
            disabled={index() === 0 || props.sent()}
            onClick={goPrev}
          >
            ‹
          </button>
          <span class="confirm-wizard-indicator">{index() + 1} / {qs().length}</span>
          <button
            type="button"
            class="confirm-wizard-arrow"
            data-testid="pause-flow-next"
            aria-label={t('rp.confirm.nextQuestion')}
            disabled={isLast() || props.sent()}
            onClick={goNext}
          >
            ›
          </button>
        </div>
        <div class="confirm-flow-feedback" role="status">
          <Show when={error() === 'incomplete'}>
            <span class="confirm-flow-error">{t('rp.confirm.hintIncomplete')}</span>
          </Show>
          <Show when={error() === 'unanswered'}>
            <span class="confirm-flow-error">{t('rp.confirm.hintUnanswered')}</span>
          </Show>
        </div>
        <div class="confirm-wizard-actions">
          <button
            type="button"
            class="confirm-btn secondary"
            data-testid="pause-flow-skip"
            disabled={props.sent()}
            onClick={skipQuestion}
          >
            {t('rp.confirm.skip')}
          </button>
          <button
            type="button"
            class="confirm-btn primary"
            data-testid="pause-flow-submit"
            disabled={props.sent() || !completedQ(index())}
            onClick={continueFlow}
          >
            {isLast() ? t('rp.confirm.send') : t('rp.confirm.nextQuestion')}
          </button>
        </div>
      </div>
    </div>
  );
}
