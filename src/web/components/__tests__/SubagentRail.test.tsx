/**
 * B3 前端：子代理只读面板（SubagentRail）组件测试。
 * 钉死：① 空清单渲染引导文案；② 清单态渲染卡片（状态/步数/摘要）；
 * ③ 点卡片进只读记录（任务/正文/工具活动），④ 返回回清单，
 * ⑤ 轮询增量更新（内容一致复用旧引用 ⇒ 不重建 DOM ⇒ 记录滚动不跳）。
 * 数据面（@/api/conversations）与 markdown 渲染子件打桩，只钉本组件编排。
 */
import { render, fireEvent, cleanup } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const apiMock = vi.hoisted(() => ({
  getSubagentThreads: vi.fn(),
  getSubagentRecord: vi.fn(),
}));
vi.mock('@/api/conversations', () => apiMock);
vi.mock('@/components/right-panel/MarkdownBubble', () => ({
  MarkdownBubble: (props: { text: string }) => <div class="md-stub">{props.text}</div>,
}));

import { SubagentRail, stabilizeItems, sameRecordMsg } from '../middle-panel/SubagentRail';

beforeEach(() => {
  apiMock.getSubagentThreads.mockReset();
  apiMock.getSubagentRecord.mockReset();
});
afterEach(() => { cleanup(); });

describe('SubagentRail', () => {
  it('空清单渲染引导文案', async () => {
    apiMock.getSubagentThreads.mockResolvedValue({ subagents: [] });
    const { findByText } = render(() => <SubagentRail />);
    expect(await findByText(/还没有子任务/)).toBeTruthy();
  });

  it('清单态渲染卡片：状态 / 步数 / 任务摘要', async () => {
    apiMock.getSubagentThreads.mockResolvedValue({
      subagents: [
        { conversation_id: 'c1', title: '子代理', label: '拆解《三体》', parent_conversation: '', status: 'completed', steps: 3 },
        { conversation_id: 'c2', title: '子代理', label: '写提示词', parent_conversation: '', status: 'running', steps: 1 },
      ],
    });
    const { findAllByTestId, getByText } = render(() => <SubagentRail />);
    const cards = await findAllByTestId('subagent-card');
    expect(cards.length).toBe(2);
    expect(getByText('已完成')).toBeTruthy();
    expect(getByText('执行中')).toBeTruthy();
    expect(getByText('3 步')).toBeTruthy();
    expect(getByText('写提示词')).toBeTruthy();
  });

  it('8888 批 D：status=failed → 渲染「已中断」+ class failed', async () => {
    apiMock.getSubagentThreads.mockResolvedValue({
      subagents: [
        { conversation_id: 'cf', title: '子代理', label: '拆镜', parent_conversation: '', status: 'failed', steps: 2 },
      ],
    });
    const { findByTestId, getByText } = render(() => <SubagentRail />);
    const card = await findByTestId('subagent-card');
    expect(getByText('已中断')).toBeTruthy();
    const statusEl = card.querySelector('.subagent-status.failed');
    expect(statusEl).toBeTruthy();
    expect(statusEl?.textContent).toContain('已中断');
  });

  it('点卡片进只读记录，返回回清单', async () => {
    apiMock.getSubagentThreads.mockResolvedValue({
      subagents: [
        { conversation_id: 'c1', title: '子代理', label: '拆解', parent_conversation: '', status: 'completed', steps: 2 },
      ],
    });
    apiMock.getSubagentRecord.mockResolvedValue({
      conversation_id: 'c1',
      messages: [
        { sender: 'user', text: '拆解任务全文' },
        { sender: 'assistant', text: '建了 3 个元素', reasoning_content: '先想清楚', actionLog: ['storyboard_create_group'] },
      ],
    });
    const { findByTestId, findByText, getByText, getByTestId } = render(() => <SubagentRail />);
    const card = await findByTestId('subagent-card');
    fireEvent.click(card);
    // 记录正文（MarkdownBubble 打桩为 .md-stub）与工具活动、任务行都出现
    expect(await findByText('建了 3 个元素')).toBeTruthy();
    const list = getByTestId('subagent-record-list');
    expect(list.textContent).toContain('拆解任务全文');
    expect(list.textContent).toContain('执行：storyboard_create_group');
    expect(list.textContent).toContain('先想清楚');
    expect(apiMock.getSubagentRecord).toHaveBeenCalledWith('c1');
    // 返回 → 清单态，卡片重现
    fireEvent.click(getByText('返回'));
    expect(await findByTestId('subagent-card')).toBeTruthy();
  });

  it('清单加载失败显示错误文案', async () => {
    apiMock.getSubagentThreads.mockRejectedValue(new Error('net'));
    const { findByText } = render(() => <SubagentRail />);
    expect(await findByText('子任务列表加载失败')).toBeTruthy();
  });
});

/**
 * E6/E7 轮询增量更新：内容一致时必须复用旧条目引用（Solid <For> 按引用比对
 * ⇒ 不重建 DOM ⇒ 记录滚动位置不跳），只有新增/变更的条目才产生新对象。
 */
describe('轮询增量更新（引用稳定化）', () => {
  const u = (text: string) => ({ sender: 'user' as const, text });
  const a = (text: string) => ({ sender: 'assistant' as const, text });

  it('内容完全一致 → 返回旧数组同一引用（signal 不触发重渲染）', () => {
    const prev = [u('任务全文'), a('建了 3 个元素')];
    const next = [u('任务全文'), a('建了 3 个元素')];
    expect(stabilizeItems(prev, next, sameRecordMsg)).toBe(prev);
  });

  it('尾部新增 → 旧条目引用保留，仅新条目为新对象', () => {
    const prev = [u('任务全文')];
    const added = a('新的一段正文');
    const out = stabilizeItems(prev, [u('任务全文'), added], sameRecordMsg);
    expect(out).not.toBe(prev);
    expect(out[0]).toBe(prev[0]);
    expect(out[1]).toBe(added);
  });

  it('中部内容变更 → 仅该条换新对象，其余复用旧引用', () => {
    const prev = [u('任务全文'), a('旧正文')];
    const out = stabilizeItems(prev, [u('任务全文'), a('新正文')], sameRecordMsg);
    expect(out[0]).toBe(prev[0]);
    expect(out[1]).not.toBe(prev[1]);
    expect(out[1].text).toBe('新正文');
  });

  // 2026-09-22 批4（Q4.1）：在途步的正文/耗时随轮询增长，比较器必须感知，
  // 否则稳定化把新对象误判为「未变」→ 复用旧引用 → Solid 不重渲染 → 永远不流式。
  it('在途步正文增长 → 不判为「未变」（否则实时增量长不出来）', () => {
    const prev = [{ sender: 'assistant' as const, text: '正在登记', streaming: true, elapsed_ms: 1000 }];
    const next = [{ sender: 'assistant' as const, text: '正在登记 22 组', streaming: true, elapsed_ms: 2500 }];
    expect(sameRecordMsg(prev[0], next[0])).toBe(false);
    const out = stabilizeItems(prev, next, sameRecordMsg);
    expect(out[0]).toBe(next[0]);
  });

  it('elapsed_ms / streaming 变化即视为变更（耗时角标要走）', () => {
    const base = { sender: 'assistant' as const, text: '同一段', elapsed_ms: 1000 };
    expect(sameRecordMsg(base, { ...base, elapsed_ms: 2000 })).toBe(false);
    expect(sameRecordMsg(base, { ...base, streaming: true })).toBe(false);
    expect(sameRecordMsg(base, { ...base })).toBe(true);
  });
});

// 2026-09-22 批4（Q4.1+Q4.2）：在途步渲染 + 每步耗时角标
describe('批4：在途步与耗时呈现（Q4.1+Q4.2）', () => {
  beforeEach(() => {
    apiMock.getSubagentThreads.mockResolvedValue({
      subagents: [
        { conversation_id: 'c1', title: '子代理', label: '分镜', parent_conversation: '', status: 'running', steps: 2 },
      ],
    });
  });

  it('在途步：思考默认展开、挂 live 类，并显示耗时', async () => {
    apiMock.getSubagentRecord.mockResolvedValue({
      conversation_id: 'c1',
      messages: [
        { sender: 'user', text: '拆镜' },
        { sender: 'assistant', reasoning_content: '正在数镜头……', streaming: true, elapsed_ms: 4200 },
      ],
    });
    const { findByTestId, getByTestId } = render(() => <SubagentRail />);
    fireEvent.click(await findByTestId('subagent-card'));
    await findByTestId('subagent-record-list');
    const list = getByTestId('subagent-record-list');
    // live 类挂上（色条提示「还在长」）
    expect(list.querySelector('.subagent-step-live')).toBeTruthy();
    // 思考自动展开：<details open> 且内容已在
    const details = list.querySelector('details.subagent-reasoning') as HTMLDetailsElement;
    expect(details).toBeTruthy();
    expect(details.open).toBe(true);
    expect(details.textContent).toContain('正在数镜头');
    // Q4.2：耗时角标出现（4.2s）
    expect(details.textContent).toContain('4.2s');
  });

  it('已完成步：思考保持折叠但有耗时角标（不长期占高度）', async () => {
    apiMock.getSubagentRecord.mockResolvedValue({
      conversation_id: 'c1',
      messages: [
        { sender: 'user', text: '拆镜' },
        { sender: 'assistant', reasoning_content: '想完了', elapsed_ms: 12000 },
      ],
    });
    const { findByTestId, getByTestId } = render(() => <SubagentRail />);
    fireEvent.click(await findByTestId('subagent-card'));
    await findByTestId('subagent-record-list');
    const list = getByTestId('subagent-record-list');
    expect(list.querySelector('.subagent-step-live')).toBeNull();
    const details = list.querySelector('details.subagent-reasoning') as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(details.textContent).toContain('12.0s');
  });

  it('无思考的纯工具步：耗时挂条目尾部（回看可知每步多久）', async () => {
    apiMock.getSubagentRecord.mockResolvedValue({
      conversation_id: 'c1',
      messages: [
        { sender: 'assistant', actionLog: ['storyboard_create_group'], elapsed_ms: 3400 },
      ],
    });
    const { findByTestId, getByTestId } = render(() => <SubagentRail />);
    fireEvent.click(await findByTestId('subagent-card'));
    await findByTestId('subagent-record-list');
    const list = getByTestId('subagent-record-list');
    expect(list.querySelector('details.subagent-reasoning')).toBeNull();
    expect(list.textContent).toContain('3.4s');
  });
});
