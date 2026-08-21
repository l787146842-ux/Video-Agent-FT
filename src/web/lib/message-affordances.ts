/**
 * 消息交互派生层（审核整改批 3：P8 收敛）。
 *
 * 「哪条消息挂哪个交互件」的唯一判定处：输入消息列表 + 流式态，
 * 输出每条消息的交互挂载标志（确认卡目标 / 闸机放行目标 / 建议动作目标 /
 * 暂停卡生命周期 / 已回应所选值）。ChatFeed 只消费结果，不再逐条散落计算；
 * 新增卡片类型只改本层，渲染组件 props 契约不变。
 *
 * 判定语义自 ChatFeed 原样归位（零行为变更），复用 lib/turn-groups 纯函数；
 * vitest 钉死（message-affordances.test.ts）。
 */
import type { ChatMessage } from '@/types';
import { answeredValueFor, suggestedTargetIndex } from './turn-groups';

export type ConfirmState = 'active' | 'answered' | 'expired' | 'none';

/** 单条消息的交互挂载派生结果 */
export interface MessageAffordance {
  /** 当前待回应的确认卡（暂停卡操作区挂载点） */
  confirmTarget: boolean;
  /** 最后一条含闸机拦截判定的消息（「本次放行」按钮挂载点） */
  gateTarget: boolean;
  /** 携带建议动作的消息（重试/继续按钮挂载点） */
  suggestedTarget: boolean;
  /** 用户气泡可编辑（P4-20：编辑控制点挂载位，点击回填输入框后作为新消息发送） */
  editable: boolean;
  /** 暂停卡生命周期（回看时可知旧卡是否仍有效） */
  confirmState: ConfirmState;
  /** 已回应暂停卡的「当时所选值」（仅 answered 态非空） */
  answeredValue: string;
}

/** 当前待回应的确认消息下标：最后一条 confirm 消息，且必须出现在最后一条
 * 用户消息之后（用户回应后旧确认不再可操作）。不能用「整体最后一条」判定：
 * 文档卡片/图片卡片会追加在确认消息之后，会把确认消息顶掉导致引导按钮不渲染。 */
function confirmTargetIdx(messages: ChatMessage[], isStreaming: boolean): number {
  if (isStreaming) return -1;
  let lastUser = -1;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].sender === 'user') { lastUser = i; break; }
  }
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].confirm) return i > lastUser ? i : -1;
  }
  return -1;
}

/** 最后一条含闸机拦截判定（trace.gates ok=false）的消息下标。
 * 结构化判定替代文案 includes('拦截') 字符串匹配——文案/措辞改动不再影响按钮。 */
function gateWarningTargetIdx(messages: ChatMessage[], isStreaming: boolean): number {
  if (isStreaming) return -1;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const gates = (messages[i].trace?.steps || []).flatMap((s) => s.gates || []);
    if (gates.some((g) => !g.ok)) return i;
  }
  return -1;
}

/** 暂停卡生命周期：active=当前待回应；answered=其后已有用户消息（已回应）；
 * expired=被更新的暂停取代。 */
function confirmStateFor(
  messages: ChatMessage[], idx: number, confirmTarget: number,
): ConfirmState {
  if (!messages[idx].confirm) return 'none';
  if (idx === confirmTarget) return 'active';
  for (let i = idx + 1; i < messages.length; i += 1) {
    if (messages[i].sender === 'user') return 'answered';
  }
  return 'expired';
}

/** 用户消息编辑挂载判定（P4-20）：有正文文本的普通用户消息可编辑；
 * 系统动作行（如「本次放行」留痕）非用户手打，不挂编辑。
 * 流式中不失效——编辑旧消息回填输入框与当前推理无冲突（发送走排队）。 */
function isEditable(m: ChatMessage): boolean {
  return m.sender === 'user' && m.kind !== 'system_action' && (m.text || '').trim() !== '';
}

/** 全量派生：与消息数组等长、同序（ChatFeed 按下标消费）。 */
export function deriveAffordances(
  messages: ChatMessage[], isStreaming: boolean,
): MessageAffordance[] {
  const confirmTarget = confirmTargetIdx(messages, isStreaming);
  const gateTarget = gateWarningTargetIdx(messages, isStreaming);
  const suggestedTarget = suggestedTargetIndex(messages, isStreaming);
  return messages.map((m, idx) => {
    const state = confirmStateFor(messages, idx, confirmTarget);
    return {
      confirmTarget: idx === confirmTarget,
      gateTarget: idx === gateTarget,
      suggestedTarget: idx === suggestedTarget,
      editable: isEditable(messages[idx]),
      confirmState: state,
      answeredValue: state === 'answered' ? answeredValueFor(messages, idx) : '',
    };
  });
}
