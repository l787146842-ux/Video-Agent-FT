import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * chat store「继续刚才的任务」建议派生测试（P4-21）
 * 从 chat.test.ts 拆出：cancelStream 派生建议、streamError 报错路径补挂、
 * 点击 retry 机械重发最近用户消息、无用户消息不挂建议
 */
import { chatState, chatActions } from '../chat';
import { resendNearestUserMessage } from '@/lib/resend';
// 机械重发终点 mock（retry 点击 → sendUserMessage；不真起流）
import { sendUserMessage } from '@/lib/agent-actions';

vi.mock('@/lib/agent-actions', () => ({ sendUserMessage: vi.fn(async () => true) }));

describe('chatActions「继续刚才的任务」建议（P4-21：kind=retry 走机械重发）', () => {
  beforeEach(() => {
    // 重置状态
    chatActions.loadMessages([]);
    chatActions.setInput('');
    vi.mocked(sendUserMessage).mockClear();
  });

  it('cancelStream 本地派生「继续刚才的任务」建议', () => {
    chatActions.startStream();
    chatActions.appendDelta('部分内容');
    chatActions.cancelStream();
    const acts = chatState.messages[0].suggestedActions;
    expect(acts).toHaveLength(1);
    expect(acts?.[0].kind).toBe('retry');
    expect(acts?.[0].label).toBe('继续刚才的任务');
  });

  // ---------- P4-21 补：报错/中断路径同语义派生「继续刚才的任务」 ----------

  it('streamError 存在前一条用户消息时派生继续建议（kind/label 与主动停止一致）', () => {
    chatActions.addMessage({ sender: 'user', text: '帮我生成开场' });
    chatActions.startStream();
    chatActions.streamError('BodyStreamBuffer was aborted.', 'raw upstream');
    const err = chatState.messages[1];
    // 错误气泡既有渲染字段不变（人话 + 技术详情折叠）
    expect(err.text).toContain('BodyStreamBuffer was aborted.');
    expect(err.errorDetail).toBe('raw upstream');
    const acts = err.suggestedActions;
    expect(acts).toHaveLength(1);
    expect(acts?.[0].kind).toBe('retry');
    expect(acts?.[0].label).toBe('继续刚才的任务');
  });

  it('streamError 点击 retry 机械重发最近一条用户消息', () => {
    chatActions.addMessage({ sender: 'user', text: '旧问题' });
    chatActions.addMessage({ sender: 'agent', text: '旧回复' });
    chatActions.addMessage({ sender: 'user', text: '新问题' });
    chatActions.startStream();
    chatActions.streamError('供应商流中断');
    // 与 ChatMessageItem.runSuggested 点击 retry 同入口（末条下标起找最近用户消息）
    resendNearestUserMessage(chatState.messages.length - 1);
    expect(sendUserMessage).toHaveBeenCalledTimes(1);
    expect(sendUserMessage).toHaveBeenCalledWith('新问题');
  });

  it('streamError 无用户消息时不挂建议（首轮即报错不无的放矢）', () => {
    chatActions.startStream();
    chatActions.streamError('服务不可用');
    expect(chatState.messages).toHaveLength(1);
    expect(chatState.messages[0].suggestedActions).toBeUndefined();
  });
});
