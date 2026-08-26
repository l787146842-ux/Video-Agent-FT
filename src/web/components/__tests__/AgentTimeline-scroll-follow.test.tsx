/**
 * 批次G 断言③（前端体验规范 §二 深度思考视窗 / 台账 #8）：
 * 流式思考视窗自动跟随的分支断言——
 * ① 用户停在底部附近（距底 <60px）时新思考内容自动跟随滚到底；
 * ② 用户上滚查看历史（距底 ≥60px）时新内容不打断、不强制拉底。
 * jsdom 布局恒为 0：几何经 defineProperty 注入，rAF 同步执行使分支确定性。
 */
import { render } from '@solidjs/testing-library';
import { createSignal } from 'solid-js';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { AgentTimeline } from '../right-panel/AgentTimeline';

/** 给思考视窗注入可度量几何（沿用 ChatFeed.test.tsx 同口径） */
function mockGeometry(el: HTMLElement, scrollHeight: number, clientHeight: number) {
  Object.defineProperty(el, 'scrollHeight', { configurable: true, value: scrollHeight });
  Object.defineProperty(el, 'clientHeight', { configurable: true, value: clientHeight });
}

describe('深度思考视窗「停在底部才跟随」分支（台账 #8）', () => {
  beforeEach(() => {
    // rAF 回调同步执行：跟随分支在信号更新后立即落断言，无需等帧
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { cb(0); return 0; });
  });
  afterEach(() => vi.unstubAllGlobals());

  /** live 相位 + 响应式 reasoning（模拟流式思考逐字到达） */
  function setup() {
    const [reasoning, setReasoning] = createSignal('第一行思考');
    const { container } = render(() => (
      <AgentTimeline reasoning={reasoning} items={[]} phase="live" />
    ));
    const win = container.querySelector('.tl-reasoning-live') as HTMLElement;
    expect(win).toBeTruthy();
    mockGeometry(win, 1000, 200);
    return { setReasoning, win };
  }

  it('停在底部（距底 <60px）：新思考到达自动跟随滚到底', () => {
    const { setReasoning, win } = setup();
    win.scrollTop = 800; // 1000-200 → 距底 0，贴底
    setReasoning('第二行思考到达');
    expect(win.scrollTop).toBe(1000);
  });

  it('上滚查看历史（距底 ≥60px）：新思考到达不强制拉底', () => {
    const { setReasoning, win } = setup();
    win.scrollTop = 0; // 距底 800，远超 60px 阈值
    setReasoning('第二行思考到达');
    expect(win.scrollTop).toBe(0);
  });

  it('边界：距底恰 59px 仍跟随（<60px 阈值内）', () => {
    const { setReasoning, win } = setup();
    win.scrollTop = 1000 - 200 - 59; // 距底 59 < 60
    setReasoning('第二行思考到达');
    expect(win.scrollTop).toBe(1000);
  });
});
