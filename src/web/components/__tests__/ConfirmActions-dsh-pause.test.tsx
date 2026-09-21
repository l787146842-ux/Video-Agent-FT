/**
 * 暂停提问结构对齐 dsh（2026-09-21 批B，事故 5555/Q4）。
 *
 * 翻案 2026-08-31「卡问句系统组装」：问句改由**模型撰写**（对齐 dsh
 * `ask_user_question` 的 question/header/detail），后端经 done payload 的
 * pause_header / pause_detail / pause_multi_select 下发，前端按此渲染。
 *
 * 钉死契约：
 * ① 题面 = msg.confirm（后端 question 字段落此）——模型问句直达题面行；
 * ② pauseHeader 非空 → 短标题独立成行，且在题面之前；
 * ③ pauseDetail 非空 → 说明文本成行，**不变成可选项**（选项数不因它变化）；
 * ④ 两者缺省 → 不渲染空行（防历史消息/旧卡出现空白标题）。
 */
/// <reference types="node" />
import { render } from '@solidjs/testing-library';
import { describe, it, expect, vi } from 'vitest';
import { ConfirmActions } from '../right-panel/ConfirmActions';
import type { ChatMessage } from '@/types';

vi.mock('@/lib/agent-actions', () => ({
  sendUserMessage: () => Promise.resolve(true),
}));
vi.mock('@/lib/providers', () => ({
  apiProvidersFor: () => [{ id: 'volc', name: '火山引擎' }],
  providerModels: () => ['doubao-seed'],
}));

function pauseMessage(extra: Partial<ChatMessage> = {}): ChatMessage {
  return {
    sender: 'agent',
    text: '',
    confirm: '角色三视图的卡应由哪个阶段构建？',
    pauseId: 'pause_dsh',
    confirmOptions: [{ label: '由 write_media_prompt 建', value: 'wmp' }],
    ...extra,
  };
}

describe('批B：暂停提问结构对齐 dsh ask_user_question', () => {
  it('模型撰写的问句直达题面行（不再被系统模板取代）', () => {
    const { container } = render(() => <ConfirmActions message={pauseMessage()} />);
    // ① 题面 = msg.confirm（后端 question 落此），且不含系统模板话术
    const q = container.querySelector('.confirm-wizard-question');
    expect(q?.textContent).toBe('角色三视图的卡应由哪个阶段构建？');
    expect(q?.textContent).not.toContain('请过目以上成果');
  });

  it('pauseHeader 渲染为短标题，且排在题面之前', () => {
    const { container } = render(() => (
      <ConfirmActions message={pauseMessage({ pauseHeader: '确认' })} />
    ));
    const header = container.querySelector('.confirm-wizard-header');
    expect(header?.textContent).toBe('确认');
    // DOM 顺序：短标题 → 题面（标题在问句上方）
    const wizard = container.querySelector('.confirm-wizard')!;
    const cls = Array.from(wizard.children).map((el) => el.classList[0]);
    expect(cls.indexOf('confirm-wizard-header')).toBeLessThan(
      cls.indexOf('confirm-wizard-question'),
    );
  });

  it('pauseDetail 渲染为说明文本，且不变成可选项', () => {
    const { container } = render(() => (
      <ConfirmActions message={pauseMessage({ pauseDetail: '这会决定后续所有镜头的基调。' })} />
    ));
    expect(container.querySelector('.confirm-wizard-detail')?.textContent)
      .toBe('这会决定后续所有镜头的基调。');
    // 关键：说明不进选项区（dsh detail 语义 = 只作说明）
    const labels = Array.from(container.querySelectorAll('.confirm-option-label'))
      .map((el) => el.textContent);
    expect(labels).toEqual(['由 write_media_prompt 建']);
    expect(labels).not.toContain('这会决定后续所有镜头的基调。');
  });

  it('两字段缺省时不渲染空标题/空说明（防旧卡出现空白行）', () => {
    const { container } = render(() => <ConfirmActions message={pauseMessage()} />);
    expect(container.querySelector('.confirm-wizard-header')).toBeNull();
    expect(container.querySelector('.confirm-wizard-detail')).toBeNull();
  });

  it('空白字符串等同缺省（不渲染空行）', () => {
    const { container } = render(() => (
      <ConfirmActions message={pauseMessage({ pauseHeader: '   ', pauseDetail: '' })} />
    ));
    expect(container.querySelector('.confirm-wizard-header')).toBeNull();
    expect(container.querySelector('.confirm-wizard-detail')).toBeNull();
  });

  it('多组向导分支同样渲染短标题与说明', () => {
    const { container } = render(() => (
      <ConfirmActions message={pauseMessage({
        pauseHeader: '选择模式',
        pauseDetail: '影响全部后续镜头。',
        confirmOptions: [
          { label: '写实', value: 'a', group: '画风' },
          { label: '16:9', value: 'b', group: '画幅' },
        ],
      })} />
    ));
    expect(container.querySelector('.confirm-wizard-header')?.textContent).toBe('选择模式');
    expect(container.querySelector('.confirm-wizard-detail')?.textContent).toBe('影响全部后续镜头。');
  });
});
