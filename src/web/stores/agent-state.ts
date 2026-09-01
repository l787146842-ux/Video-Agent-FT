/** chat/agent 运行态 store（批 6-2：忙态按对话化，多会话并行）。
 *
 * 语义：同项目多对话可同时运行 Agent 任务（共享项目状态、不复制不合并，
 * 宪法 Rule 3 并发契约 Q25）。busyTasks 按对话记录运行中任务
 *（键=对话 id；''=未携带对话定向的旧路径/测试路径，视为活跃对话口径）。
 * agentBusy 保留为派生兼容位（任一对话忙即真），既有断言/守卫逐步迁读
 * isConvBusy；任务完成且用户未在该对话时置 unread 提示（激活即清）。
 */
import { createStore, produce } from 'solid-js/store';

export interface AgentState {
  /** 全局兼容位：任一对话有运行中任务即真（派生自 busyTasks，勿直接写） */
  agentBusy: boolean;
  /** 对话级忙态：对话 id → 运行中任务 id（''=旧路径回落键） */
  busyTasks: Record<string, string>;
  /** 任务在后台对话完成/出错而用户未在该对话：未读提示（激活该对话即清） */
  unread: Record<string, boolean>;
}

const defaultAgentState: AgentState = {
  agentBusy: false,
  busyTasks: {},
  unread: {},
};

const [agentState, setAgentState] = createStore<AgentState>(defaultAgentState);

function syncAnyBusy() {
  setAgentState('agentBusy', Object.keys(agentState.busyTasks).length > 0);
}

export const agentActions = {
  /** 标记对话忙碌（任务提交/接管/恢复订阅时；任务 id 未知时可先传 ''） */
  setConvBusy(conversationId: string, taskId: string) {
    setAgentState(produce((s) => { s.busyTasks[conversationId || ''] = taskId; }));
    syncAnyBusy();
  },
  /** 解除对话忙碌（任务终态/断开；幂等） */
  clearConvBusy(conversationId: string) {
    setAgentState(produce((s) => { delete s.busyTasks[conversationId || '']; }));
    syncAnyBusy();
  },
  /** 兼容旧写面：true = 标记 '' 键忙（调用方无对话信息时的回落）；
   *  false = 清空全部忙态（终态收尾/测试复位口径） */
  setAgentBusy(busy: boolean) {
    if (busy) {
      agentActions.setConvBusy('', 'unknown');
    } else {
      setAgentState(produce((s) => { s.busyTasks = {}; }));
      syncAnyBusy();
    }
  },
  /** 对话是否有运行中任务（'' 键 = 旧路径回落，视为任意对话口径的保守忙） */
  isConvBusy(conversationId: string): boolean {
    return Boolean(agentState.busyTasks[conversationId] ?? agentState.busyTasks['']);
  },
  /** 取对话的运行中任务 id（无则 ''） */
  taskOfConv(conversationId: string): string {
    return agentState.busyTasks[conversationId] || '';
  },
  markUnread(conversationId: string) {
    if (!conversationId) return;
    setAgentState('unread', conversationId, true);
  },
  clearUnread(conversationId: string) {
    if (!conversationId) return;
    setAgentState('unread', conversationId, false);
  },
  /** 测试复位/硬重置 */
  resetBusy() {
    setAgentState({ agentBusy: false, busyTasks: {}, unread: {} });
  },
};

export { agentState, setAgentState };
