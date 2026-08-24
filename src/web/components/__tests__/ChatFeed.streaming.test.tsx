/**
 * ChatFeed 流式块测试（F2 阶段一：流式块消费归一后的本轮账本 turnLedger）。
 *
 * 从 ChatFeed.test.tsx 拆出（前端物理行数 250 红线）；AgentTimeline 走真实组件
 * 以钉死 live 时间线 DOM（.tl-reasoning-live），消息卡仍走轻量 mock。
 */
import { render } from '@solidjs/testing-library';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { ChatFeed } from '../right-panel/ChatFeed';
import { chatState, chatActions, setChatState } from '@/stores/chat';
import type { ChatMessage } from '@/types';

vi.mock('../right-panel/ChatMessageItem', () => ({
  ChatMessageItem: (props: { message: ChatMessage }) => (
    <div class="mock-msg">{props.message.text || ''}</div>
  ),
}));
vi.mock('../right-panel/StreamingBubble', () => ({ StreamingBubble: () => <div class="mock-streaming" /> }));
vi.mock('../right-panel/StreamingIndicator', () => ({ StreamingIndicator: () => <div class="mock-indicator" /> }));

/** 重置全局聊天状态（含流式字段） */
function resetChat(msgs: ChatMessage[] = []) {
  chatActions.loadMessages(msgs);
  chatActions.clearStreaming();
  setChatState('queuedMessages', []);
}

describe('ChatFeed 流式块（消费归一后的本轮账本 turnLedger，F2 阶段一）', () => {
  beforeEach(() => resetChat());

  it('流式中：思考文本与工具账目经 turnLedger 进时间线（DOM 结构/类名不变）', () => {
    const { container } = render(() => <ChatFeed />);
    chatActions.startStream('m');
    chatActions.appendReasoning('深度思考片段');
    chatActions.toolStarted('t1', 'script_analyze', '分析剧本');
    chatActions.toolFinished('t1', true, 800, '分析完成');
    const timeline = container.querySelector('.chat-msg.agent .agent-timeline');
    expect(timeline).toBeTruthy();
    expect(timeline?.textContent).toContain('深度思考片段');
    expect(timeline?.textContent).toContain('分析剧本');
    // 状态栏文案（liveStatus）进操作面板标题（已完成 N 项）
    expect(timeline?.textContent).toContain('已完成 1 项');
  });

  it('finishStream 后流式块收起，账目随相位翻转消息常驻（不重复展示）', () => {
    const { container } = render(() => <ChatFeed />);
    chatActions.startStream('m');
    chatActions.toolStarted('t1', 'gen', '生图');
    chatActions.toolFinished('t1', true, 500);
    chatActions.finishStream({ text: '完成', elapsed_ms: 900, steps: 1, applied_actions: 0 });
    // 流式块（带 live 时间线的临时 agent 容器）不再渲染
    expect(container.querySelector('.tl-reasoning-live')).toBeNull();
    // 翻转后的 settled 账目仍在消息时间线可见（本测试 ChatMessageItem 为 mock，
    // 只钉流式块收起；消息侧账目消费由 ChatMessageItem 自身测试钉死）
    expect(container.querySelectorAll('.mock-msg').length).toBe(1);
  });
});

// 防止未使用告警：chatState 由被测组件消费，测试仅经 chatActions 驱动
void chatState;
