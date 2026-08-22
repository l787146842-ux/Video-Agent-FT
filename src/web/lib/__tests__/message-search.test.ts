/**
 * 消息搜索与轮次跳转派生测试：
 * ① searchMessages——大小写不敏感、正文/文档卡双通道、摘录裁剪、命中上限；
 * ② turnJumpEntries——每轮一条（问/答），标签为组首摘录且长度封顶。
 */
import { describe, it, expect } from 'vitest';
import { searchMessages, turnJumpEntries } from '@/lib/message-search';
import type { ChatMessage } from '@/types';

const u = (text: string): ChatMessage => ({ sender: 'user', text });
const a = (text: string, extra?: Partial<ChatMessage>): ChatMessage =>
  ({ sender: 'agent', text, ...extra });

describe('searchMessages 消息搜索', () => {
  it('空白查询一律返回空（trim 后判空）', () => {
    expect(searchMessages([u('你好')], '')).toEqual([]);
    expect(searchMessages([u('你好')], '   ')).toEqual([]);
  });

  it('大小写不敏感命中正文，返回原数组下标与发送方', () => {
    const hits = searchMessages([u('随便聊聊'), a('Hello World'), u('hello 再来')], 'HELLO');
    expect(hits.map((h) => h.index)).toEqual([1, 2]);
    expect(hits[0].sender).toBe('agent');
    expect(hits[0].snippet).toContain('Hello World');
  });

  it('文档卡名同样参与匹配（无正文的卡片也能搜到）', () => {
    const hits = searchMessages([a('', { docCard: '分镜脚本.md' })], '分镜');
    expect(hits.length).toBe(1);
    expect(hits[0].snippet).toContain('分镜脚本.md');
  });

  it('长文本摘录以命中点为中心，越界侧加省略号', () => {
    const text = `前缀${'甲'.repeat(40)}目标词${'乙'.repeat(40)}`;
    const hits = searchMessages([u(text)], '目标词');
    expect(hits[0].snippet.startsWith('…')).toBe(true);
    expect(hits[0].snippet.endsWith('…')).toBe(true);
    expect(hits[0].snippet).toContain('目标词');
  });

  it('命中数封顶 limit（超长会话不全量返回）', () => {
    const msgs = Array.from({ length: 10 }, (_, i) => u(`关键词消息${i}`));
    expect(searchMessages(msgs, '关键词', 3).length).toBe(3);
  });
});

describe('turnJumpEntries 轮次跳转条目', () => {
  it('每轮一条：用户组=问、agent 组=答，下标为组首', () => {
    const entries = turnJumpEntries([
      u('帮我写开场白'),
      a('好的', { turnId: 't1' }),
      a('', { docCard: '稿子.md', turnId: 't1' }),
      u('再改短一点'),
      a('已精简', { turnId: 't2' }),
    ]);
    expect(entries.map((e) => e.kind)).toEqual(['ask', 'answer', 'ask', 'answer']);
    expect(entries.map((e) => e.index)).toEqual([0, 1, 3, 4]);
    expect(entries[0].label).toBe('帮我写开场白');
  });

  it('答组标签回落组首文档卡名（正文为空的卡片轮）', () => {
    const entries = turnJumpEntries([u('出个文档'), a('', { docCard: '规格.md', turnId: 't1' })]);
    expect(entries[1]).toEqual({ index: 1, kind: 'answer', label: '规格.md' });
  });

  it('标签长度封顶（超长正文取前段加省略号）', () => {
    const long = '长'.repeat(60);
    const entries = turnJumpEntries([u(long)]);
    expect(entries[0].label.length).toBeLessThanOrEqual(27);
    expect(entries[0].label.endsWith('…')).toBe(true);
  });

  it('空白消息与空会话不产出条目', () => {
    expect(turnJumpEntries([])).toEqual([]);
    expect(turnJumpEntries([u(''), a('')] as ChatMessage[])).toEqual([]);
  });
});
