/**
 * stores/chat/projection 投影兜底腿单测（D2 批 commit3）。
 *
 * 钉死 refreshProjectionFallback 的兜底语义（3333 冻屏根因类：done 帧丢失 →
 * 确认卡永不出现）：
 * ① 活跃暂停 + 消息尾无载体 → 物化暂停卡（挂既有尾消息，不新增气泡）；
 * ② 已有 confirm / decisionForm 载体 → no-op（不覆盖、不回溯更早消息、不双挂）；
 * ③ 用户已回应（末条 user）→ 旧暂停不复活；
 * ④ 无活跃暂停 / convId 空 / 请求失败 / 响应形状异常 → 静默返回不抛
 *    （兜底腿绝不阻断主链，replay 与历史仍是主源）；
 * ⑤ 选项面归一：缺 label 项丢弃（机械消费无意义）、label trim、无有效选项不造空壳。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const projectionMock = vi.fn();
vi.mock('@/api/conversations', () => ({
  getConversationProjection: (id: string) => projectionMock(id),
}));

import { chatState, chatActions } from '../chat';
import { refreshProjectionFallback } from '../chat/projection';
import { t } from '@/lib/locale';
import type {
  ConversationProjectionResponse, ProjectionActivePause,
} from '@/api/conversations';

/** 造一致切响应（兜底腿只读 interaction_pause 单元） */
function snapWith(pause: ProjectionActivePause | null): ConversationProjectionResponse {
  return {
    conversation_id: 'conv-1',
    asOfSeq: pause?.seq ?? -1,
    values: { interaction_pause: { active_pause: pause, pause_count: pause ? 1 : 0 } },
  };
}

beforeEach(() => {
  projectionMock.mockReset();
  chatActions.loadMessages([]);
  chatActions.clearQueuedMessages();
});

describe('活跃暂停物化（消息尾无载体时挂载）', () => {
  it('末条 agent 消息无载体 → 挂暂停问句与选项（不新增气泡）', async () => {
    chatActions.addMessage({ sender: 'user', text: '开工' });
    chatActions.addMessage({ sender: 'agent', text: '已建好 3 个关键元素' });
    projectionMock.mockResolvedValue(snapWith({
      seq: 42,
      message: '请确认是否继续推进分镜',
      options: [{ label: '继续', description: '进入下一阶段', value: '继续' }],
    }));

    await refreshProjectionFallback('conv-1');

    const msgs = chatState.messages;
    expect(projectionMock).toHaveBeenCalledWith('conv-1');
    expect(msgs).toHaveLength(2);
    expect(msgs[1].confirm).toBe('请确认是否继续推进分镜');
    expect(msgs[1].confirmOptions).toEqual([
      { label: '继续', description: '进入下一阶段', value: '继续' },
    ]);
  });

  it('暂停问句为空 → 落默认标题（卡必有可点问句，不挂空文案）', async () => {
    chatActions.addMessage({ sender: 'agent', text: '……' });
    projectionMock.mockResolvedValue(snapWith({ seq: 7, message: '' }));

    await refreshProjectionFallback('conv-1');

    expect(chatState.messages[0].confirm).toBe(t('rp.decision.defaultTitle'));
  });
});

describe('幂等与不复活（兜底腿不得覆盖主源）', () => {
  it('末条 agent 已有 confirm → no-op：不覆盖文案、不回溯更早消息', async () => {
    chatActions.addMessage({ sender: 'agent', text: '早期无卡消息' });
    chatActions.addMessage({ sender: 'agent', text: '已完成', confirm: '请审阅规格文档' });
    projectionMock.mockResolvedValue(snapWith({
      message: '投影里的另一个问句', options: [{ label: '继续' }],
    }));

    await refreshProjectionFallback('conv-1');

    const msgs = chatState.messages;
    expect(msgs[1].confirm).toBe('请审阅规格文档');
    expect(msgs[1].confirmOptions).toBeUndefined();
    expect(msgs[0].confirm).toBeUndefined();
  });

  it('末条 agent 已挂 decisionForm → no-op（结构化决策表单通道优先）', async () => {
    chatActions.addMessage({
      sender: 'agent', text: '', decisionForm: { token: 'decision:run_1', message: '几个分镜？' },
    });
    projectionMock.mockResolvedValue(snapWith({ message: '请确认是否继续' }));

    await refreshProjectionFallback('conv-1');

    expect(chatState.messages[0].confirm).toBeUndefined();
    expect(chatState.messages[0].confirmOptions).toBeUndefined();
  });

  it('连续两次刷新只挂一次（resume 与 focusConversation 双触发不双挂）', async () => {
    chatActions.addMessage({ sender: 'agent', text: '……' });
    projectionMock.mockResolvedValue(snapWith({
      message: '请确认', options: [{ label: '继续' }],
    }));

    await refreshProjectionFallback('conv-1');
    await refreshProjectionFallback('conv-1');

    expect(chatState.messages).toHaveLength(1);
    expect(chatState.messages[0].confirm).toBe('请确认');
    expect(chatState.messages[0].confirmOptions).toHaveLength(1);
  });

  it('用户已回应（末条 user）→ 旧暂停不复活', async () => {
    chatActions.addMessage({ sender: 'agent', text: '……' });
    chatActions.addMessage({ sender: 'user', text: '继续' });
    projectionMock.mockResolvedValue(snapWith({ message: '请确认' }));

    await refreshProjectionFallback('conv-1');

    expect(chatState.messages[0].confirm).toBeUndefined();
    expect(chatState.messages[1].confirm).toBeUndefined();
  });
});

describe('静默兜底（失败不阻断主链）', () => {
  it('无活跃暂停（active_pause=null）→ 不动消息', async () => {
    chatActions.addMessage({ sender: 'agent', text: '……' });
    projectionMock.mockResolvedValue(snapWith(null));

    await refreshProjectionFallback('conv-1');

    expect(chatState.messages[0].confirm).toBeUndefined();
  });

  it('空账本一致切（values 无 interaction_pause 单元）→ 不炸不挂', async () => {
    chatActions.addMessage({ sender: 'agent', text: '……' });
    projectionMock.mockResolvedValue({
      conversation_id: 'conv-1', asOfSeq: -1, values: {},
    } satisfies ConversationProjectionResponse);

    await refreshProjectionFallback('conv-1');

    expect(chatState.messages[0].confirm).toBeUndefined();
  });

  it('接口失败（404/网络）→ 静默吞掉，不抛不挂卡', async () => {
    chatActions.addMessage({ sender: 'agent', text: '……' });
    projectionMock.mockRejectedValue(new Error('对话不存在'));

    await expect(refreshProjectionFallback('conv-1')).resolves.toBeUndefined();
    expect(chatState.messages[0].confirm).toBeUndefined();
  });

  it('convId 为空 → 不发请求（无活跃对话时不打接口）', async () => {
    await refreshProjectionFallback('');
    expect(projectionMock).not.toHaveBeenCalled();
  });
});

describe('选项面归一（投影读的是模型原始 tool_call 参数）', () => {
  it('缺 label 的选项丢弃、label 前后空白 trim', async () => {
    chatActions.addMessage({ sender: 'agent', text: '……' });
    projectionMock.mockResolvedValue(snapWith({
      message: '请确认',
      options: [{ label: '  继续  ', value: '继续' }, { description: '无标签项' }, { label: '' }],
    }));

    await refreshProjectionFallback('conv-1');

    expect(chatState.messages[0].confirmOptions).toEqual([{ label: '继续', value: '继续' }]);
  });

  it('全部选项无效 → confirmOptions 留空（不造空壳选项面）', async () => {
    chatActions.addMessage({ sender: 'agent', text: '……' });
    projectionMock.mockResolvedValue(snapWith({
      message: '请确认', options: [{ description: '无标签项' }],
    }));

    await refreshProjectionFallback('conv-1');

    expect(chatState.messages[0].confirm).toBe('请确认');
    expect(chatState.messages[0].confirmOptions).toBeUndefined();
  });
});
