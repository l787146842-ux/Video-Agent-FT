/**
 * AgentTimeline 组件测试。
 *
 * 钉死契约：
 * ① 双折叠面板（深度思考 / 已处理操作）呈现与手动展开折叠；
 * ② 运行态条目走秒计时（500ms 刷新 now），完成态显示最终耗时角标；
 * ③ 连续规划轮合并条目（consolidateTimeline）可点击展开逐轮明细；
 * ④ 结果摘要（result_summary）与 summary 重复时不重复展示。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { AgentTimeline } from '../right-panel/AgentTimeline';
import type { TimelineItem } from '@/lib/timeline';

const doneItem = (id: string, summary: string, ms: number, extra?: Partial<TimelineItem>): TimelineItem =>
  ({ id, summary, status: 'done', elapsed_ms: ms, ...extra });

/** 面板标题文本集合（含展开态 class 判定） */
function panels(container: HTMLElement) {
  return Array.from(container.querySelectorAll('.tl-panel')) as HTMLElement[];
}

describe('AgentTimeline 双折叠面板呈现', () => {
  it('有 reasoning + items → 两面板齐备（深度思考/已处理操作）', () => {
    const { container } = render(() => (
      <AgentTimeline reasoning="先分析剧本结构" items={[doneItem('t-1-0', '执行工具 script_analyze', 1200)]} />
    ));
    const titles = panels(container).map((p) => p.querySelector('.tl-panel-title')?.textContent);
    expect(titles[0]).toBe('深度思考');
    expect(titles[1]).toBe('已处理 1 个操作');
    expect(container.querySelector('.tl-reasoning')?.textContent).toBe('先分析剧本结构');
  });

  it('历史重建（非 live）两面板初始折叠；点击头部可展开/收起', async () => {
    const { container } = render(() => (
      <AgentTimeline reasoning="思考" items={[doneItem('t-1-0', '写文档', 100)]} />
    ));
    const [thinkPanel, opsPanel] = panels(container);
    expect(thinkPanel.classList.contains('expanded')).toBe(false);
    expect(opsPanel.classList.contains('expanded')).toBe(false);
    await fireEvent.click(opsPanel.querySelector('.tl-panel-header') as HTMLElement);
    expect(panels(container)[1].classList.contains('expanded')).toBe(true);
    await fireEvent.click(thinkPanel.querySelector('.tl-panel-header') as HTMLElement);
    expect(panels(container)[0].classList.contains('expanded')).toBe(true);
  });

  it('流式中（live）两面板默认展开，思考视窗走 live 形态', () => {
    const { container } = render(() => (
      <AgentTimeline reasoning="正在想" items={[doneItem('t-1-0', 'x', 100)]} live />
    ));
    panels(container).forEach((p) => expect(p.classList.contains('expanded')).toBe(true));
    expect(container.querySelector('.tl-reasoning-live')).toBeTruthy();
  });

  it('无 reasoning 无 items → 整体不渲染', () => {
    const { container } = render(() => <AgentTimeline items={[]} />);
    expect(container.querySelector('.agent-timeline')).toBeNull();
  });

  it('完成态 thinkingMs 角标仅历史重建显示（流式中不显示）', () => {
    const done = render(() => <AgentTimeline reasoning="x" items={[]} thinkingMs={2400} />);
    expect(done.container.querySelector('.tl-panel-elapsed')?.textContent).toContain('2.4s');
    const live = render(() => <AgentTimeline reasoning="x" items={[]} live thinkingMs={2400} />);
    expect(live.container.querySelector('.tl-panel-elapsed')).toBeNull();
  });
});

describe('AgentTimeline 耗时角标与运行态走秒', () => {
  afterEach(() => vi.useRealTimers());

  it('完成条目显示最终耗时（formatElapsed 口径）', () => {
    const { container } = render(() => (
      <AgentTimeline items={[doneItem('t-1-0', '生图', 1200), doneItem('t-1-1', '快操作', 60)]} />
    ));
    const elapsed = Array.from(container.querySelectorAll('.tl-item-elapsed')).map((e) => e.textContent);
    expect(elapsed).toContain('· 1.2s');
    expect(elapsed).toContain('· 60ms');
  });

  it('运行态条目走秒：每 500ms 刷新一次 now（起点 started_at_ms）', () => {
    vi.useFakeTimers();
    const startedAt = Date.now() - 1500;
    const { container } = render(() => (
      <AgentTimeline items={[{ id: 't-1-0', summary: '生图中', status: 'running', started_at_ms: startedAt }]} live />
    ));
    const el = () => container.querySelector('.tl-item-elapsed')?.textContent || '';
    expect(el()).toBe('· 1.5s');
    vi.advanceTimersByTime(1000);
    expect(el()).toBe('· 2.5s');
  });

  it('运行态无起点 → 不显示耗时角标', () => {
    const { container } = render(() => (
      <AgentTimeline items={[{ id: 't-1-0', summary: '生图中', status: 'running' }]} live />
    ));
    expect(container.querySelector('.tl-item-elapsed')).toBeNull();
  });
});

describe('AgentTimeline 合并条目与结果摘要', () => {
  const llm = (step: number, ms: number): TimelineItem =>
    ({ id: `llm-s${step}`, summary: `规划第 ${step} 轮`, status: 'done', elapsed_ms: ms });

  it('连续规划轮合并为单条，点击展开逐轮明细（再点收起）', async () => {
    const { container } = render(() => <AgentTimeline items={[llm(1, 1200), llm(2, 800), llm(3, 1000)]} />);
    // 合并条：三条规划 → 一条（工具条目不受影响）
    expect(container.querySelectorAll('.tl-item').length).toBe(1);
    const toggle = container.querySelector('.tl-item-summary-toggle') as HTMLButtonElement;
    expect(toggle.textContent).toContain('模型创作 3 步 · 累计 3.0s');
    expect(container.querySelector('.tl-sublist')).toBeNull();
    await fireEvent.click(toggle);
    const subs = container.querySelectorAll('.tl-subitem');
    expect(subs.length).toBe(3);
    expect(subs[0].textContent).toContain('规划第 1 轮');
    expect(subs[0].textContent).toContain('· 1.2s');
    await fireEvent.click(toggle);
    expect(container.querySelector('.tl-sublist')).toBeNull();
  });

  it('工具条目带 result_summary → 结果摘要行展示；与 summary 重复则不重复', () => {
    const { container } = render(() => (
      <AgentTimeline items={[
        doneItem('t-1-0', '执行工具 image_generate', 900, { result_summary: '产出 3 张图' }),
        doneItem('t-1-1', '写入文档', 300, { result_summary: '写入文档' }),
      ]}
      />
    ));
    const results = Array.from(container.querySelectorAll('.tl-item-result')).map((e) => e.textContent);
    expect(results).toEqual(['↳ 产出 3 张图']);
  });

  it('多句 result_summary：折叠态一句话，点击展开全文，再点收起', async () => {
    const full = '已写入规格文档。含分镜与音色两节，待确认。';
    const { container } = render(() => (
      <AgentTimeline items={[doneItem('t-1-0', '写文档', 300, { result_summary: full })]} />
    ));
    const toggle = container.querySelector('.tl-item-result-toggle') as HTMLButtonElement;
    expect(toggle).toBeTruthy();
    // 折叠态：只显示首句（不含后续句），带展开箭头
    expect(toggle.textContent).toContain('已写入规格文档。');
    expect(toggle.textContent).not.toContain('待确认');
    // 点击展开：全文可见；再点收起回首句
    await fireEvent.click(toggle);
    expect(toggle.textContent).toContain('待确认');
    expect(toggle.classList.contains('expanded')).toBe(true);
    await fireEvent.click(toggle);
    expect(toggle.textContent).not.toContain('待确认');
    expect(toggle.classList.contains('expanded')).toBe(false);
  });

  it('单句 result_summary：不挂展开按钮（保持纯文本行）', () => {
    const { container } = render(() => (
      <AgentTimeline items={[doneItem('t-1-0', '生图', 900, { result_summary: '产出 3 张图。' })]} />
    ));
    expect(container.querySelector('.tl-item-result-toggle')).toBeNull();
    expect(container.querySelector('.tl-item-result')?.textContent).toBe('↳ 产出 3 张图。');
  });

  it('规划级执行器徽标（planning）随条目呈现', () => {
    const { container } = render(() => (
      <AgentTimeline items={[doneItem('t-1-0', '音频生成', 200, { planning: true })]} />
    ));
    expect(container.querySelector('.tl-planning-badge')?.textContent).toBe('规划');
  });

  it('live 标题：liveStatus 为具体动作时展示「动作（已完成 N 项）」', () => {
    const { container } = render(() => (
      <AgentTimeline
        items={[doneItem('t-1-0', '写文档', 100), { id: 't-1-1', summary: '生图', status: 'running' }]}
        live
        liveStatus={() => '正在生图'}
      />
    ));
    const title = panels(container)[0].querySelector('.tl-panel-title')?.textContent;
    expect(title).toBe('正在生图（已完成 1 项）');
  });
});
