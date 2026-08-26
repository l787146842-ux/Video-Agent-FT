/** Chat store 组合出口（任务 #11 三分拆，对齐 stores/studio 模式）。
 *
 * 状态体：stores/chat-core.ts；域实现按关注点三分——
 *   chat/messages.ts 消息列表（入库/截断/收尾落盘/决策投影/文档卡/历史加载）
 *   chat/stream.ts   流式会话（开始/进度/思考/工具/增量/重连恢复/清空）
 *   chat/queue.ts    排队引导（推理中继续发送，任务完成后自动发出）
 * 本文件只做组合 re-export：对外 API（chatActions/chatState/setChatState
 * 及各类型）与拆分前完全一致，既有导入不破坏。
 * Agent 忙碌态已迁 stores/agent-state.ts（studio 只留画布数据）。
 */
import { messageActions } from './chat/messages';
import { streamActions } from './chat/stream';
import { queueActions } from './chat/queue';

export { chatState, setChatState } from './chat-core';
export type { ChatState, TimelineToolEntry } from './chat-core';
export type { QueuedMessage } from './chat/queue';

/** 三域动作合并（键名与拆分前 chatActions 完全一致，无覆盖冲突） */
export const chatActions = {
  ...messageActions,
  ...streamActions,
  ...queueActions,
};
