/**
 * ChatFeed 组件测试（P4-19 前端回归防护：只加测试不改行为）。
 *
 * 钉死契约：
 * ① 轮次分组渲染（groupTurns：同 turnId 聚合进 .turn-group，用户消息独立成组）；
 * ② 交互挂载位经 deriveAffordances 派生后按位传给 ChatMessageItem
 *    （确认卡目标 / 闸机放行目标 / 建议动作目标 / 暂停卡生命周期）；
 * ③ 自动滚底阈值（80px）：贴底自动跟随，用户上滚即暂停，回到底部恢复。
 *
 * ChatMessageItem 走轻量 mock（本文件只钉 ChatFeed 的编排职责，
 * 消息卡内部形态由其自身测试/E2E 覆盖）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { ChatFeed } from '../right-panel/ChatFeed';
import { chatState, chatActions, setChatState } from '@/stores/chat';
import type { ChatMessage } from '@/types';

vi.mock('../right-panel/ChatMessageItem', () => ({
  ChatMessageItem: (props: {
    message: ChatMessage; isLast: boolean; isGateTarget?: boolean;
    isSuggestedTarget?: boolean; confirmState?: string; editable?: boolean;
  }) => (
    <div
      class="mock-msg"
      data-sender={props.message.sender}
      data-confirm-target={props.isLast ? '1' : '0'}
      data-gate-target={props.isGateTarget ? '1' : '0'}
      data-suggested-target={props.isSuggestedTarget ? '1' : '0'}
      data-editable={props.editable ? '1' : '0'}
      data-confirm-state={props.confirmState || 'none'}
    >
      {props.message.text || props.message.docCard || ''}
    </div>
  ),
}));
vi.mock('../right-panel/StreamingBubble', () => ({ StreamingBubble: () => <div class="mock-streaming" /> }));
vi.mock('../right-panel/StreamingIndicator', () => ({ StreamingIndicator: () => <div class="mock-indicator" /> }));

const user = (text: string): ChatMessage => ({ sender: 'user', text });
const agent = (text: string, extra?: Partial<ChatMessage>): ChatMessage =>
  ({ sender: 'agent', text, ...extra });

/** 重置全局聊天状态（含流式字段） */
function resetChat(msgs: ChatMessage[]) {
  chatActions.loadMessages(msgs);
  chatActions.clearStreaming();
  setChatState('queuedMessages', []);
}

function msgs(container: HTMLElement) {
  return Array.from(container.querySelectorAll('.mock-msg')) as HTMLElement[];
}

describe('ChatFeed 轮次分组渲染（groupTurns）', () => {
  beforeEach(() => resetChat([]));

  it('同 turnId 的正文/文档卡收进同一 .turn-group；用户消息独立成组', () => {
    const { container } = render(() => <ChatFeed />);
    resetChat([
      user('开始'),
      agent('正文', { turnId: 't1', modelName: '模型A', meta: '耗时 1.0s' }),
      agent('', { docCard: '规格.md', turnId: 't1' }),
      user('再问一次'),
      agent('第二条回复', { turnId: 't2' }),
    ]);
    const groups = container.querySelectorAll('.turn-group');
    expect(groups.length).toBe(2);
    // 组头：模型名 + meta 上提（仅多条/有 meta 时显示）
    const header = groups[0].querySelector('.turn-group-header');
    expect(header?.querySelector('.turn-group-model')?.textContent).toBe('模型A');
    expect(header?.querySelector('.turn-group-meta')?.textContent).toBe('耗时 1.0s');
    // 组内消息顺序不变（原数组下标语义）
    expect(groups[0].querySelectorAll('.mock-msg').length).toBe(2);
  });

  it('无 turnId 的旧消息相邻 agent 条目兜底同组', () => {
    const { container } = render(() => <ChatFeed />);
    resetChat([user('问'), agent('答1'), agent('答2')]);
    expect(container.querySelectorAll('.turn-group').length).toBe(1);
    expect(msgs(container).length).toBe(3);
  });

  it('无消息时展示能力提示（chat-feed-hint），流式中不展示', () => {
    const { container } = render(() => <ChatFeed />);
    expect(container.querySelector('.chat-feed-hint')).toBeTruthy();
    chatActions.startStream('m');
    expect(container.querySelector('.chat-feed-hint')).toBeNull();
  });
});

describe('ChatFeed 交互挂载位（deriveAffordances 派生结果）', () => {
  beforeEach(() => resetChat([]));

  it('确认卡目标挂最后一条用户消息之后的 confirm 消息（生命周期 active）', () => {
    const { container } = render(() => <ChatFeed />);
    resetChat([user('开始'), agent('完成', { confirm: '请确认' })]);
    const items = msgs(container);
    expect(items[1].dataset.confirmTarget).toBe('1');
    expect(items[1].dataset.confirmState).toBe('active');
    expect(items[0].dataset.confirmTarget).toBe('0');
  });

  it('闸机放行目标仅挂最后一条含 ok=false 判定的消息', () => {
    const gated = (rule: string): ChatMessage => agent('拦', {
      trace: { steps: [{ step: 1, gates: [{ rule_id: rule, layer: 'platform', ok: false }] }] },
    } as Partial<ChatMessage>);
    const { container } = render(() => <ChatFeed />);
    resetChat([gated('old'), user('继续'), gated('new'), agent('后续')]);
    const items = msgs(container);
    expect(items.filter((m) => m.dataset.gateTarget === '1').length).toBe(1);
    expect(items[2].dataset.gateTarget).toBe('1');
  });

  it('用户气泡编辑控制点（P4-20）：有正文的用户消息挂 editable，agent/系统动作行不挂', () => {
    const { container } = render(() => <ChatFeed />);
    resetChat([
      user('写一段开场白'),
      agent('好的，正在写'),
      { sender: 'user', text: '本次放行', kind: 'system_action' } as ChatMessage,
    ]);
    const items = msgs(container);
    expect(items[0].dataset.editable).toBe('1');
    expect(items[1].dataset.editable).toBe('0');
    expect(items[2].dataset.editable).toBe('0');
  });

  it('流式中所有挂载位失效（确认/闸机/建议均不挂）', () => {
    const { container } = render(() => <ChatFeed />);
    resetChat([
      user('开始'),
      agent('完成', { confirm: '请确认', suggestedActions: [{ kind: 'retry', label: '重试', value: '' }] }),
    ]);
    chatActions.startStream('m');
    const items = msgs(container);
    items.forEach((m) => {
      expect(m.dataset.confirmTarget).toBe('0');
      expect(m.dataset.gateTarget).toBe('0');
      expect(m.dataset.suggestedTarget).toBe('0');
    });
  });
});

describe('ChatFeed 自动滚底阈值（80px）', () => {
  beforeEach(() => resetChat([]));

  /** 给 feed 元素注入可度量几何（jsdom 布局恒为 0） */
  function mockGeometry(feed: HTMLElement, scrollHeight: number, clientHeight: number) {
    Object.defineProperty(feed, 'scrollHeight', { configurable: true, value: scrollHeight });
    Object.defineProperty(feed, 'clientHeight', { configurable: true, value: clientHeight });
  }
  const nextFrame = () => new Promise<void>((r) => {
    requestAnimationFrame(() => requestAnimationFrame(() => r(undefined)));
  });

  it('贴底时新消息自动滚到底部', async () => {
    const { container } = render(() => <ChatFeed />);
    const feed = container.querySelector('.chat-feed') as HTMLElement;
    mockGeometry(feed, 2000, 400);
    chatActions.addMessage(user('第一条'));
    await nextFrame();
    expect(feed.scrollTop).toBe(2000);
  });

  it('用户上滚（离开底部 ≥80px）后暂停自动滚动；新消息不强制拉底', async () => {
    const { container } = render(() => <ChatFeed />);
    const feed = container.querySelector('.chat-feed') as HTMLElement;
    mockGeometry(feed, 2000, 400);
    await nextFrame(); // 先排空挂载时的初始自动滚底帧，避免其延迟落底干扰断言
    // 用户上滚到顶部（远超 80px 阈值）
    feed.scrollTop = 0;
    fireEvent.scroll(feed);
    chatActions.addMessage(user('新消息'));
    await nextFrame();
    expect(feed.scrollTop).toBe(0);
  });

  it('回到距底 <80px 后恢复自动滚动', async () => {
    const { container } = render(() => <ChatFeed />);
    const feed = container.querySelector('.chat-feed') as HTMLElement;
    mockGeometry(feed, 2000, 400);
    await nextFrame(); // 先排空挂载时的初始自动滚底帧
    feed.scrollTop = 0;
    fireEvent.scroll(feed);
    // 回到底部附近（距底 40px < 80px）
    feed.scrollTop = 2000 - 400 - 40;
    fireEvent.scroll(feed);
    chatActions.addMessage(user('新消息'));
    await nextFrame();
    expect(feed.scrollTop).toBe(2000);
  });
});

// 防止未使用告警：chatState 由被测组件消费，测试仅经 chatActions 驱动
void chatState;
