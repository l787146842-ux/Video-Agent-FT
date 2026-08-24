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
 */
import { render } from '@solidjs/testing-library';
import { describe, it, expect } from 'vitest';
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

  it('msg.confirm 挂阶段完成卡；answeredValue + 选项挂「当时所选」标注（顺序不重排）', () => {
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
    const answered = container.querySelector('.answered-options');
    expect(answered?.querySelector('.answered-option.chosen')?.textContent).toContain('确认，继续');
    // DOM 顺序钉死：阶段卡 → 已回应标注 → 时间线（相位翻转结构同构不重排）
    const order = Array.from(container.querySelectorAll('.stage-card, .answered-options, .agent-timeline'))
      .map((el) => el.classList[0]);
    expect(order).toEqual(['stage-card', 'answered-options', 'agent-timeline']);
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
