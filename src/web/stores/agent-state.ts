/** chat/agent 运行态 store（任务 #11 迁域：agentBusy 自 StudioState 迁出）。
 *
 * 迁域理由：agentBusy 描述「Agent 任务进行中」的会话域事实，与画布/故事板
 * 数据无关；studio 只留画布数据，Agent 运行态归 chat/agent 域单点持有。
 * 读取点（RightPanel/ChatInput/submit-message/message-branch/truncate-resend）
 * 与写入点（use-sse fx.setAgentBusy）同批改读 agentState.agentBusy，
 * 对外行为不变（同一 store 语义，仅迁域）。
 */
import { createStore } from 'solid-js/store';

export interface AgentState {
  /** Agent 任务进行中（流式/推理）：拦截新任务提交、对话切换/新建/关闭、
   * 分支截断等并发动作（busy 守卫各读取点自持文案） */
  agentBusy: boolean;
}

const defaultAgentState: AgentState = {
  agentBusy: false,
};

const [agentState, setAgentState] = createStore<AgentState>(defaultAgentState);

export const agentActions = {
  setAgentBusy(busy: boolean) {
    setAgentState('agentBusy', busy);
  },
};

export { agentState, setAgentState };
