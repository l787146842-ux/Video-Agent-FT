/**
 * 已回应暂停卡的「当时所选」只读标注（回看对勾）——从 ChatMessageItem 抽出，
 * 消息条目组件专注气泡/工具条挂载（任务 #17 红线瘦身）。
 *
 * 2026-09-21 批F（事故 4444/Q3②）：选中项除标题外**同时显示 description**。
 * 4444 实证：用户选了「电影级写实科幻（推荐）」，落盘记录只有标签
 * （`pauseAnsweredValue`），详细描述（16:9 · 约4分钟 · 冷调写实…）虽随
 * confirmOptions 一并落盘却**不渲染**——回看时看不出当初选了什么。
 * 注：发送 payload 仍是标签（与 dsh `selected` 只回标签一致，且
 * `turn-groups.ts` 的对勾匹配依赖值相等），本处只补**显示**。
 */
import { For, Show } from 'solid-js';
import { FiCheckCircle } from 'solid-icons/fi';
import { t } from '@/lib/locale';

/** 确认卡候选项（与 ChatMessage.confirmOptions 元素同形） */
export interface ConfirmOption {
  label: string;
  description?: string;
  group?: string;
  value?: string;
}

export function AnsweredOptions(props: {
  options: ConfirmOption[];
  answeredValue: string;
  /** 附加根类（批次B：settled 相位淡入类由 TurnLedgerCard 透传） */
  class?: string;
}) {
  return (
    <div class={`answered-options${props.class ? ` ${props.class}` : ''}`}>
      <For each={props.options}>
        {(opt) => {
          const lines = (props.answeredValue || '')
            .split('\n').map((s) => s.trim()).filter(Boolean);
          const chosen = () =>
            opt.value === props.answeredValue || opt.label === props.answeredValue
            || lines.includes(opt.value ?? '') || lines.includes(opt.label ?? '');
          return (
            <span class={`answered-option${chosen() ? ' chosen' : ''}`}>
              <Show when={chosen()}>
                <FiCheckCircle size={12} class="answered-option-check" />
              </Show>
              <span class="answered-option-body">
                <span class="answered-option-label">{opt.label}</span>
                {/* 详细描述只对选中项展示（回看时看清当初选了什么） */}
                <Show when={chosen() && (opt.description || '').trim()}>
                  <span class="answered-option-desc">{opt.description}</span>
                </Show>
              </span>
              <Show when={chosen()}>
                <span class="answered-option-tag">{t('rp.msg.chosen')}</span>
              </Show>
            </span>
          );
        }}
      </For>
    </div>
  );
}
