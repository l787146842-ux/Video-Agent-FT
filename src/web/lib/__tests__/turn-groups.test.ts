import { describe, it, expect } from 'vitest';
import { groupTurns } from '../turn-groups';
import type { ChatMessage } from '@/types';

/** 五轮 S2/#2：轮次分组纯函数（turnId 为主，相邻 agent 兜底） */

const u = (text: string): ChatMessage => ({ sender: 'user', text });
const a = (turnId?: string, extra?: Partial<ChatMessage>): ChatMessage => ({
  sender: 'agent', text: '', turnId, ...extra,
});

describe('groupTurns 轮次分组', () => {
  it('同 turnId 的正文/文档卡/图片卡聚合为一组', () => {
    const groups = groupTurns([
      u('开工'),
      a('t1', { text: '总结' }),
      a('t1', { docCard: '规格.md' }),
      a('t1', { imageCard: { image_urls: ['x.png'] } }),
    ]);
    expect(groups.length).toBe(2);
    expect(groups[0].kind).toBe('user');
    expect(groups[1].kind).toBe('turn');
    expect(groups[1].indices).toEqual([1, 2, 3]);
    expect(groups[1].turnId).toBe('t1');
  });

  it('不同 turnId 不相邻合并（即使中间无用户消息也不误并）', () => {
    const groups = groupTurns([a('t1'), a('t2')]);
    expect(groups.length).toBe(2);
    expect(groups[0].indices).toEqual([0]);
    expect(groups[1].indices).toEqual([1]);
  });

  it('无 turnId 的旧消息按相邻兜底合并', () => {
    const groups = groupTurns([u('q'), a(undefined, { text: '正文' }), a(undefined, { docCard: 'd' })]);
    expect(groups.length).toBe(2);
    expect(groups[1].indices).toEqual([1, 2]);
    expect(groups[1].turnId).toBeUndefined();
  });

  it('用户消息永远独立成组并切断相邻合并', () => {
    const groups = groupTurns([a(undefined), u('再改'), a(undefined)]);
    expect(groups.length).toBe(3);
    expect(groups.map((g) => g.kind)).toEqual(['turn', 'user', 'turn']);
  });

  it('新 turnId 消息与无 turnId 旧消息相邻时兜底合并（过渡期历史混排）', () => {
    const groups = groupTurns([a(undefined, { text: '旧' }), a('t9', { docCard: 'd' })]);
    expect(groups.length).toBe(1);
    expect(groups[0].turnId).toBe('t9');
  });
});
