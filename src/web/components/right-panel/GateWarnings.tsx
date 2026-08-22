import { For, Show } from 'solid-js';
import { t } from '@/lib/locale';
import { sendUserMessage } from '@/lib/agent-actions';
import type { ChatMessage } from '@/types';

/** 闸机拦截明细（结构化判定——trace.gates 存在 ok=false 条目，
 * 不再对文案做 includes('拦截') 字符串匹配） */
export interface GateWarningRecord {
  rule_id: string;
  layer: string;
  message: string;
  skill_name?: string;
}

export function gateRecordsOf(msg: ChatMessage): GateWarningRecord[] {
  const out: GateWarningRecord[] = [];
  (msg.trace?.steps || []).forEach((s) => {
    (s.gates || []).forEach((g) => {
      if (!g.ok) {
        out.push({
          rule_id: g.rule_id,
          layer: g.layer,
          message: g.message || '',
          skill_name: g.skill_name,
        });
      }
    });
  });
  return out;
}

/**
 * 闸机拦截 chips + 警告行 +「本次放行」。
 * 相同拦截（同层/同规则/同文案）合并计数折叠 ×N；trace 仍保留全量记录（审计不丢，§2.5）。
 */
export function GateWarnings(props: { message: ChatMessage; isGateTarget?: boolean }) {
  const msg = () => props.message;
  const records = () => gateRecordsOf(msg());
  const hasGateWarning = () => records().length > 0;

  const grouped = () => {
    const out: Array<GateWarningRecord & { count: number }> = [];
    records().forEach((g) => {
      const hit = out.find(
        (o) => o.layer === g.layer && o.rule_id === g.rule_id && o.message === g.message,
      );
      if (hit) hit.count += 1;
      else out.push({ ...g, count: 1 });
    });
    return out;
  };

  /** 本次放行（§2.4）：显式用户指令 + gate_overrides 随消息留痕，后端单次消费。
   *  系统动作形态（对标业界 harness：系统操作不混入用户话语流）；
   *  kind 必须用形态标记 'system_action'（仅此值能命中系统动作行渲染条件） */
  const overrideOnce = () => {
    void sendUserMessage('放行本次拦截，继续任务', {
      gateOverrides: ['all'],
      systemAction: 'system_action',
    });
  };

  return (
    <Show when={(msg().warnings || []).length > 0 || hasGateWarning()}>
      <div class="msg-warnings">
        {/* 闸机判定 chips（结构化来源标注：「平台」/「Skill『xxx』」）；
            相同拦截合并 ×N + details 折叠，防同款长报错刷屏 */}
        <Show when={grouped().length > 0}>
          <details class="msg-gate-collapse" open={grouped().length <= 1}>
            <summary class="msg-gate-collapse-summary">
              {t('rp.msg.gateCollapseSummary', {
                total: String(records().length),
                groups: String(grouped().length),
              })}
            </summary>
            <For each={grouped()}>
              {(g) => (
                <div class="gate-chip-row">
                  <span class={`gate-chip gate-chip-${g.layer === 'platform' ? 'platform' : 'skill'}`}>
                    {g.layer === 'platform'
                      ? t('rp.msg.gatePlatform')
                      : t('rp.msg.gateSkill', { name: g.skill_name || '' })}
                  </span>
                  <span class="gate-chip-msg">{g.message || g.rule_id}</span>
                  <Show when={g.count > 1}>
                    <span class="gate-chip-count">
                      {t('rp.msg.gateCount', { count: String(g.count) })}
                    </span>
                  </Show>
                </div>
              )}
            </For>
          </details>
        </Show>
        <For each={msg().warnings || []}>
          {(w) => <div class="msg-warning-line">⚠ {w}</div>}
        </For>
        {/* 拦截类警告附「本次放行」按钮（结构化挂载，仅最新一条，单次生效留痕） */}
        <Show when={props.isGateTarget && hasGateWarning()}>
          <button type="button" class="gate-override-btn" onClick={overrideOnce}>
            {t('rp.msg.gateOverride')}
          </button>
        </Show>
      </div>
    </Show>
  );
}
