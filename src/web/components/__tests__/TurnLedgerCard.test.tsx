/**
 * TurnLedgerCard 组件测试（F2 阶段二：轮次账本卡渲染统一）。
 *
 * 钉死契约：
 * ① live 相位：时间线走运行装饰形态（.tl-reasoning-live、面板默认展开、
 *    liveStatus 进操作面板标题），不渲染 settled 专属的阶段完成卡；
 * ② settled 相位：同构 .agent-timeline 面板（默认折叠、无 live 视窗），
 *    账目消费账本数据，thinkingMs 角标呈现；
 * ③ settled 相位挂载阶段完成卡（msg.confirm）与已回应「当时所选」标注，
 *    且顺序保持阶段卡 → 标注 → 时间线（相位翻转不重排）。
 * ④ 批次B账本翻转淡入：settled 新挂载卡片挂 ledger-fade-in 淡入类
 *    （120ms opacity 0→1，CSS 归 chat-cards.css）；prefers-reduced-motion
 *    reduce 时不挂类（jsdom 以 matchMedia mock 真实断言）。
 */
/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { render } from '@solidjs/testing-library';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { TurnLedgerCard } from '../right-panel/TurnLedgerCard';
import type { TurnLedger } from '@/lib/turn-ledger';
import type { ChatMessage } from '@/types';

function ledger(extra?: Partial<TurnLedger>): TurnLedger {
  return {
    phase: 'settled',
    reasoning: '账本思考',
    items: [{ id: 't1', summary: '分析剧本', status: 'done', elapsed_ms: 800 }],
    statusText: '',
    reasoningStartMs: 0,
    reasoningEndMs: 0,
    ...extra,
  };
}

describe('TurnLedgerCard live 相位', () => {
  it('时间线走运行装饰形态：live 视窗 + 面板默认展开 + liveStatus 进标题', () => {
    const led = ledger({ phase: 'live', statusText: '正在生图' });
    const { container } = render(() => (
      <TurnLedgerCard phase="live" ledger={() => led} />
    ));
    const timeline = container.querySelector('.agent-timeline');
    expect(timeline).toBeTruthy();
    expect(container.querySelector('.tl-reasoning-live')).toBeTruthy();
    // liveStatus 为具体动作 → 标题「动作（已完成 N 项）」
    expect(timeline?.textContent).toContain('正在生图（已完成 1 项）');
    // live 相位不渲染 settled 专属件
    expect(container.querySelector('.stage-card')).toBeNull();
    expect(container.querySelector('.answered-options')).toBeNull();
  });
});

describe('TurnLedgerCard settled 相位', () => {
  it('同构面板定型形态：默认折叠、无 live 视窗、账目与思考角标呈现', () => {
    const led = ledger({ thinkingMs: 2400 });
    const { container } = render(() => (
      <TurnLedgerCard phase="settled" ledger={() => led} />
    ));
    const timeline = container.querySelector('.agent-timeline');
    expect(timeline).toBeTruthy();
    expect(timeline?.textContent).toContain('账本思考');
    expect(timeline?.textContent).toContain('分析剧本');
    expect(container.querySelector('.tl-reasoning-live')).toBeNull();
    // settled 面板初始折叠（与 live 默认展开相对）
    const panels = Array.from(container.querySelectorAll('.tl-panel'));
    panels.forEach((p) => expect(p.classList.contains('expanded')).toBe(false));
    // thinkingMs 角标（账本携带）
    expect(container.querySelector('.tl-panel-elapsed')?.textContent).toContain('2.4s');
  });

  it('msg.confirm 挂阶段完成卡；已回应标注已移除（批K 迁到用户气泡）', () => {
    const msg = {
      sender: 'agent',
      text: '',
      confirm: '请确认规格',
      confirmOptions: [{ label: '确认，继续' }, { label: '我要调整' }],
    } as ChatMessage;
    const { container } = render(() => (
      <TurnLedgerCard
        phase="settled"
        ledger={() => ledger()}
        message={() => msg}
        confirmState="answered"
        answeredValue="确认，继续"
      />
    ));
    expect(container.querySelector('.stage-card')?.textContent).toContain('阶段完成');
    // answered/expired 生命周期徽标透传 StageCard
    expect(container.querySelector('.stage-card-badge-stale')).toBeTruthy();
    // 2026-09-21 批K（用户要求）：本卡不再挂「已回应选项对勾区」——
    // 问答回执改在用户气泡内逐问呈现（见 PauseQaBlock / UserBubble）。
    // 移除理由：该区把整排选项重画后用**文字**匹配打勾，多问题时会混在一起、
    // 同名选项互相串；批J 落盘的问题级 answers 已可按 id 精确配对。
    expect(container.querySelector('.answered-options')).toBeNull();
    // DOM 顺序：阶段卡 → 时间线（旧的中间「已回应标注」已不在链上）
    const order = Array.from(container.querySelectorAll('.stage-card, .agent-timeline'))
      .map((el) => el.classList[0]);
    expect(order).toEqual(['stage-card', 'agent-timeline']);
  });

  it('无 confirm 的消息不渲染阶段卡与标注，仅时间线', () => {
    const msg = { sender: 'agent', text: '完成' } as ChatMessage;
    const { container } = render(() => (
      <TurnLedgerCard phase="settled" ledger={() => ledger()} message={() => msg} />
    ));
    expect(container.querySelector('.stage-card')).toBeNull();
    expect(container.querySelector('.answered-options')).toBeNull();
    expect(container.querySelector('.agent-timeline')).toBeTruthy();
  });
});

describe('批次B：账本翻转淡入（settled 新挂载 120ms opacity 淡入）', () => {
  /** jsdom 无 matchMedia，按 reduce 场景 mock（组件读 matches 门控淡入类） */
  function mockMatchMedia(matches: boolean) {
    window.matchMedia = vi.fn().mockReturnValue({
      matches,
      media: '(prefers-reduced-motion: reduce)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }) as unknown as typeof window.matchMedia;
  }

  afterEach(() => {
    vi.restoreAllMocks();
    // 还原为 jsdom 原生缺失态（未 mock 时组件回落允许动画）
    delete (window as { matchMedia?: unknown }).matchMedia;
  });

  it('settled 新挂载：阶段卡/时间线两件根均挂 ledger-fade-in（批K 已回应标注迁出）', () => {
    mockMatchMedia(false);
    const msg = {
      sender: 'agent',
      text: '',
      confirm: '请确认规格',
      confirmOptions: [{ label: '确认，继续' }],
    } as ChatMessage;
    const { container } = render(() => (
      <TurnLedgerCard
        phase="settled"
        ledger={() => ledger()}
        message={() => msg}
        answeredValue="确认，继续"
      />
    ));
    expect(container.querySelector('.stage-card.ledger-fade-in')).toBeTruthy();
    expect(container.querySelector('.agent-timeline.ledger-fade-in')).toBeTruthy();
    // 已回应标注不再属于本卡（批K 迁到用户气泡）
    expect(container.querySelector('.answered-options')).toBeNull();
  });

  it('live 相位不挂淡入类（淡入仅 settled 翻转新挂载面）', () => {
    mockMatchMedia(false);
    const led = ledger({ phase: 'live', statusText: '正在生图' });
    const { container } = render(() => (
      <TurnLedgerCard phase="live" ledger={() => led} />
    ));
    expect(container.querySelector('.ledger-fade-in')).toBeNull();
  });

  it('prefers-reduced-motion reduce：settled 卡片不挂淡入类（opacity 直接呈现）', () => {
    mockMatchMedia(true);
    const msg = {
      sender: 'agent',
      text: '',
      confirm: '请确认规格',
      confirmOptions: [{ label: '确认，继续' }],
    } as ChatMessage;
    const { container } = render(() => (
      <TurnLedgerCard
        phase="settled"
        ledger={() => ledger()}
        message={() => msg}
        answeredValue="确认，继续"
      />
    ));
    // 两件照常渲染，仅淡入类缺席
    expect(container.querySelector('.stage-card')).toBeTruthy();
    expect(container.querySelector('.agent-timeline')).toBeTruthy();
    expect(container.querySelector('.ledger-fade-in')).toBeNull();
    expect(window.matchMedia).toHaveBeenCalledWith('(prefers-reduced-motion: reduce)');
  });

  // CSS 侧钉死（vitest 桩空 CSS 导入，源文件文本断言同 user-select 先例）
  const here = dirname(fileURLToPath(import.meta.url));
  const chatCardsCss = readFileSync(resolve(here, '../../styles/chat-cards.css'), 'utf-8');

  it('chat-cards.css：.ledger-fade-in 走 120ms opacity 淡入动画', () => {
    expect(chatCardsCss).toMatch(/\.ledger-fade-in\s*\{[^}]*animation:\s*ledger-fade-in\s+120ms/s);
    expect(chatCardsCss).toMatch(/@keyframes\s+ledger-fade-in\s*\{[^@]*?from\s*\{\s*opacity:\s*0/s);
  });

  it('chat-cards.css：@media (prefers-reduced-motion: reduce) 下淡入动画禁用', () => {
    expect(chatCardsCss).toMatch(
      /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[^@]*?\.ledger-fade-in\s*\{[^}]*animation:\s*none/s,
    );
  });
});
