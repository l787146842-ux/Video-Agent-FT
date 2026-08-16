import { describe, it, expect } from 'vitest';
import { groupTurns, suggestedTargetIndex } from '../turn-groups';
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

  it('六轮 S5/N4a：即显 doc 卡携带事件 turn_id 与主消息严格同组（不依赖兜底）', () => {
    const groups = groupTurns([
      u('写文档'),
      a('t7', { docCard: '规格.md' }), // doc_written 事件打戳先到
      a('t7', { text: '总结' }),       // done 主消息后到
    ]);
    expect(groups.length).toBe(2);
    expect(groups[1].indices).toEqual([1, 2]);
    expect(groups[1].turnId).toBe('t7');
  });
});

/** 六轮 S5/N4c：建议动作按钮挂载边界（锐化后规则） */
const act = { kind: 'retry' as const, label: '重试', value: '' };

describe('suggestedTargetIndex 建议按钮挂载边界', () => {
  it('携带者其后无新消息 → 渲染（返回其下标）', () => {
    const msgs = [u('开工'), a('t1', { text: '空响应', suggestedActions: [act] }), a('t1', { docCard: 'd' })];
    expect(suggestedTargetIndex(msgs, false)).toBe(1);
  });

  it('携带者其后出现新用户消息 → 失效（返回 -1）', () => {
    const msgs = [a('t1', { text: 'x', suggestedActions: [act] }), u('我手动继续了')];
    expect(suggestedTargetIndex(msgs, false)).toBe(-1);
  });

  it('流式进行中 → 不渲染', () => {
    const msgs = [a('t1', { text: 'x', suggestedActions: [act] })];
    expect(suggestedTargetIndex(msgs, true)).toBe(-1);
  });
});
