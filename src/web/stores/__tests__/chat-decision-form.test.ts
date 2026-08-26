/**
 * stores/chat 结构化决策表单投影测试（任务 #3 A-2）。
 *
 * 钉死契约：
 * ① finishStream：done payload 的 workflow.pending_decision_payload
 *    随主消息落 decisionForm（与确认卡同源同消息，不另起卡片）；
 * ② applyDecisionForm（replay 重建通道）：优先附挂最近待回应暂停消息；
 *    token 幂等（重连不双挂）；不跨用户消息向前附挂；无载体派生独立卡消息。
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { chatState, chatActions } from '../chat';
import type { PendingDecisionPayload } from '@/types';

const pd: PendingDecisionPayload = {
  token: 'decision:run_1',
  node_id: 'storyboard_shots',
  message: '几个分镜？画幅选哪个？',
  schema: { type: 'decision', fields: [{ key: 'shots', label: '几个分镜？', type: 'number' }] },
  options: [],
};

beforeEach(() => {
  chatActions.loadMessages([]);
  chatActions.clearQueuedMessages();
});

describe('finishStream 落结构化决策表单', () => {
  it('done payload workflow.pending_decision_payload 随主消息挂 decisionForm', () => {
    chatActions.startStream('m');
    chatActions.finishStream({
      text: '需要先确认参数', elapsed_ms: 10, steps: 1, applied_actions: 0,
      confirmation: '需要先确认参数', pause_id: 'p1',
      workflow: { pending_decision: true, pending_decision_payload: pd },
    } as never);
    const msg = chatState.messages[chatState.messages.length - 1];
    expect(msg.decisionForm).toEqual(pd);
    expect(msg.confirm).toBe('需要先确认参数');
  });

  it('无 workflow 投影时不挂 decisionForm（契约只增不改，旧链路不受影响）', () => {
    chatActions.startStream('m');
    chatActions.finishStream({
      text: '普通回复', elapsed_ms: 10, steps: 1, applied_actions: 0,
    } as never);
    const msg = chatState.messages[chatState.messages.length - 1];
    expect(msg.decisionForm).toBeUndefined();
  });
});

describe('applyDecisionForm（replay 重建通道）', () => {
  it('优先附挂最近一条待回应 agent 暂停消息', () => {
    chatActions.addMessage({ sender: 'user', text: '开工' });
    chatActions.addMessage({ sender: 'agent', text: '已完成', confirm: '请审阅规格文档' });
    chatActions.applyDecisionForm(pd);
    const msgs = chatState.messages;
    expect(msgs.length).toBe(2); // 不新增消息，附挂既有暂停卡
    expect(msgs[1].decisionForm).toEqual(pd);
  });

  it('token 幂等：同 token 重放不重复挂卡（重连 replay 同源重建）', () => {
    chatActions.addMessage({ sender: 'agent', text: '', confirm: '请审阅' });
    chatActions.applyDecisionForm(pd);
    chatActions.applyDecisionForm(pd);
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages.filter((m) => m.decisionForm?.token === pd.token)).toHaveLength(1);
  });

  it('空 token 投影：以 schema 首字段 key + 问句组合去重（replay 不双挂）', () => {
    const noToken: PendingDecisionPayload = {
      message: '几个分镜？',
      schema: { type: 'decision', fields: [{ key: 'shots', label: '几个分镜？', type: 'number' }] },
    };
    chatActions.applyDecisionForm(noToken); // 无载体 → 派生独立卡
    chatActions.applyDecisionForm(noToken); // 同首字段 key + 同问句 → 命中去重
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].decisionForm?.schema?.fields?.[0]?.key).toBe('shots');
    // 问句不同视为新决策，不去重
    chatActions.applyDecisionForm({ ...noToken, message: '画幅选哪个？' });
    expect(chatState.messages.length).toBe(2);
  });

  it('不跨用户消息向前附挂（用户已回应后旧决策不复活），无载体派生独立卡', () => {
    chatActions.addMessage({ sender: 'agent', text: '', confirm: '请审阅' });
    chatActions.addMessage({ sender: 'user', text: '确认' });
    chatActions.applyDecisionForm(pd);
    const msgs = chatState.messages;
    expect(msgs.length).toBe(3);
    expect(msgs[0].decisionForm).toBeUndefined(); // 旧暂停卡不复活
    // 派生卡：决策问句随 confirm 展示，表单负载齐备
    expect(msgs[2].decisionForm).toEqual(pd);
    expect(msgs[2].confirm).toBe(pd.message);
  });

  it('空负载不挂（无 token 且无 fields 的投影不造壳）', () => {
    chatActions.applyDecisionForm({ schema: {} });
    expect(chatState.messages.length).toBe(0);
  });
});
