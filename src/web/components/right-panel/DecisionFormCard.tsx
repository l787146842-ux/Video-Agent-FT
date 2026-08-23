import { createEffect, createMemo, createSignal, For, Show } from 'solid-js';
import { sendUserMessage } from '@/lib/agent-actions';
import { t } from '@/lib/locale';
import type { ChatMessage, DecisionFormField } from '@/types';

/** 决策表单有效字段（key 非空；数据驱动：后端 schema.fields 原样派生）。
 * 导出供渲染判定与测试钉死（ChatMessageItem 挂载条件同源）。 */
export function decisionFormFields(msg: ChatMessage): DecisionFormField[] {
  return ((msg.decisionForm?.schema?.fields) || [])
    .filter((f) => f && (f.key || '').trim() !== '');
}

/** 字段是否必填（缺省必填；required=false 显式豁免） */
function isRequired(f: DecisionFormField): boolean {
  return f.required !== false;
}

/** 初值：schema 下发的 default 优先（字符串化入输入框） */
function initialValues(fields: DecisionFormField[]): Record<string, string> {
  const out: Record<string, string> = {};
  fields.forEach((f) => {
    out[f.key] = f.default === undefined || f.default === null ? '' : String(f.default);
  });
  return out;
}

/**
 * 结构化决策表单卡（任务 #3 A-2）：workflow pending_decision 的参数表单形态。
 *
 * 数据驱动（schema→表单）：字段清单来自后端 pending_decision.schema.fields
 *（text/number/select 三形态；产出侧写入即渲染，前端不做形态假设）。
 * 用于「几个分镜？画幅选哪个？」类多字段参数决策，与确认卡/选项卡
 *（ConfirmActions）同层互补：有 fields 时本卡接管交互面。
 *
 * 提交走既有恢复通道：sendUserMessage 序列化「字段: 值」逐行发送，
 * 携带 pause_response 结构化回携（如有 pauseId）——系统动作留痕同普通消息。
 */
export function DecisionFormCard(props: { message: ChatMessage }) {
  const form = () => props.message.decisionForm;
  const fields = createMemo(() => decisionFormFields(props.message));
  const [values, setValues] = createSignal<Record<string, string>>({});
  // schema.default 初值入输入框（跟踪 scope 内读 fields，响应性合规）
  createEffect(() => setValues(initialValues(fields())));
  /** 单发语义同确认卡：一经发出即锁，连点不重复发送 */
  const [sent, setSent] = createSignal(false);

  const setValue = (key: string, v: string) => setValues({ ...values(), [key]: v });

  const canSubmit = () => fields().every((f) => {
    if (!isRequired(f)) return true;
    return (values()[f.key] || '').trim() !== '';
  });

  /** 提交：序列化「字段: 值」逐行，走既有消息/暂停回应通道（留痕同普通消息） */
  const submit = async () => {
    if (sent() || !canSubmit()) return;
    setSent(true);
    const text = fields()
      .map((f) => `${f.label || f.key}: ${(values()[f.key] || '').trim()}`)
      .join('\n');
    const pid = props.message.pauseId || '';
    const ok = await sendUserMessage(text, pid
      ? { pauseResponse: { pause_id: pid, value: text } }
      : undefined);
    if (!ok) setSent(false); // 被拦截（无供应商等）时解锁，允许重试
  };

  return (
    <div class="confirm-wizard decision-form-card" data-testid="decision-form-card">
      <Show when={(form()?.message || '').trim()}>
        <div class="confirm-wizard-question">{form()?.message}</div>
      </Show>
      <For each={fields()}>
        {(f) => (
          <div class="decision-form-field">
            <div class="decision-form-label">
              {f.label || f.key}
              <Show when={isRequired(f)}><span class="decision-form-required">*</span></Show>
            </div>
            <Show
              when={f.type === 'select'}
              fallback={(
                <input
                  class="confirm-custom-input decision-form-input"
                  type={f.type === 'number' ? 'number' : 'text'}
                  placeholder={f.placeholder || ''}
                  value={values()[f.key] || ''}
                  onInput={(e) => setValue(f.key, e.currentTarget.value)}
                />
              )}
            >
              <select
                class="confirm-custom-input decision-form-input"
                value={values()[f.key] || ''}
                onChange={(e) => setValue(f.key, e.currentTarget.value)}
              >
                <option value="" disabled>{t('rp.decision.selectPlaceholder')}</option>
                <For each={f.options || []}>
                  {(o) => <option value={o.value || o.label}>{o.label}</option>}
                </For>
              </select>
            </Show>
          </div>
        )}
      </For>
      <div class="confirm-wizard-footer">
        <span class="confirm-wizard-hint">
          {sent() ? t('rp.decision.sent') : t('rp.decision.hint')}
        </span>
        <button
          type="button"
          class="confirm-btn primary"
          disabled={!canSubmit() || sent()}
          onClick={() => void submit()}
        >
          {t('rp.decision.submit')}
        </button>
      </div>
    </div>
  );
}
