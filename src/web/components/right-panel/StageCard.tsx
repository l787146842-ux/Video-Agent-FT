import { For, Show, createSignal } from 'solid-js';
import {
  FiCheckCircle, FiChevronDown, FiChevronRight,
} from 'solid-icons/fi';
import { t } from '@/lib/locale';
import { stageLabelFromMessage } from './AgentTimeline';
import type { ChatMessage } from '@/types';

/**
 * 阶段完成卡（B2/F12·D4；五轮 S10 自 ChatMessageItem.tsx 切出，零行为变更）：
 * 可展开、默认展开。正文=本轮概述（确认文案，与模型正文判重防双显）+ 执行清单
 * （actionLog）。历史消息同样可展开——暂停点回看不丢失（吸收 Qoder 问题 12）。
 */
export function StageCard(props: { msg: () => ChatMessage; state: 'active' | 'answered' | 'expired' | 'none' }) {
  const [open, setOpen] = createSignal(true);
  const msg = () => props.msg();
  const confirmText = () => {
    const c = msg().confirm;
    return typeof c === 'string' ? c : '';
  };
  /** 确认文案与模型正文判重：正文已包含同样句子时卡片只留执行清单 */
  const bodyText = () => {
    const c = confirmText().trim();
    if (!c) return '';
    const norm = (s: string) => s.replace(/[\s“”'"]/g, '');
    if (norm(msg().text || '').includes(norm(c))) return '';
    return c;
  };
  const hasBody = () => !!bodyText() || (msg().actionLog || []).length > 0;

  return (
    <div class={`stage-card ${open() ? 'expanded' : ''}`}>
      <button
        type="button"
        class="stage-card-header"
        onClick={() => setOpen(!open())}
        aria-expanded={open()}
      >
        <FiCheckCircle size={15} class="stage-check" />
        <span class="stage-card-title">
          {stageLabelFromMessage(msg())
            ? `${stageLabelFromMessage(msg())} · ${t('rp.msg.stageDone')}`
            : t('rp.msg.stageDone')}
        </span>
        <Show when={msg().appliedActions}>
          <span class="stage-card-badge">
            {t('rp.msg.appliedOps', { count: msg().appliedActions ?? 0 })}
          </span>
        </Show>
        {/* 四轮 R3/#10：非当前待回应的暂停卡标注生命周期（已回应/已过期），回看不迷惑 */}
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
          <Show when={(msg().actionLog || []).length > 0}>
            <ul class="stage-card-ops">
              <For each={msg().actionLog || []}>
                {(op) => <li>{op}</li>}
              </For>
            </ul>
          </Show>
        </div>
      </Show>
    </div>
  );
}
