/**
 * 消息交互派生层测试（审核整改批 3：P8 收敛）。
 *
 * 钉死 deriveAffordances 的判定语义（自 ChatFeed 原样归位，零行为变更）：
 * 确认卡目标（doc 卡追加不顶掉）、闸机放行目标（结构化判定）、
 * 建议动作目标（新用户消息即失效）、暂停卡生命周期与已回应所选值。
 */
import { describe, expect, it } from 'vitest';
import { deriveAffordances } from '../message-affordances';
import type { ChatMessage } from '@/types';

const user = (text: string, extra?: Partial<ChatMessage>): ChatMessage =>
  ({ sender: 'user', text, ...extra });
const agent = (text: string, extra?: Partial<ChatMessage>): ChatMessage =>
  ({ sender: 'agent', text, ...extra });

describe('deriveAffordances — 确认卡目标', () => {
  it('最后一条 confirm 消息在用户消息之后 → active 目标', () => {
    const msgs = [user('开始'), agent('分析完成', { confirm: '请确认' })];
    const aff = deriveAffordances(msgs, false);
    expect(aff[1].confirmTarget).toBe(true);
    expect(aff[1].confirmState).toBe('active');
    expect(aff[0].confirmState).toBe('none');
  });

  it('doc 卡追加在确认之后不顶掉引导按钮（确认目标仍是确认消息）', () => {
    const msgs = [
      user('开始'),
      agent('完成', { confirm: '请确认', turnId: 't1' }),
      agent('', { docCard: 'Final_Video_Spec.md', turnId: 't1' }),
    ];
    const aff = deriveAffordances(msgs, false);
    expect(aff[1].confirmTarget).toBe(true);
    expect(aff[2].confirmTarget).toBe(false);
  });

  it('confirm 出现在最后一条用户消息之前 → 不再可操作（无 active）', () => {
    const msgs = [agent('旧确认', { confirm: '请确认' }), user('继续')];
    const aff = deriveAffordances(msgs, false);
    expect(aff[0].confirmTarget).toBe(false);
    expect(aff[0].confirmState).toBe('answered');
  });

  it('流式中不挂确认目标', () => {
    const msgs = [user('开始'), agent('完成', { confirm: '请确认' })];
    const aff = deriveAffordances(msgs, true);
    expect(aff[1].confirmTarget).toBe(false);
  });
});

describe('deriveAffordances — 暂停卡生命周期', () => {
  it('旧确认卡被新暂停取代 → expired；新卡 active', () => {
    const msgs = [
      agent('旧', { confirm: '旧确认' }),
      agent('新', { confirm: '新确认' }),
    ];
    const aff = deriveAffordances(msgs, false);
    expect(aff[0].confirmState).toBe('expired');
    expect(aff[1].confirmState).toBe('active');
  });

  it('已回应所选值：结构化优先（pauseAnsweredId 匹配）', () => {
    const msgs = [
      agent('', { confirm: '选风格', pauseId: 'p1', confirmOptions: [{ label: '写实' }] }),
      user('写实', { pauseAnsweredId: 'p1', pauseAnsweredValue: '写实' }),
    ];
    const aff = deriveAffordances(msgs, false);
    expect(aff[0].confirmState).toBe('answered');
    expect(aff[0].answeredValue).toBe('写实');
  });

  it('已回应所选值：旧消息回落文本匹配；系统动作行不构成回应', () => {
    const msgs = [
      agent('', { confirm: '选风格' }),
      user('本次放行', { kind: 'system_action' }),
      user('写实'),
    ];
    const aff = deriveAffordances(msgs, false);
    expect(aff[0].confirmState).toBe('answered');
    expect(aff[0].answeredValue).toBe('写实');
  });
});

describe('deriveAffordances — 闸机放行目标', () => {
  const gated = (ok: boolean): ChatMessage => agent('被拦', {
    trace: { steps: [{ step: 1, gates: [{ rule_id: 'skill.min_length', layer: 'skill', ok }] }] },
  } as Partial<ChatMessage>);

  it('最后一条含 ok=false 闸机判定的消息挂放行目标（结构化，不靠文案）', () => {
    const msgs = [user('写'), gated(false), agent('后续正文')];
    const aff = deriveAffordances(msgs, false);
    expect(aff[1].gateTarget).toBe(true);
    expect(aff[2].gateTarget).toBe(false);
  });

  it('闸机全过 → 无放行目标', () => {
    const msgs = [user('写'), gated(true)];
    const aff = deriveAffordances(msgs, false);
    expect(aff.every((a) => !a.gateTarget)).toBe(true);
  });
});

describe('deriveAffordances — 建议动作目标', () => {
  it('最后一条带 suggestedActions 的消息为目标；新用户消息使其失效', () => {
    const msgs = [
      agent('出错', { suggestedActions: [{ kind: 'retry', label: '重试', value: '' }] }),
    ];
    expect(deriveAffordances(msgs, false)[0].suggestedTarget).toBe(true);
    const msgs2 = [...msgs, user('换个方式')];
    expect(deriveAffordances(msgs2, false)[0].suggestedTarget).toBe(false);
  });

  it('同轮 agent 派生条目（doc 卡）不构成建议动作失效', () => {
    const msgs = [
      agent('完成', {
        turnId: 't1',
        suggestedActions: [{ kind: 'next', label: '下一步', value: '继续下一步' }],
      }),
      agent('', { docCard: 'A.md', turnId: 't1' }),
    ];
    expect(deriveAffordances(msgs, false)[0].suggestedTarget).toBe(true);
  });
});

describe('deriveAffordances — 形状契约', () => {
  it('输出与消息等长同序；answeredValue 仅 answered 态非空', () => {
    const msgs = [user('一'), agent('二'), agent('三', { confirm: '确认' })];
    const aff = deriveAffordances(msgs, false);
    expect(aff.length).toBe(3);
    expect(aff.every((a) => typeof a.answeredValue === 'string')).toBe(true);
    expect(aff[2].answeredValue).toBe('');
  });
});
