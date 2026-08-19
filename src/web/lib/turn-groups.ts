/**
 * 轮次分组（五轮 S2/#2：消息流碎片化清偿）。
 *
 * 一轮 Agent 回复会产出多条消息条目（正文气泡 / 文档卡 / 图片卡），
 * 渲染层按轮次聚合进同一容器（turn group），消除「一轮产出散落多条消息」
 * 的碎片化观感。
 *
 * 聚合规则（D3 终裁）：
 * - 后端显式下发 turnId（同轮正文/文档卡/图片卡共用）为主；
 * - 无 turnId 的旧消息回落「相邻 agent 消息同组」兜底；
 * - 用户消息永远独立成组（一问一答一坨的心智）。
 */
import type { ChatMessage } from '@/types';

export interface TurnGroup {
  kind: 'user' | 'turn';
  /** 组内消息在原数组中的下标（顺序不变） */
  indices: number[];
  turnId?: string;
}

/** 把消息列表分组为轮次容器序列（纯函数，渲染层消费） */
export function groupTurns(messages: ChatMessage[]): TurnGroup[] {
  const groups: TurnGroup[] = [];
  let cur: TurnGroup | null = null;
  messages.forEach((m, i) => {
    if (m.sender === 'user') {
      groups.push({ kind: 'user', indices: [i] });
      cur = null;
      return;
    }
    // 可并入当前轮次组：turnId 一致，或任一侧无 turnId（旧消息相邻兜底）
    const canMerge = cur !== null
      && (!m.turnId || !cur.turnId || m.turnId === cur.turnId);
    if (canMerge && cur) {
      cur.indices.push(i);
      if (m.turnId) cur.turnId = m.turnId;
    } else {
      cur = { kind: 'turn', indices: [i], turnId: m.turnId };
      groups.push(cur);
    }
  });
  return groups;
}

/** 六轮 S5/N4c：建议动作按钮挂载点（ChatFeed 消费）。
 * 规则：最后一条携带 suggestedActions 的消息为候选；其后出现新「用户消息」
 * 即视为已处置（用户已用别的方式继续）→ 返回 -1（旧按钮失效）。
 * 同轮的 agent 派生条目（doc 卡/图片卡）不构成失效。 */
export function suggestedTargetIndex(
  messages: ChatMessage[],
  isStreaming: boolean,
): number {
  if (isStreaming) return -1;
  let candidate = -1;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if ((messages[i].suggestedActions || []).length) { candidate = i; break; }
  }
  if (candidate < 0) return -1;
  for (let i = candidate + 1; i < messages.length; i += 1) {
    if (messages[i].sender === 'user') return -1;
  }
  return candidate;
}

/** 已回应暂停卡的「当时所选值」（对标 AskUserQuestion：展示层状态从权威登记派生）。
 * 优先结构化匹配：其后首条携带 pauseAnsweredId 且与暂停卡 pauseId 相等的用户消息；
 * 旧消息（无结构化标记）回落文本匹配：其后首条用户消息文本即所选值。
 * 纯函数，vitest 钉死。 */
export function answeredValueFor(messages: ChatMessage[], idx: number): string {
  const pid = messages[idx].pauseId;
  for (let i = idx + 1; i < messages.length; i += 1) {
    const m = messages[i];
    if (m.sender !== 'user') continue;
    // 系统动作行（如「本次放行」）不构成对暂停的回应
    if (m.kind === 'system_action') continue;
    if (pid && m.pauseAnsweredId === pid) return (m.pauseAnsweredValue || '').trim();
    return (m.text || '').trim();
  }
  return '';
}
