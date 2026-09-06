/**
 * 消息高度缓存单测：
 * ① 缓存键——同形态同键；ts/meta 等本地易变字段不参与（重载不 miss）；
 * ② 估算——下限/上限钳制、随字数与卡片单调增；
 * ③ 回填——rememberHeight 后 intrinsicSize 命中缓存，±2px 内去重，噪声不入库；
 * ④ 持久化——防抖落盘 localStorage，重置模块后新实例直接命中；
 * ⑤ 降级——无 ResizeObserver 环境返回 no-op 不抛错。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  messageHeightKey, estimateMessageHeight, messageIntrinsicSize,
  rememberHeight, trackMessageHeight,
} from '@/lib/message-heights';
import type { ChatMessage } from '@/types';

function msg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return { sender: 'agent', text: 'hello', ...overrides };
}

beforeEach(() => { localStorage.clear(); });
afterEach(() => { vi.useRealTimers(); });

describe('messageHeightKey 内容形态键', () => {
  it('同形态同键', () => {
    expect(messageHeightKey(msg({ text: 'abc' })))
      .toBe(messageHeightKey(msg({ text: 'abc' })));
  });

  it('ts/meta/appliedActions 等本地易变字段不参与键（重载后不 miss）', () => {
    expect(messageHeightKey(msg({ ts: 111, meta: '1s', appliedActions: 3 })))
      .toBe(messageHeightKey(msg()));
  });

  it('字数/头部/sender/kind/卡片任一不同即不同键', () => {
    expect(messageHeightKey(msg({ text: 'abcd' }))).not.toBe(messageHeightKey(msg({ text: 'abc' })));
    expect(messageHeightKey(msg({ sender: 'user' }))).not.toBe(messageHeightKey(msg()));
    expect(messageHeightKey(msg({ kind: 'system_action' }))).not.toBe(messageHeightKey(msg()));
    expect(messageHeightKey(msg({ imageCard: { image_urls: ['u'] } })))
      .not.toBe(messageHeightKey(msg()));
  });
});

describe('estimateMessageHeight 内容估算', () => {
  it('短消息钳在下限 120（与 CSS 兜底一致）', () => {
    expect(estimateMessageHeight(msg({ text: 'hi' }))).toBe(120);
  });

  it('随字数单调增，超长文本封顶', () => {
    const a = estimateMessageHeight(msg({ text: 'x'.repeat(500) }));
    const b = estimateMessageHeight(msg({ text: 'x'.repeat(5000) }));
    expect(b).toBeGreaterThan(a);
    expect(estimateMessageHeight(msg({ text: 'x'.repeat(500000) }))).toBeLessThanOrEqual(8000);
  });

  it('卡片抬升估算', () => {
    expect(estimateMessageHeight(msg({ docCard: 'doc-1' })))
      .toBeGreaterThan(estimateMessageHeight(msg()));
    expect(estimateMessageHeight(msg({ actionLog: ['a', 'b', 'c'] })))
      .toBeGreaterThan(estimateMessageHeight(msg()));
  });
});

describe('rememberHeight 真实高度回填', () => {
  it('回填后 intrinsicSize 优先命中缓存（高于估算顺位）', () => {
    const m = msg({ text: 'y'.repeat(3000) });
    const key = messageHeightKey(m);
    expect(messageIntrinsicSize(m)).toBe(`auto ${estimateMessageHeight(m)}px`);
    rememberHeight(key, 5000);
    expect(messageIntrinsicSize(m)).toBe('auto 5000px');
  });

  it('±2px 内重复回填去重，低于 40px 视为噪声不入库', () => {
    const key = messageHeightKey(msg({ text: 'z'.repeat(400) }));
    rememberHeight(key, 1000);
    rememberHeight(key, 1000.5);
    expect(messageIntrinsicSize(msg({ text: 'z'.repeat(400) }))).toBe('auto 1000px');
    rememberHeight(key, 10);
    expect(messageIntrinsicSize(msg({ text: 'z'.repeat(400) }))).toBe('auto 1000px');
  });
});

describe('localStorage 持久化', () => {
  it('防抖后落盘；重置模块后新实例直接命中（跨刷新不重跳）', async () => {
    vi.useFakeTimers();
    const m = msg({ text: 'persist'.repeat(100) });
    const key = messageHeightKey(m);
    rememberHeight(key, 2345);
    expect(localStorage.getItem('ftdyb.msg-heights.v1')).toBeNull();
    vi.advanceTimersByTime(700);
    expect(localStorage.getItem('ftdyb.msg-heights.v1')).toContain('2345');

    vi.resetModules();
    const fresh = await import('@/lib/message-heights');
    expect(fresh.messageIntrinsicSize(m)).toBe('auto 2345px');
  });

  it('损坏数据不抛错，降级为纯估算', async () => {
    localStorage.setItem('ftdyb.msg-heights.v1', '{not-json');
    vi.resetModules();
    const fresh = await import('@/lib/message-heights');
    const m = msg({ text: 'w'.repeat(300) });
    expect(fresh.messageIntrinsicSize(m)).toBe(`auto ${fresh.estimateMessageHeight(m)}px`);
  });
});

describe('trackMessageHeight 观察器', () => {
  it('无 ResizeObserver 环境返回 no-op 清理函数不抛错', () => {
    const cleanup = trackMessageHeight(document.createElement('div'), () => 'k');
    expect(typeof cleanup).toBe('function');
    expect(() => cleanup()).not.toThrow();
  });

  it('有 ResizeObserver 时 observe；尺寸回调回填真实高度，无关元素跳过', async () => {
    const cbs: ResizeObserverCallback[] = [];
    const unobserved: Element[] = [];
    class MockRO {
      constructor(cb: ResizeObserverCallback) { cbs.push(cb); }
      observe() { /* 记录省略：触发靠手动调回调 */ }
      unobserve(el: Element) { unobserved.push(el); }
      disconnect() { /* 单例不销毁 */ }
    }
    vi.stubGlobal('ResizeObserver', MockRO);
    vi.resetModules();
    const mod = await import('@/lib/message-heights');
    const m = msg({ text: 'ro'.repeat(200) });
    const el = document.createElement('div');
    el.getBoundingClientRect = () => ({ height: 1500 } as DOMRect);
    const cleanup = mod.trackMessageHeight(el, () => mod.messageHeightKey(m));
    // 回调带目标元素 → 回填；目标不在注册表（foreign）→ 静默跳过
    const foreign = { target: document.createElement('div') } as unknown as ResizeObserverEntry;
    const hit = { target: el } as unknown as ResizeObserverEntry;
    expect(() => cbs[0]([foreign], cbs[0] as never)).not.toThrow();
    cbs[0]([hit], cbs[0] as never);
    expect(mod.messageIntrinsicSize(m)).toBe('auto 1500px');
    cleanup();
    expect(unobserved).toContain(el);
    vi.unstubAllGlobals();
  });
});
