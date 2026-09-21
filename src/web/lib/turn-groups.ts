/**
 * 轮次分组（消息流碎片化。
 *
 * 单次 Agent 回复会产出多条消息条目（正文气泡 / 文档卡 / 图片卡），
 * 渲染层按轮次聚合进同一容器（turn group），消除「单次产出散落多条消息」
 * 的碎片化观感。
 *
 * 聚合规则（终裁）：
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

/** ：建议动作按钮挂载点（ChatFeed 消费）。
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

/** 一问一答配对（2026-09-21 批K）：问题原文 × 用户实际所选。
 *  用于把「你当时答了什么」直接渲染在用户气泡里。 */
export interface PauseQaPair {
  /** 问题短标题（可选） */
  header: string;
  /** 问题原文 */
  question: string;
  /** 用户所选（多选多项；用自定义文本作答时为空） */
  selected: string[];
  /** 用户自由文本作答（"其它（自定义输入）"，未用时为空） */
  custom: string;
  /** 该问是否未作答 */
  unanswered: boolean;
}

/** 该用户消息是否是对**某张暂停卡**的回应（是则其气泡应渲染问答对）。 */
export function isPauseAnswerMessage(messages: ChatMessage[], idx: number): boolean {
  const m = messages[idx];
  if (m.sender !== 'user' || m.kind === 'system_action') return false;
  if (!m.pauseAnsweredId) return false;
  // 必须真能找到对应的暂停卡（防脏数据产生无主问答块）
  for (let i = idx - 1; i >= 0; i -= 1) {
    if (messages[i].pauseId === m.pauseAnsweredId) return true;
  }
  return false;
}

/** 该用户消息对应的问答对（一问一答；无问答数据时返回空数组）。
 *
 *  数据来源（批J 落盘面）：`pauseQuestions`（第 i 条暂停卡的问题清单）
 *  × `pauseAnsweredAnswers`（用户逐问所选 `{id, selected[], custom?}`），
 *  **按问题 id 配对**——不再依赖「第几行 = 第几问」的位置约定
 *  （选项文字含换行/某问跳答时不再错位）。
 *
 *  回落：无 `pauseAnsweredAnswers` 的旧消息用 `pauseAnsweredValue` 逐行
 *  按序补齐（尽力而为，位置对齐），保证旧历史也有可读回执。
 *  纯函数，vitest 钉死。
 */
export function pauseQaFor(messages: ChatMessage[], idx: number): PauseQaPair[] {
  const m = messages[idx];
  if (m.sender !== 'user' || !m.pauseAnsweredId) return [];
  // 往前找对应的暂停卡（携问题清单的那条 agent 消息）
  let card = -1;
  for (let i = idx - 1; i >= 0; i -= 1) {
    if (messages[i].pauseId === m.pauseAnsweredId) { card = i; break; }
  }
  if (card < 0) return [];
  const questions = messages[card].pauseQuestions || [];
  if (!questions.length) return [];
  // 答题面：结构化优先（按 id 配对）；旧消息回落逐行补齐
  const byId = new Map<string, { selected: string[]; custom: string }>();
  (m.pauseAnsweredAnswers || []).forEach((a) => {
    if (a && a.id) {
      byId.set(a.id, { selected: (a.selected || []).slice(), custom: (a.custom || '').trim() });
    }
  });
  const legacyLines = m.pauseAnsweredAnswers?.length
    ? [] : (m.pauseAnsweredValue || '').split('\n').map((s) => s.trim()).filter(Boolean);
  return questions.map((q, i) => {
    const qid = (q.id || '').trim() || `q${i + 1}`;
    const hit = byId.get(qid);
    const fallback = hit ? '' : (legacyLines[i] || '');
    const selected = hit ? hit.selected : (fallback ? [fallback] : []);
    const custom = hit ? hit.custom : '';
    return {
      header: (q.header || '').trim(),
      question: (q.question || '').trim(),
      selected,
      custom,
      unanswered: !selected.length && !custom,
    };
  });
}

/**
 * 轮次组引用稳定化：groupTurns 每次返回全新对象，而 Solid <For> 按对象
 * identity diff——引用不稳导致每条消息变化都全树拆建，content-visibility
 * 高度缓存随之失效。组内下标恒为连续区间：首下标+长度相等且 kind/turnId
 * 相同即同组，复用旧引用，<For> 只做尾部增量 diff，既有节点与高度缓存保留。
 */
export function stabilizeGroups(prev: TurnGroup[], next: TurnGroup[]): TurnGroup[] {
  const out: TurnGroup[] = [];
  for (let i = 0; i < next.length; i += 1) {
    const n = next[i];
    const p = prev[i];
    if (p && p.kind === n.kind && p.turnId === n.turnId
      && p.indices.length === n.indices.length
      && p.indices[0] === n.indices[0]) {
      out.push(p);
    } else {
      out.push(n);
    }
  }
  return out;
}
