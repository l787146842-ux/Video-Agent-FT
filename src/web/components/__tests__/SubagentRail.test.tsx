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
});
