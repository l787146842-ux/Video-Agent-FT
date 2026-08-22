/**
 * 排队消息持久化存储层测试：旧格式条目的结构归一化。
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { registerQueueStorageKey, loadQueue } from '../queue-storage';

const KEY = 'ftdyb.queued.p1.conv-q';

describe('loadQueue 结构归一化', () => {
  beforeEach(() => {
    localStorage.clear();
    registerQueueStorageKey(() => KEY);
  });

  it('旧格式条目（无 parts/displayText 键）恢复时补齐默认值', () => {
    localStorage.setItem(KEY, JSON.stringify([{ id: 'q-old', text: '旧格式排队' }]));
    expect(loadQueue()).toEqual([
      { id: 'q-old', text: '旧格式排队', displayText: '旧格式排队', parts: [] },
    ]);
  });

  it('新格式条目原样通过（parts/displayText 不被覆盖）', () => {
    const entry = { id: 'q1', text: '正文', displayText: '正文 [图×1]', parts: [{ type: 'text', text: '正文' }] };
    localStorage.setItem(KEY, JSON.stringify([entry]));
    expect(loadQueue()).toEqual([entry]);
  });
});
