/**
 * conversations store 测试（任务 #8 E-2：消息单一来源）。
 *
 * 钉死 convState 只持有对话元信息（id/title），消息装载统一经
 * 「按会话拉消息」接口进 chat store：
 * - 切换/新建/关闭（删活跃）→ 活跃对话变化 → 拉目标对话消息装载；
 * - 关闭非活跃对话 → 活跃未变 → 不重载（不冲掉本地流式状态）；
 * - 拉取失败 → 装载空列表 + toast（不残留上一对话消息）；
 * - 并发兜底：响应回来时活跃对话已再次切换 → 丢弃过期结果；
 * - syncFromServer/loadFromSnapshot 只刷新元信息，不触碰 chat 消息。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const listMock = vi.fn();
const createMock = vi.fn();
const deleteMock = vi.fn();
const activateMock = vi.fn();
const messagesMock = vi.fn();
vi.mock('@/api/conversations', () => ({
  getConversations: () => listMock(),
  createConversation: (title?: string) => createMock(title),
  deleteConversation: (id: string) => deleteMock(id),
  activateConversation: (id: string) => activateMock(id),
  getConversationMessages: (id: string) => messagesMock(id),
}));

const toastMock = vi.fn();
vi.mock('@/stores/toast', () => ({
  showToast: (msg: string, kind: string) => toastMock(msg, kind),
}));

import { convState, convActions, setConvState } from '../conversations';
import { chatState, chatActions } from '../chat';

const meta = (id: string, title: string) => ({ id, title });
const payload = (ids: string[], activeId: string) => ({
  conversations: ids.map((id) => meta(id, `会话 ${id}`)),
  active_conversation_id: activeId,
});

describe('convActions 消息单一来源装载（E-2）', () => {
  beforeEach(() => {
    setConvState({ list: [], activeId: '' });
    chatActions.loadMessages([]);
    listMock.mockReset();
    createMock.mockReset();
    deleteMock.mockReset();
    activateMock.mockReset();
    messagesMock.mockReset();
    toastMock.mockReset();
  });

  it('activate：切换后经按会话拉消息接口装载目标对话历史', async () => {
    setConvState({ list: [meta('c1', '会话1'), meta('c2', '会话2')], activeId: 'c1' });
    activateMock.mockResolvedValue(payload(['c1', 'c2'], 'c2'));
    messagesMock.mockResolvedValue({
      conversation_id: 'c2',
      messages: [{ sender: 'user', text: '会话2的历史' }],
    });
    await convActions.activate('c2');
    expect(activateMock).toHaveBeenCalledWith('c2');
    expect(messagesMock).toHaveBeenCalledWith('c2');
    expect(convState.activeId).toBe('c2');
    expect(chatState.messages.map((m) => m.text)).toEqual(['会话2的历史']);
  });

  it('activate 同一对话：不发请求不重载', async () => {
    setConvState({ list: [meta('c1', '会话1')], activeId: 'c1' });
    await convActions.activate('c1');
    expect(activateMock).not.toHaveBeenCalled();
    expect(messagesMock).not.toHaveBeenCalled();
  });

  it('create：新对话为空，装载空消息列表', async () => {
    setConvState({ list: [meta('c1', '会话1')], activeId: 'c1' });
    chatActions.addMessage({ sender: 'user', text: '旧对话消息' });
    createMock.mockResolvedValue(payload(['c1', 'c2'], 'c2'));
    messagesMock.mockResolvedValue({ conversation_id: 'c2', messages: [] });
    const ok = await convActions.create();
    expect(ok).toBe(true);
    expect(messagesMock).toHaveBeenCalledWith('c2');
    expect(chatState.messages).toHaveLength(0);
  });

  it('close 非活跃对话：活跃未变，不拉消息不重载（不冲流式状态）', async () => {
    setConvState({ list: [meta('c1', '会话1'), meta('c2', '会话2')], activeId: 'c1' });
    chatActions.addMessage({ sender: 'user', text: '正在看的消息' });
    deleteMock.mockResolvedValue(payload(['c1'], 'c1'));
    await convActions.close('c2');
    expect(messagesMock).not.toHaveBeenCalled();
    expect(chatState.messages.map((m) => m.text)).toEqual(['正在看的消息']);
    expect(convState.list).toHaveLength(1);
  });

  it('close 活跃对话：后端回落首个对话，拉取新活跃消息装载', async () => {
    setConvState({ list: [meta('c1', '会话1'), meta('c2', '会话2')], activeId: 'c2' });
    deleteMock.mockResolvedValue(payload(['c1'], 'c1'));
    messagesMock.mockResolvedValue({
      conversation_id: 'c1',
      messages: [{ sender: 'agent', text: 'c1 的历史' }],
    });
    await convActions.close('c2');
    expect(messagesMock).toHaveBeenCalledWith('c1');
    expect(chatState.messages.map((m) => m.text)).toEqual(['c1 的历史']);
  });

  it('仅剩一个对话时 close 直接拒绝（不发请求）', async () => {
    setConvState({ list: [meta('c1', '会话1')], activeId: 'c1' });
    await convActions.close('c1');
    expect(deleteMock).not.toHaveBeenCalled();
  });

  it('消息拉取失败：装载空列表 + toast（不残留上一对话消息）', async () => {
    setConvState({ list: [meta('c1', '会话1'), meta('c2', '会话2')], activeId: 'c1' });
    chatActions.addMessage({ sender: 'user', text: 'c1 消息' });
    activateMock.mockResolvedValue(payload(['c1', 'c2'], 'c2'));
    messagesMock.mockRejectedValue(new Error('网络中断'));
    await convActions.activate('c2');
    expect(chatState.messages).toHaveLength(0);
    expect(toastMock).toHaveBeenCalled();
    expect(toastMock.mock.calls[0][0]).toContain('网络中断');
  });

  it('并发兜底：拉取响应回来时活跃对话已再次切换，丢弃过期结果', async () => {
    setConvState({ list: [meta('c1', '会话1'), meta('c2', '会话2')], activeId: 'c1' });
    activateMock.mockResolvedValue(payload(['c1', 'c2'], 'c2'));
    let release: (v: { conversation_id: string; messages: unknown[] }) => void = () => {};
    messagesMock.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    const pending = convActions.activate('c2');
    // 等 activate 走到消息拉取挂起点（微任务排干）
    await new Promise((r) => { setTimeout(r, 0); });
    expect(messagesMock).toHaveBeenCalledWith('c2');
    // 响应未回期间用户已切到 c3
    setConvState('activeId', 'c3');
    release({ conversation_id: 'c2', messages: [{ sender: 'user', text: '过期消息' }] });
    await pending;
    expect(chatState.messages).toHaveLength(0); // 过期结果被丢弃
  });

  it('applyPayload（分支通道）：元信息入 store + 活跃变化时拉消息装载', async () => {
    setConvState({ list: [meta('c1', '会话1')], activeId: 'c1' });
    messagesMock.mockResolvedValue({
      conversation_id: 'c-branch',
      messages: [{ sender: 'user', text: '分支历史' }],
    });
    await convActions.applyPayload(payload(['c1', 'c-branch'], 'c-branch'));
    expect(convState.list.map((c) => c.id)).toEqual(['c1', 'c-branch']);
    expect(chatState.messages.map((m) => m.text)).toEqual(['分支历史']);
  });
});

describe('convActions 快照同步（只动元信息，不触碰 chat 消息）', () => {
  beforeEach(() => {
    setConvState({ list: [], activeId: '' });
    chatActions.loadMessages([]);
  });

  it('syncFromServer：刷新对话元信息与活跃态，不重载 chat（消息唯一来源 = chat store）', () => {
    chatActions.addMessage({ sender: 'agent', text: '本地流式消息' });
    convActions.syncFromServer({
      conversations: [meta('c1', '新标题')],
      activeConversationId: 'c1',
    });
    expect(convState.list[0].title).toBe('新标题');
    expect(convState.activeId).toBe('c1');
    expect(chatState.messages.map((m) => m.text)).toEqual(['本地流式消息']);
  });

  it('syncFromServer 空清单不覆盖本地标签栏', () => {
    setConvState({ list: [meta('c1', '会话1')], activeId: 'c1' });
    convActions.syncFromServer({ conversations: [] });
    expect(convState.list).toHaveLength(1);
  });

  it('loadFromSnapshot：装载标签栏；null/空快照清空', () => {
    convActions.loadFromSnapshot({
      conversations: [meta('c1', '会话1'), meta('c2', '会话2')],
      activeConversationId: 'c2',
    });
    expect(convState.list).toHaveLength(2);
    expect(convState.activeId).toBe('c2');
    convActions.loadFromSnapshot(null);
    expect(convState.list).toHaveLength(0);
    expect(convState.activeId).toBe('');
  });
});
