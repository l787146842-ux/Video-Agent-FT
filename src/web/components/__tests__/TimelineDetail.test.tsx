/**
 * 任务 #2 时间线分级展开详情卡（TimelineDetail，经 AgentTimeline 组装验证）。
 *
 * 钉死契约：
 * ① expand 档：折叠态一句话结果（一眼信息不变），展开看输入参数预览+执行结果；
 * ② 中间档：仅输出留痕，不渲染详情卡与输入（即使携带 args）；
 * ③ 不展开档：保持单行摘要形态；运行态不渲染详情区；
 * ④ 任务 P2-5：审批档交互徽标映射（confirm=需确认 / none 不挂）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect } from 'vitest';
import { AgentTimeline } from '../right-panel/AgentTimeline';
import type { TimelineItem } from '@/lib/timeline';

const doneItem = (id: string, summary: string, ms: number, extra?: Partial<TimelineItem>): TimelineItem =>
  ({ id, summary, status: 'done', elapsed_ms: ms, ...extra });

describe('时间线分级展开：expand 档详情卡', () => {
  it('折叠态显示一句话结果，点击展开看输入参数+执行结果，再点收起', async () => {
    const { container } = render(() => (
      <AgentTimeline items={[doneItem('t-1-0', '写入文档 剧本.md', 300, {
        name: 'document_write',
        result_summary: '已写入规格文档。含分镜与音色两节，待确认。',
        args: { name: '剧本.md', content: '第一幕：深空中……' },
      })]} />
    ));
    const toggle = container.querySelector('.tl-detail-toggle') as HTMLButtonElement;
    expect(toggle).toBeTruthy();
    // 折叠态：一句话结果摘要（一眼信息不变），详情体未渲染
    expect(toggle.textContent).toContain('已写入规格文档。');
    expect(container.querySelector('.tl-detail-body')).toBeNull();
    // 展开：输入参数键值预览 + 执行结果全文
    await fireEvent.click(toggle);
    expect(container.querySelector('.tl-detail-body')).toBeTruthy();
    const labels = Array.from(container.querySelectorAll('.tl-detail-label')).map((e) => e.textContent);
    expect(labels).toEqual(['输入参数', '执行结果']);
    const keys = Array.from(container.querySelectorAll('.tl-detail-key')).map((e) => e.textContent);
    expect(keys).toEqual(['name', 'content']);
    expect(container.querySelector('.tl-detail-result')?.textContent).toContain('待确认');
    // 再点收起
    await fireEvent.click(toggle);
    expect(container.querySelector('.tl-detail-body')).toBeNull();
  });

  it('仅有输入无结果摘要：折叠态文案为「输入参数」，展开只含输入分区', async () => {
    const { container } = render(() => (
      <AgentTimeline items={[doneItem('t-1-0', '暂停等待确认', 50, {
        name: 'workflow_pause', args: { confirmation: '是否继续？' },
      })]} />
    ));
    const toggle = container.querySelector('.tl-detail-toggle') as HTMLButtonElement;
    expect(toggle.textContent).toContain('输入参数');
    await fireEvent.click(toggle);
    expect(container.querySelector('.tl-detail-key')?.textContent).toBe('confirmation');
    // 无结果段：只有输入参数一个分区
    expect(container.querySelectorAll('.tl-detail-section').length).toBe(1);
  });
});

describe('时间线分级展开：中间档与不展开档', () => {
  it('中间档：仅输出留痕，不渲染详情卡与输入（即使携带 args）', () => {
    const { container } = render(() => (
      <AgentTimeline items={[doneItem('t-1-0', '删除分组 A', 80, {
        name: 'storyboard_delete_group', result_summary: '已删除 1 个分组',
        args: { group_id: 'g-1' },
      })]} />
    ));
    expect(container.querySelector('.tl-detail-toggle')).toBeNull();
    expect(container.querySelector('.tl-detail-key')).toBeNull();
    expect(container.querySelector('.tl-item-result')?.textContent).toBe('↳ 已删除 1 个分组');
  });

  it('不展开档：保持单行摘要形态（有差异结果摘要仍留痕）', () => {
    const { container } = render(() => (
      <AgentTimeline items={[doneItem('t-1-0', '读取技能', 30, {
        name: 'read_skill', result_summary: '读取完成',
      })]} />
    ));
    expect(container.querySelector('.tl-detail-toggle')).toBeNull();
    expect(container.querySelector('.tl-item-result')?.textContent).toBe('↳ 读取完成');
  });

  it('运行态条目不渲染详情区（未完成无输出可看）', () => {
    const { container } = render(() => (
      <AgentTimeline items={[{
        id: 't-1-0', summary: '生图中', status: 'running', name: 'generate_image',
        args: { prompt: '赛博朋克城市' }, result_summary: '产出 1 张图',
      }]} live />
    ));
    expect(container.querySelector('.tl-detail-toggle')).toBeNull();
    expect(container.querySelector('.tl-item-result')).toBeNull();
  });
});

describe('时间线审批档交互徽标（任务 P2-5 正交轴映射）', () => {
  it('confirm 档工具（生成族）挂「需确认」徽标（expand 档折叠钮内）', () => {
    const { container } = render(() => (
      <AgentTimeline items={[doneItem('t-1-0', '生成图片', 8000, {
        name: 'generate_image', result_summary: '产出 1 张图',
        args: { prompt: '水墨山水' },
      })]} />
    ));
    const badge = container.querySelector('.tl-approval-confirm');
    expect(badge?.textContent).toBe('需确认');
    expect(container.querySelector('.tl-approval-review')).toBeNull();
  });

  it('none 档工具（只读类）不挂审批徽标', () => {
    const { container } = render(() => (
      <AgentTimeline items={[doneItem('t-1-0', '读取技能', 30, {
        name: 'read_skill', result_summary: '读取完成',
      })]} />
    ));
    expect(container.querySelector('.tl-approval-badge')).toBeNull();
  });
});
