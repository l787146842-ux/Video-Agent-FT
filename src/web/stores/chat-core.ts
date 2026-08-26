/** Chat store 核心（任务 #11 三分拆的共享状态体，对齐 stores/studio-core 模式）。
 *
 * 域实现：chat/messages.ts（消息列表）、chat/stream.ts（流式会话）、
 *         chat/queue.ts（排队引导）；组合出口见 stores/chat.ts（对外 API 不变）。
 * 流式收尾重置/继续建议派生/停止气泡构造抽至 lib/stream-finalize.ts，
 * 供 done/错误/停止/重连四处收尾复用同一语义。
 */
import { createStore } from 'solid-js/store';
import type { ChatMessage } from '@/types';
import type { TurnLedger, LedgerItem } from '@/lib/turn-ledger';
import { emptyLedger } from '@/lib/turn-ledger';
import type { QueuedMessage } from './chat/queue';

/** 过程时间线条目（F2 阶段一：并入轮次账本模型，保留别名兼容既有导入） */
export type TimelineToolEntry = LedgerItem;

/**
 * 聊天状态管理
 * 管理消息列表、流式输出、排队引导（Agent 忙碌态已迁 stores/agent-state.ts）
 */
export interface ChatState {
  messages: ChatMessage[];
  /** 流式累积文本 */
  streamingText: string;
  isStreaming: boolean;
  inputText: string;
  /** 当前流式回复对应的模型名称 */
  streamingModel: string;
  /** 当前轮次账本（F2 阶段一：流式期临时态的单一数据体，
   *  reasoning/items/statusText/思考计时同构归一；完成即相位翻转随消息入库） */
  turnLedger: TurnLedger;
  /** 排队中的引导消息（推理中发送 → 当前任务完成后自动发出） */
  queuedMessages: QueuedMessage[];
  /** 本轮流已渲染过文档卡片的名称（doc_written 即显与 done 全量清单去重用） */
  renderedDocCards: string[];
  /** 推理轮次进度（status 事件 {step,max} 结构化捕获；0 = 未收到） */
  roundStep: number;
  roundMax: number;
  /** 当前轮 turn_id（流式中由 doc_written 打戳建立；终态收尾后保留，
   *  供错误/停止终态帧的幂等守卫判重；startStream/loadMessages 清零） */
  currentTurnId?: string;
}

const defaultChatState: ChatState = {
  messages: [],
  streamingText: '',
  isStreaming: false,
  inputText: '',
  streamingModel: '',
  turnLedger: emptyLedger(),
  queuedMessages: [],
  renderedDocCards: [],
  roundStep: 0,
  roundMax: 0,
  currentTurnId: undefined,
};

const [chatState, setChatState] = createStore<ChatState>(defaultChatState);

export { chatState, setChatState };
