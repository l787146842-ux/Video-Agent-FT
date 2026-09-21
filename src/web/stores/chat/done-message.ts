/** Chat store · done 主气泡构造域（任务 #21 自 messages.ts 拆出：行数门禁清偿）：
 * done meta 行/主气泡 builder/轮次终态判重，纯函数无 store 依赖。 */
import type { ChatMessage, SseDonePayload } from '@/types';
import { t } from '@/lib/locale';
import { settleLedger, type TurnLedger } from '@/lib/turn-ledger';

/** done 气泡 meta 行（耗时/token/tokens⁄sec/轮次/落盘数；文案全走 locale 字典） */
export function buildDoneMeta(payload: SseDonePayload): string {
  const elapsedMs = payload.elapsed_ms || 0;
  const elapsed = (elapsedMs / 1000).toFixed(1);
  const metaParts = [t('rp.msg.metaTime', { s: elapsed })];
  // 轮次 token 账单（后端 usage 有值才展示；缺失保 0 不显示）
  const totalTokens = (payload.trace?.steps || [])
    .reduce((sum, st) => sum + (st.token_usage || 0), 0);
  if (totalTokens > 0) metaParts.push(t('rp.msg.metaTokens', { n: totalTokens }));
  // tokens/sec：整程计时口径（总 token ÷ 总耗时），消费既有 SSE elapsed_ms + trace.token_usage
  if (totalTokens > 0 && elapsedMs > 0) {
    const tps = Math.round(totalTokens / (elapsedMs / 1000));
    if (tps > 0) metaParts.push(t('rp.msg.metaTokensPerSec', { n: tps }));
  }
  if (payload.steps > 1) metaParts.push(t('rp.msg.metaRounds', { n: payload.steps }));
  if (payload.applied_actions > 0) metaParts.push(t('rp.msg.metaUpdated', { n: payload.applied_actions }));
  return metaParts.join(' · ');
}

/** done 主气泡构造（原 finishStream 内 15+ 字段 push 随消息域下沉为单一 builder） */
export function buildDoneMessage(
  payload: SseDonePayload, thinkingMs: number, fallbackModel: string, liveLedger: TurnLedger,
): ChatMessage {
  const turnId = payload.turn_id || undefined;
  return {
    sender: 'agent',
    ts: Date.now(),
    text: (payload.text || '').trim() || t('rp.msg.emptyReply'),
    meta: buildDoneMeta(payload),
    // 类型收窄：confirm 唯一形态 = 问句文本（无暂停 = undefined）
    confirm: payload.confirmation || undefined,
    appliedActions: payload.applied_actions || 0,
    actionLog: (payload.action_log || []).length ? payload.action_log : undefined,
    // 确认卡片的候选选项（单选卡片，点击即把 label 作为回复发送）
    confirmOptions: (payload.confirmation_options || []).length ? payload.confirmation_options : undefined,
    // 主模型故障 fallback 时标注实际生效的模型
    modelName: payload.fallback_model || fallbackModel || undefined,
    trace: payload.trace && (payload.trace.steps || []).length ? payload.trace : undefined,
    // F2 阶段一：本轮 live 账本相位翻转随消息入库（settled），完成后直接消费同一批账目，不再从 trace 二次重建
    ledger: settleLedger(liveLedger, { thinkingMs, turnId }),
    // 闸机拦截/降级等警告：随消息常驻展示，拦截类附「本次放行」按钮
    warnings: (payload.warnings || []).length ? payload.warnings : undefined,
    thinkingMs: thinkingMs || undefined,
    turnId,
    // 暂停卡语义种类（remind=待补原料 / collect=规格交互 / 其余=阶段完成）；白名单收窄，未知值不入库（防类型退化）
    kind: (['remind', 'collect', 'stage_done', 'confirm'].includes(payload.pause_kind || '')
      ? (payload.pause_kind as ChatMessage['kind'])
      : undefined),
    // 暂停卡结构化标识（用户点选回应时经 pause_response 结构化回携，对勾不再靠文本反推）
    pauseId: payload.pause_id || undefined,
    // 2026-09-21 批B（事故 5555/Q4，对齐 dsh ask_user_question）：问题级字段
    // 非空/非缺省才落（缺省不产生空键，防类型退化）
    pauseHeader: payload.pause_header || undefined,
    pauseDetail: payload.pause_detail || undefined,
    pauseMultiSelect: payload.pause_multi_select || undefined,
    // E1：轮末快照指针 live 落账（done 同轮下发，当前会话即可挂回档动作，无需刷新）
    snapshotId: payload.snapshot_id || undefined,
    // 结构化决策表单（workflow 投影 pending_decision_payload，schema→表单数据驱动；与确认卡同源同消息，不另起卡片）
    decisionForm: payload.workflow?.pending_decision_payload || undefined,
    // 建议动作按钮（重试/继续，确定性交互；仅最后一条消息渲染）
    suggestedActions: (payload.suggested_actions || []).length
      ? payload.suggested_actions : undefined,
  };
}

/** 轮次已落账标记：done 主气泡 meta / 错误气泡 errorKind / 停止气泡继续建议
 * 任一落地即视为该轮终态已处理（finishStream/streamError/cancelStream 幂等守卫共用） */
export function isTurnSettled(m: ChatMessage): boolean {
  return m.meta !== undefined || m.errorKind !== undefined || m.suggestedActions !== undefined;
}
