import { describe, it, expect, beforeEach } from 'vitest';

/**
 * chat store 流式状态机测试
 * 覆盖：start -> append -> finish / error / cancel
 */

// 直接测试 chatActions 的状态转换逻辑（不依赖 DOM）
// 由于 solid-js store 在 node 环境可用，直接 import
import { chatState, chatActions } from '../chat';

describe('chatActions 流式状态机', () => {
  beforeEach(() => {
    // 重置状态
    chatActions.loadMessages([]);
    chatActions.setInput('');
  });

  it('startStream 设置流式状态', () => {
    chatActions.startStream();
    expect(chatState.isStreaming).toBe(true);
    expect(chatState.streamingText).toBe('');
    expect(chatState.streamingStatus).toBe('正在连接…');
  });

  it('appendDelta 累积文本', () => {
    chatActions.startStream();
    chatActions.appendDelta('你好');
    chatActions.appendDelta('世界');
    expect(chatState.streamingText).toBe('你好世界');
    expect(chatState.streamingStatus).toBe('正在回复…');
  });

  it('finishStream 将结果写入消息列表并清除流式状态', () => {
    chatActions.startStream();
    chatActions.appendDelta('回复内容');
    chatActions.finishStream({
      text: '最终回复',
      elapsed_ms: 1500,
      steps: 2,
      applied_actions: 1,
    });
    expect(chatState.isStreaming).toBe(false);
    expect(chatState.streamingText).toBe('');
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].sender).toBe('agent');
    expect(chatState.messages[0].text).toBe('最终回复');
    expect(chatState.messages[0].meta).toContain('1.5s');
    expect(chatState.messages[0].meta).toContain('2 轮');
  });

  it('streamError 写入错误消息并清除流式状态', () => {
    chatActions.startStream();
    chatActions.streamError('网络超时');
    expect(chatState.isStreaming).toBe(false);
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].text).toContain('网络超时');
  });

  it('cancelStream 保留已有流式文本为消息', () => {
    chatActions.startStream();
    chatActions.appendDelta('部分内容');
    chatActions.cancelStream();
    expect(chatState.isStreaming).toBe(false);
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].text).toBe('部分内容');
    expect(chatState.messages[0].meta).toBe('已停止');
  });

  it('cancelStream 无文本时不产生消息', () => {
    chatActions.startStream();
    chatActions.cancelStream();
    expect(chatState.isStreaming).toBe(false);
    expect(chatState.messages.length).toBe(0);
  });

  it('addMessage 追加用户消息', () => {
    chatActions.addMessage({ sender: 'user', text: '你好' });
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].sender).toBe('user');
  });

  it('loadMessages 替换全部消息', () => {
    chatActions.addMessage({ sender: 'user', text: '旧消息' });
    chatActions.loadMessages([{ sender: 'agent', text: '新消息' }]);
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].text).toBe('新消息');
  });

  // ---------- B0/F1：docCard 双通道去重 ----------

  it('docWritten 即显后 finishStream 不重复渲染同名文档卡', () => {
    chatActions.startStream();
    chatActions.docWritten('大纲.md');
    chatActions.finishStream({
      text: '完成',
      elapsed_ms: 1000,
      steps: 1,
      applied_actions: 0,
      documents_written: ['大纲.md', '规格.md'],
    });
    const docs = chatState.messages.filter((m) => m.docCard);
    expect(docs.map((m) => m.docCard)).toEqual(['大纲.md', '规格.md']);
  });

  it('docWritten 同轮重复名称只渲染一次', () => {
    chatActions.startStream();
    chatActions.docWritten('大纲.md');
    chatActions.docWritten('大纲.md');
    expect(chatState.messages.filter((m) => m.docCard).length).toBe(1);
  });
});
