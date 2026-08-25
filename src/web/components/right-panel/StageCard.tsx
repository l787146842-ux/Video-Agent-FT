import { Show, createSignal } from 'solid-js';
import {
  FiCheckCircle, FiChevronDown, FiChevronRight,
} from 'solid-icons/fi';
import { t } from '@/lib/locale';
import { stageLabelFromMessage } from './AgentTimeline';
import type { ChatMessage } from '@/types';

/**
 * 阶段完成卡（自 ChatMessageItem.tsx 切出）：
 * 可展开、默认展开。正文 = 本轮概述（确认文案，与模型正文判重防双显）。
 * 账目收敛：执行明细（actionLog）只展示在 AgentTimeline「已处理操作」
 * 面板（trace 同源、含 result_summary），本卡只留操作数徽标，不再双处呈现
 *（项目体验基线：信息已在对话内可见的只展示一处）。
 */
export function StageCard(props: {
  msg: () => ChatMessage;
  state: 'active' | 'answered' | 'expired' | 'none';
  /** 附加根类（批次B：settled 相位淡入类由 TurnLedgerCard 透传） */
  class?: string;
}) {
  const [open, setOpen] = createSignal(true);
  const msg = () => props.msg();
  const confirmText = () => msg().confirm || '';
  /** 确认文案与模型正文判重：正文已包含同样句子时卡片只留执行清单；
   * 批次C 判重调位：active 暂停卡带选项时，题面已由问卷卡三段式①
   * （confirm-wizard-question）独立成行接管，阶段卡让位防双显；
   * 无选项的暂停（仅「确认，继续」按钮）题面无处可让，照常呈现 */
  const bodyText = () => {
    const c = confirmText().trim();
    if (!c) return '';
    if (props.state === 'active' && (msg().confirmOptions || []).length > 0) return '';
    const norm = (s: string) => s.replace(/[\s“”'"]/g, '');
    if (norm(msg().text || '').includes(norm(c))) return '';
    return c;
  };
  const hasBody = () => !!bodyText();
  /** 卡标题按 pause kind 语义渲染（Rule2 v6）：
   *  remind=待补原料 / collect=规格交互 / 其余=阶段完成（消误标） */
  const cardTitle = () => {
    const k = msg().kind;
    if (k === 'remind') return '待补原料';
    if (k === 'collect') return '规格交互';
    return stageLabelFromMessage(msg())
      ? `${stageLabelFromMessage(msg())} · ${t('rp.msg.stageDone')}`
      : t('rp.msg.stageDone');
  };

  return (
    <div class={`stage-card ${open() ? 'expanded' : ''} ${props.class || ''}`}>
      <button
        type="button"
        class="stage-card-header"
        onClick={() => setOpen(!open())}
        aria-expanded={open()}
      >
        <FiCheckCircle size={15} class="stage-check" />
        <span class="stage-card-title">
          {cardTitle()}
        </span>
        <Show when={msg().appliedActions}>
          <span class="stage-card-badge">
            {t('rp.msg.appliedOps', { count: msg().appliedActions ?? 0 })}
          </span>
        </Show>
        {/* 非当前待回应的暂停卡标注生命周期（已回应/已过期），回看不迷惑 */}
        <Show when={props.state === 'answered' || props.state === 'expired'}>
          <span class="stage-card-badge stage-card-badge-stale">
            {props.state === 'answered' ? t('rp.msg.confirmAnswered') : t('rp.msg.confirmExpired')}
          </span>
        </Show>
        <Show when={hasBody()}>
          {open() ? <FiChevronDown size={13} class="stage-card-arrow" /> : <FiChevronRight size={13} class="stage-card-arrow" />}
        </Show>
      </button>
      <Show when={open() && hasBody()}>
        <div class="stage-card-body">
          <Show when={bodyText()}>
            <p class="stage-card-summary">{bodyText()}</p>
          </Show>
          {/* actionLog 明细不双处呈现，归 AgentTimeline 单家 */}
        </div>
      </Show>
    </div>
  );
}
