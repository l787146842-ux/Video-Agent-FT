/**
 * GateWarnings 组件测试（P4-19 前端回归防护：只加测试不改行为）。
 *
 * 钉死契约：
 * ① 闸机拦截明细结构化判定（trace.gates ok=false），不靠文案匹配；
 * ② 同款拦截（同层/同规则/同文案）合并计数 ×N 折叠防刷屏；
 * ③ 「本次放行」按钮仅在 isGateTarget（最新一条）且有拦截记录时挂载，
 *    点击经系统动作形态发送（gate_overrides + system_action 留痕）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { GateWarnings, gateRecordsOf } from '../right-panel/GateWarnings';
import type { ChatMessage } from '@/types';

const sendMock = vi.fn();
vi.mock('@/lib/agent-actions', () => ({
  sendUserMessage: (input: unknown, opts?: unknown) => {
    sendMock(input, opts);
    return Promise.resolve(true);
  },
}));

type Gate = { rule_id: string; layer: string; ok: boolean; message?: string; skill_name?: string };

/** 构造携带结构化闸机判定的消息 */
function gatedMsg(gates: Gate[], extra?: Partial<ChatMessage>): ChatMessage {
  return {
    sender: 'agent',
    text: '写入被拦截',
    trace: { steps: [{ step: 1, gates }] },
    ...extra,
  } as ChatMessage;
}

describe('gateRecordsOf 结构化判定', () => {
  it('只收集 ok=false 的闸机条目（ok=true 放行不告警）', () => {
    const msg = gatedMsg([
      { rule_id: 'spec.min_length', layer: 'platform', ok: false, message: '长度不足' },
      { rule_id: 'skill.tone', layer: 'skill', ok: true, skill_name: '短剧' },
      { rule_id: 'skill.min_length', layer: 'skill', ok: false, message: '过短', skill_name: '短剧' },
    ]);
    const recs = gateRecordsOf(msg);
    expect(recs.map((r) => r.rule_id)).toEqual(['spec.min_length', 'skill.min_length']);
    expect(recs[1].skill_name).toBe('短剧');
  });

  it('无 trace / 无 gates → 空记录', () => {
    expect(gateRecordsOf({ sender: 'agent', text: '普通回复' })).toEqual([]);
    expect(gateRecordsOf(gatedMsg([]))).toEqual([]);
  });
});

describe('GateWarnings 同款拦截合并 ×N', () => {
  it('相同（层/规则/文案）合并计数折叠，不同款分行', () => {
    const same: Gate = { rule_id: 'skill.min_length', layer: 'skill', ok: false, message: '过短', skill_name: '短剧' };
    const msg = gatedMsg([same, { ...same }, { ...same },
      { rule_id: 'platform.deny', layer: 'platform', ok: false, message: '平台拦截' }]);
    const { container } = render(() => <GateWarnings message={msg} />);
    // 折叠摘要：4 条合并为 2 类（locale: rp.msg.gateCollapseSummary）
    const summary = container.querySelector('.msg-gate-collapse-summary');
    expect(summary?.textContent).toContain('4');
    expect(summary?.textContent).toContain('2');
    const rows = container.querySelectorAll('.gate-chip-row');
    expect(rows.length).toBe(2);
    // 同款行带 ×3 计数角标；单条行不带
    const counts = container.querySelectorAll('.gate-chip-count');
    expect(counts.length).toBe(1);
    expect(counts[0].textContent).toBe('×3');
    // 结构化来源标注：平台 vs Skill『xxx』
    expect(container.textContent).toContain('平台');
    expect(container.textContent).toContain('Skill『短剧』');
  });

  it('单组拦截默认展开（details open），多组默认折叠', () => {
    const one = gatedMsg([{ rule_id: 'a', layer: 'platform', ok: false, message: 'x' }]);
    const single = render(() => <GateWarnings message={one} />);
    expect((single.container.querySelector('details') as HTMLDetailsElement).open).toBe(true);
    const two = gatedMsg([
      { rule_id: 'a', layer: 'platform', ok: false, message: 'x' },
      { rule_id: 'b', layer: 'platform', ok: false, message: 'y' },
    ]);
    const multi = render(() => <GateWarnings message={two} />);
    expect((multi.container.querySelector('details') as HTMLDetailsElement).open).toBe(false);
  });

  it('普通 warnings（非闸机）逐行渲染，无折叠块', () => {
    const msg: ChatMessage = { sender: 'agent', text: 'x', warnings: ['供应商降级', '注意时长'] };
    const { container } = render(() => <GateWarnings message={msg} />);
    expect(container.querySelectorAll('.msg-warning-line').length).toBe(2);
    expect(container.querySelector('.msg-gate-collapse')).toBeNull();
  });

  it('无警告也无拦截 → 整体不渲染', () => {
    const { container } = render(() => <GateWarnings message={{ sender: 'agent', text: 'x' }} />);
    expect(container.querySelector('.msg-warnings')).toBeNull();
  });
});

describe('GateWarnings 「本次放行」挂载（仅最新一条）', () => {
  const blocked = gatedMsg([{ rule_id: 'a', layer: 'platform', ok: false, message: 'x' }]);

  beforeEach(() => sendMock.mockClear());

  it('isGateTarget=true 且有拦截记录 → 挂载放行按钮；点击经系统动作发送', async () => {
    const { container } = render(() => <GateWarnings message={blocked} isGateTarget />);
    const btn = container.querySelector('.gate-override-btn') as HTMLButtonElement;
    expect(btn).toBeTruthy();
    await fireEvent.click(btn);
    expect(sendMock).toHaveBeenCalledTimes(1);
    const [text, opts] = sendMock.mock.calls[0];
    expect(text).toContain('放行');
    expect(opts).toMatchObject({ gateOverrides: ['all'], systemAction: 'system_action' });
  });

  it('isGateTarget=false（旧消息）→ 不挂按钮（放行目标仅最新一条）', () => {
    const { container } = render(() => <GateWarnings message={blocked} isGateTarget={false} />);
    expect(container.querySelector('.gate-override-btn')).toBeNull();
  });

  it('无拦截记录（仅普通 warnings）→ 即使 isGateTarget 也不挂按钮', () => {
    const msg: ChatMessage = { sender: 'agent', text: 'x', warnings: ['普通警告'] };
    const { container } = render(() => <GateWarnings message={msg} isGateTarget />);
    expect(container.querySelector('.gate-override-btn')).toBeNull();
  });
});
