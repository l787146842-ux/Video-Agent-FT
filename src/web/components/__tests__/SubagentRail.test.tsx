/**
 * B3 前端：子代理只读面板（SubagentRail）组件测试。
 * 钉死：① 空清单渲染引导文案；② 清单态渲染卡片（状态/步数/摘要）；
 * ③ 点卡片进只读记录（任务/正文/工具活动），④ 返回回清单。
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

import { SubagentRail } from '../left-panel/SubagentRail';

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

  it('完成章条目以 system 形态呈现（本轮宣告完成）', async () => {
    apiMock.getSubagentThreads.mockResolvedValue({
      subagents: [
        { conversation_id: 'c9', title: '子代理', label: '拆结构', parent_conversation: '', status: 'completed', steps: 2 },
      ],
    });
    apiMock.getSubagentRecord.mockResolvedValue({
      conversation_id: 'c9',
      messages: [
        { sender: 'user', text: '拆解任务' },
        { sender: 'system', text: '已登记本轮完成章。分镜 0 组 0 卡', stamp: true, ts: 1 },
      ],
    });
    const { findByTestId } = render(() => <SubagentRail />);
    fireEvent.click(await findByTestId('subagent-card'));
    // 记录异步装载：用 findBy 等条到才判存在（getBy 不等会假失败）
    const stamp = await findByTestId('subagent-stamp');
    expect(stamp.textContent).toContain('本轮宣告完成');
    expect(stamp.textContent).toContain('分镜 0 组 0 卡');
  });

  it('清单加载失败显示错误文案', async () => {
    apiMock.getSubagentThreads.mockRejectedValue(new Error('net'));
    const { findByText } = render(() => <SubagentRail />);
    expect(await findByText('子任务列表加载失败')).toBeTruthy();
  });
});
