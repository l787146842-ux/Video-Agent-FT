/**
 * StageCard 组件测试（覆盖率闸 80% 纳入件）。
 *
 * 钉死契约：
 * ① 卡标题按 pause kind 语义渲染：remind=待补原料 / collect=规格交互 /
 *    其余=阶段标签+「阶段完成」（无标签则仅「阶段完成」）；
 * ② 确认文案与模型正文判重：正文已含同句时卡 body 不再双显；
 * ③ appliedActions 徽标「已执行 N 个操作」；
 * ④ answered/expired 生命周期徽标；
 * ⑤ 展开/折叠点击切换 body 可见性；
 * ⑥ 批次C 判重调位：active 且带选项时题面让位问卷卡三段式①防双显，
 *    无选项暂停与 answered/expired 回看态题面照常呈现；
 * ⑦ 审查修复批：让位须与「问卷卡确实接管题面」同条件——消息同时携带
 *    decisionForm（fields 非空）时不让位（form.message 可能为空，
 *    让位会导致题面消失）。
 * ⑧ D-09 作废态：expired（被新卡取代）旧卡挂 stage-card-void 作废标记类，
 *    且点击头部给明确失效反馈（Toast），不再静默降级为普通文本；
 *    active/answered/none 态不挂作废类、点击不触发失效 Toast。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { StageCard } from '../right-panel/StageCard';
import type { ChatMessage } from '@/types';

// D-09：作废卡点击反馈桩——Toast 不发真实副作用，只记录调用
const toastMock = vi.fn();
vi.mock('@/stores/toast', () => ({
  showToast: (msg: string, kind?: string) => toastMock(msg, kind),
  dismissToast: vi.fn(),
}));

function msg(extra?: Partial<ChatMessage>): ChatMessage {
  return { sender: 'agent', text: '模型正文', ...extra } as ChatMessage;
}

describe('StageCard 标题语义', () => {
  it('kind=remind → 待补原料', () => {
    const { container } = render(() => <StageCard msg={() => msg({ kind: 'remind' })} state="none" />);
    expect(container.querySelector('.stage-card-title')?.textContent).toContain('待补原料');
  });

  it('kind=collect → 规格交互', () => {
    const { container } = render(() => <StageCard msg={() => msg({ kind: 'collect' })} state="none" />);
    expect(container.querySelector('.stage-card-title')?.textContent).toContain('规格交互');
  });

  it('其余 kind 带 trace 阶段标签 → 「标签 · 阶段完成」', () => {
    const m = msg({
      trace: { steps: [{ step: 1, actions: [{ stage: '故事板' }] }] },
    } as Partial<ChatMessage>);
    const { container } = render(() => <StageCard msg={() => m} state="none" />);
    const title = container.querySelector('.stage-card-title')?.textContent || '';
    expect(title).toContain('故事板');
    expect(title).toContain('阶段完成');
  });

  it('无阶段标签 → 仅「阶段完成」', () => {
    const { container } = render(() => <StageCard msg={() => msg()} state="none" />);
    expect(container.querySelector('.stage-card-title')?.textContent).toContain('阶段完成');
  });
});

describe('StageCard 正文判重与展开折叠', () => {
  it('confirm 与正文同句时不双显（body 无概要）', () => {
    const m = msg({ text: '故事板已建立，请审阅', confirm: '故事板已建立，请审阅' });
    const { container } = render(() => <StageCard msg={() => m} state="active" />);
    expect(container.querySelector('.stage-card-summary')).toBeNull();
  });

  it('confirm 与正文不同句时展开显示概要，点击折叠后隐藏', async () => {
    const m = msg({ text: '正文内容', confirm: '请确认规格' });
    const { container } = render(() => <StageCard msg={() => m} state="active" />);
    expect(container.querySelector('.stage-card-summary')?.textContent).toContain('请确认规格');
    // 点击头部折叠：body 收起、aria-expanded 翻转
    const header = container.querySelector('.stage-card-header') as HTMLButtonElement;
    await fireEvent.click(header);
    expect(container.querySelector('.stage-card-body')).toBeNull();
    expect(header.getAttribute('aria-expanded')).toBe('false');
    // 再点展开
    await fireEvent.click(header);
    expect(container.querySelector('.stage-card-summary')?.textContent).toContain('请确认规格');
  });

  it('无 confirm 时不渲染箭头与 body', () => {
    const { container } = render(() => <StageCard msg={() => msg()} state="none" />);
    expect(container.querySelector('.stage-card-arrow')).toBeNull();
    expect(container.querySelector('.stage-card-body')).toBeNull();
  });

  it('批次C 判重调位：active 且带选项时题面让位问卷卡（body 不双显）', () => {
    const m = msg({
      text: '正文内容',
      confirm: '请确认规格',
      confirmOptions: [{ label: '确认，继续' }],
    });
    const { container } = render(() => <StageCard msg={() => m} state="active" />);
    expect(container.querySelector('.stage-card-summary')).toBeNull();
  });

  it('active 无选项暂停题面照常呈现（问卷卡无题面行，无处可让）', () => {
    const m = msg({ text: '正文内容', confirm: '请确认规格' });
    const { container } = render(() => <StageCard msg={() => m} state="active" />);
    expect(container.querySelector('.stage-card-summary')?.textContent).toContain('请确认规格');
  });

  it('answered 回看态题面照常呈现（问卷卡已随非末条卸载）', () => {
    const m = msg({
      text: '正文内容',
      confirm: '请确认规格',
      confirmOptions: [{ label: '确认，继续' }],
    });
    const { container } = render(() => <StageCard msg={() => m} state="answered" />);
    expect(container.querySelector('.stage-card-summary')?.textContent).toContain('请确认规格');
  });

  it('审查修复批：同时携带 decisionForm（fields 非空）与选项时不让位，题面可见', () => {
    // 交互面由 DecisionFormCard 接管（题面取 form.message），阶段卡不再让位
    const m = msg({
      text: '正文内容',
      confirm: '进入分镜设计前需要确认几个参数',
      confirmOptions: [{ label: '确认，继续' }],
      decisionForm: {
        token: 'decision:run_1',
        message: '进入分镜设计前需要确认几个参数',
        schema: { type: 'decision', fields: [{ key: 'shots', label: '几个分镜？', type: 'number' }] },
        options: [],
      },
    });
    const { container } = render(() => <StageCard msg={() => m} state="active" />);
    expect(container.querySelector('.stage-card-summary')?.textContent)
      .toContain('进入分镜设计前需要确认几个参数');
  });

  it('审查修复批：form.message 为空时题面不消失（不让位兼容）', () => {
    const m = msg({
      text: '正文内容',
      confirm: '请确认分镜参数',
      confirmOptions: [{ label: '确认，继续' }],
      decisionForm: {
        token: 'decision:run_2',
        message: '',
        schema: { type: 'decision', fields: [{ key: 'shots', label: '几个分镜？', type: 'number' }] },
        options: [],
      },
    });
    const { container } = render(() => <StageCard msg={() => m} state="active" />);
    expect(container.querySelector('.stage-card-summary')?.textContent).toContain('请确认分镜参数');
  });
});

describe('StageCard 徽标', () => {
  it('appliedActions 渲染操作数徽标', () => {
    const { container } = render(() => <StageCard msg={() => msg({ appliedActions: 3 })} state="none" />);
    expect(container.querySelector('.stage-card-badge')?.textContent).toContain('已执行 3 个操作');
  });

  it('answered/expired 渲染生命周期徽标，active/none 不渲染', () => {
    const a = render(() => <StageCard msg={() => msg()} state="answered" />);
    expect(a.container.textContent).toContain('已回应');
    a.unmount();
    const b = render(() => <StageCard msg={() => msg()} state="expired" />);
    expect(b.container.textContent).toContain('已过期');
    b.unmount();
    const c = render(() => <StageCard msg={() => msg()} state="active" />);
    expect(c.container.textContent).not.toContain('已回应');
    expect(c.container.textContent).not.toContain('已过期');
  });
});

describe('StageCard D-09 作废态（被新卡取代的 expired 旧卡）', () => {
  beforeEach(() => {
    toastMock.mockClear();
  });

  it('expired 旧卡挂 stage-card-void 作废标记类；active/answered/none 不挂', () => {
    const ex = render(() => <StageCard msg={() => msg()} state="expired" />);
    expect(ex.container.querySelector('.stage-card')?.classList.contains('stage-card-void')).toBe(true);
    ex.unmount();
    const ac = render(() => <StageCard msg={() => msg()} state="active" />);
    expect(ac.container.querySelector('.stage-card')?.classList.contains('stage-card-void')).toBe(false);
    ac.unmount();
    const an = render(() => <StageCard msg={() => msg()} state="answered" />);
    expect(an.container.querySelector('.stage-card')?.classList.contains('stage-card-void')).toBe(false);
    an.unmount();
    const no = render(() => <StageCard msg={() => msg()} state="none" />);
    expect(no.container.querySelector('.stage-card')?.classList.contains('stage-card-void')).toBe(false);
  });

  it('点击作废卡头部 → 触发失效反馈 Toast（info），且仍可展开/折叠供回看', async () => {
    const m = msg({ text: '正文内容', confirm: '请确认规格' });
    const { container } = render(() => <StageCard msg={() => m} state="expired" />);
    const header = container.querySelector('.stage-card-header') as HTMLButtonElement;
    // 默认展开：点击后折叠 + 给失效反馈
    await fireEvent.click(header);
    expect(toastMock).toHaveBeenCalledTimes(1);
    expect(toastMock).toHaveBeenCalledWith(expect.stringContaining('已被新卡取代'), 'info');
    expect(header.getAttribute('aria-expanded')).toBe('false');
    // 再点重新展开（历史回看不丢），反馈照常给
    await fireEvent.click(header);
    expect(header.getAttribute('aria-expanded')).toBe('true');
    expect(toastMock).toHaveBeenCalledTimes(2);
  });

  it('点击 active 卡头部只折叠展开，不触发失效 Toast', async () => {
    const m = msg({ text: '正文内容', confirm: '请确认规格' });
    const { container } = render(() => <StageCard msg={() => m} state="active" />);
    const header = container.querySelector('.stage-card-header') as HTMLButtonElement;
    await fireEvent.click(header);
    expect(header.getAttribute('aria-expanded')).toBe('false');
    expect(toastMock).not.toHaveBeenCalled();
  });
});
