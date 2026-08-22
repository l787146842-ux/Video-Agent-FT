/**
 * chat store 视频结果内联预览卡测试（任务 #10）
 * 数据通路：done payload 的 chat_inserts 中 kind=video 项 → videoCard 消息。
 * 自 chat.test.ts 拆出（控制单文件 ≤250 行红线）。
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { chatState, chatActions } from '../chat';

describe('finishStream 视频卡派生（chat_inserts kind=video）', () => {
  beforeEach(() => {
    chatActions.loadMessages([]);
    chatActions.setInput('');
  });

  it('携带视频插入时落 videoCard 消息（同轮 turnId，只收合法项）', () => {
    chatActions.startStream();
    chatActions.finishStream({
      text: '视频已生成',
      elapsed_ms: 1000,
      steps: 1,
      applied_actions: 0,
      turn_id: 'turn-video',
      chat_inserts: [
        { kind: 'video', url: '/media/v1.mp4', name: '开场.mp4', thumb: '/media/v1.jpg' },
        { kind: 'image', url: '/media/i1.png', name: 'i1.png' },
        { kind: 'video', url: '', name: '' },
      ],
    });
    const vids = chatState.messages.filter((m) => m.videoCard);
    expect(vids.length).toBe(1);
    expect(vids[0].turnId).toBe('turn-video');
    // 只收 kind=video 且 url 非空的项；image 项不进入视频卡
    expect(vids[0].videoCard?.items).toEqual([
      { url: '/media/v1.mp4', name: '开场.mp4', thumb: '/media/v1.jpg' },
    ]);
  });

  it('无视频插入时不产生 videoCard 消息', () => {
    chatActions.startStream();
    chatActions.finishStream({
      text: '纯文本',
      elapsed_ms: 100,
      steps: 1,
      applied_actions: 0,
      chat_inserts: [{ kind: 'audio', url: '/x', name: 'x' }],
    });
    expect(chatState.messages.filter((m) => m.videoCard).length).toBe(0);
  });
});
