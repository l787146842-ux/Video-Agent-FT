/**
 * 提问回执卡（2026-09-21 A 批，对齐 dsh `AskQuestionRow`）；
 * R 批把「查看」改为 dsh `row.inspect` 的等价物：**查看说明**。
 *
 * 折叠行「提问 · N/M 已回答」+ 点头部展开逐问「问题 → 答案」（PauseQaBlock）。
 * 底部「查看说明/收起说明」= 展开**所选选项的 description**——回执主体保持
 * dsh 口径（只显示 label），需要看全时点它；无说明数据时按钮不出现。
 *
 * 挂载点（用户裁决："回执卡要在我回复的气泡这个位置"）：**用户气泡内**，
 * 与「问题 → 你的选择」同处（见 UserBubble/pauseQa）；agent 侧不挂
 * （阶段完成卡保持原样）。默认展开（回执初现即可读），点头部折叠。
 */
import { Show, createSignal } from 'solid-js';
import { FiChevronDown, FiChevronRight, FiInfo } from 'solid-icons/fi';
import { t } from '@/lib/locale';
import type { PauseQaPair } from '@/lib/turn-groups';
import { PauseQaBlock } from './PauseQaBlock';

export function AskQuestionReceipt(props: {
  /** 该用户消息的逐问答对（pauseQaFor 派生，问题 id 配对） */
  pairs: PauseQaPair[];
}) {
  const [open, setOpen] = createSignal(true);
  const [notes, setNotes] = createSignal(false);
  const answered = () => props.pairs.filter((p) => !p.unanswered).length;
  const toggle = () => setOpen(!open());
  /** 有可看的选项说明（旧数据/选项无 description → 不显示「查看说明」） */
  const hasNotes = () => props.pairs.some((p) => p.notes && Object.keys(p.notes).length > 0);
  const toggleNotes = () => {
    const next = !notes();
    setNotes(next);
    // 开说明时确保回执本体可见（收起态直接点「查看说明」也能看全）
    if (next) setOpen(true);
  };

  return (
    <div class={`ask-receipt${open() ? ' expanded' : ''}`} data-testid="ask-question-receipt">
      <button
        type="button"
        class="ask-receipt-header"
        aria-expanded={open()}
        onClick={toggle}
      >
        {open()
          ? <FiChevronDown size={13} class="ask-receipt-arrow" />
          : <FiChevronRight size={13} class="ask-receipt-arrow" />}
        <span class="ask-receipt-title">{t('rp.receipt.title')}</span>
        <span class="ask-receipt-summary">
          · {t('rp.receipt.answered', { answered: answered(), total: props.pairs.length })}
        </span>
      </button>
      <Show when={open()}>
        <div class="ask-receipt-body">
          <PauseQaBlock pairs={props.pairs} showNotes={notes()} />
        </div>
      </Show>
      <Show when={hasNotes()}>
        <button type="button" class="ask-receipt-toggle" onClick={toggleNotes}>
          <FiInfo size={11} />
          {notes() ? t('rp.receipt.hide') : t('rp.receipt.view')}
        </button>
      </Show>
    </div>
  );
}
