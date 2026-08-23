/**
 * 消息交互派生层。
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
  /** 悬停工具条——编辑：仅最后一条用户消息（原地编辑 = 截断重答，忙碌隐藏） */
  editable: boolean;
  /** 悬停工具条——重新生成：仅最后一条普通 agent 回复（截断重答无 text；
   * 错误/停止气泡不挂——自带 suggestedActions 出口；忙碌隐藏） */
  regenerable: boolean;
  /** 悬停工具条——分支：全部 agent 回复（含历史；以该消息为分叉点截断快照） */
  branchable: boolean;
  /** 悬停工具条——复制：有正文文本的消息 */
  copyable: boolean;
  /** 悬停工具条——存为文档：助手消息且含非空文本（任务#6 C-2 确定性兜底，
   * 点击直接把该条正文 upsert 进项目文档，不经 LLM） */
  docSavable: boolean;
  /** 暂停卡生命周期（回看时可知旧卡是否仍有效） */
  confirmState: ConfirmState;
  /** 已回应暂停卡的「当时所选值」（仅 answered 态非空） */
  answeredValue: string;
}

/** 当前待回应的确认消息下标：最后一条 confirm 消息（任务 #3 扩：结构化
 * 决策表单 decisionForm 同口径），且必须出现在最后一条
 * 用户消息之后（用户回应后旧确认不再可操作）。不能用「整体最后一条」判定：
 * 文档卡片/图片卡片会追加在确认消息之后，会把确认消息顶掉导致引导按钮不渲染。 */
function confirmTargetIdx(messages: ChatMessage[], isStreaming: boolean): number {
  if (isStreaming) return -1;
  let lastUser = -1;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].sender === 'user') { lastUser = i; break; }
  }
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].confirm || messages[i].decisionForm) return i > lastUser ? i : -1;
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

/** 最后一条可编辑的用户消息：有正文的普通用户消息（系统动作行非用户手打不挂）；
 * 与后端截断重答目标同口径（最后一条非 system_action 用户消息）。 */
function lastEditableUserIdx(messages: ChatMessage[]): number {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (m.sender === 'user' && m.kind !== 'system_action' && (m.text || '').trim() !== '') return i;
  }
  return -1;
}

/** 最后一条普通 agent 回复（重新生成挂载点）：有正文且非错误气泡
 * （无 errorKind/errorDetail）、非停止/建议气泡（无 suggestedActions、正文不以
 * ⚠️/⏹ 开头——存量库内无结构化字段的错误/停止气泡同口径跳过）、
 * 非待回应暂停卡（带 confirm/confirmOptions——先回应再重答，防误截断卡片）、
 * 非卡片派生条目。历史轮次不挂重新生成（只留末条）。 */
function lastPlainAgentIdx(messages: ChatMessage[]): number {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (m.sender !== 'agent') continue;
    const text = (m.text || '').trim();
    if (!text) continue;
    if (m.errorKind || m.errorDetail) continue;
    if (text.startsWith('⚠️') || text.startsWith('⏹')) continue;
    if ((m.suggestedActions || []).length) continue;
    if (m.confirm || (m.confirmOptions || []).length) continue;
    return i;
  }
  return -1;
}

/** 消息级分支的历史长度上限：后端历史装载裁 200 条，超限后本地绝对下标
 * 与后端持久化下标错位（up_to_index 会截错位置），此时禁用消息级分支。 */
export const BRANCH_MAX_MESSAGES = 200;

/** 全量派生：与消息数组等长、同序（ChatFeed 按下标消费）。 */
export function deriveAffordances(
  messages: ChatMessage[], isStreaming: boolean,
): MessageAffordance[] {
  const confirmTarget = confirmTargetIdx(messages, isStreaming);
  const gateTarget = gateWarningTargetIdx(messages, isStreaming);
  const suggestedTarget = suggestedTargetIndex(messages, isStreaming);
  const lastEditableUser = lastEditableUserIdx(messages);
  const lastPlainAgent = lastPlainAgentIdx(messages);
  return messages.map((m, idx) => {
    const state = confirmStateFor(messages, idx, confirmTarget);
    return {
      confirmTarget: idx === confirmTarget,
      gateTarget: idx === gateTarget,
      suggestedTarget: idx === suggestedTarget,
      // 编辑/重新生成都走截断重答：忙碌（流式）中隐藏，只挂末条
      editable: !isStreaming && idx === lastEditableUser,
      regenerable: !isStreaming && idx === lastPlainAgent,
      // 分支只挂有正文的 agent 回复；卡片派生条目（doc/图/视频卡，空正文）不挂；
      // 超 BRANCH_MAX_MESSAGES 条时禁用（后端裁 200 条，绝对下标会错位）
      branchable: messages.length <= BRANCH_MAX_MESSAGES
        && m.sender === 'agent' && (m.text || '').trim() !== '',
      copyable: (m.text || '').trim() !== '',
      // 存为文档只挂助手消息：用户消息/空正文卡片派生条目不挂
      docSavable: m.sender === 'agent' && (m.text || '').trim() !== '',
      confirmState: state,
      answeredValue: state === 'answered' ? answeredValueFor(messages, idx) : '',
    };
  });
}
