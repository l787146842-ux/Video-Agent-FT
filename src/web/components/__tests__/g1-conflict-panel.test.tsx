/** G1 故事板冲突面板组件钉死测试：开闭渲染 + 逐项定夺 + 提交/放弃接线 */
import { render, waitFor, cleanup } from '@solidjs/testing-library';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { BoardConflictPanel } from '../left-panel/BoardConflictPanel';
import { openConflicts, closeConflicts, conflictsState } from '@/stores/studio/conflicts';
import { resolveBoardConflicts, cancelBoardConflicts } from '@/stores/studio/conflict-actions';

vi.mock('@/stores/studio/conflict-actions', () => ({
  resolveBoardConflicts: vi.fn(async () => {}),
  cancelBoardConflicts: vi.fn(async () => {}),
}));

const CONFLICT = {
  category: 'shots',
  category_label: '分镜',
  kind: 'draft',
  group_id: 'g1',
  group_title: '镜头1',
  id: 'd1',
  label: '草稿 1',
  mine: { id: 'd1', prompt: '用户版提示词' },
  theirs: { id: 'd1', prompt: 'Agent版提示词' },
};

function openWithConflict() {
  openConflicts({
    ok: true, applied: false, base_available: true, board_version: 5,
    merged: { keyElements: [], shots: [], audioItems: [], assets: [] },
    conflicts: [CONFLICT as never as Record<string, unknown>],
  });
}

describe('G1 冲突面板', () => {
  afterEach(() => {
    closeConflicts();
    vi.clearAllMocks();
    cleanup();
  });

  it('未开启时不渲染遮罩', () => {
    const { container } = render(() => <BoardConflictPanel />);
    expect(container.querySelector('.board-conflict-overlay')).toBeNull();
  });

  it('开启后渲染冲突清单与双方版本摘要', async () => {
    openWithConflict();
    const { container } = render(() => <BoardConflictPanel />);
    await waitFor(() => {
      expect(container.textContent).toContain('故事板改动冲突（1 处）');
    });
    expect(container.textContent).toContain('用户版提示词');
    expect(container.textContent).toContain('Agent版提示词');
    expect(container.textContent).toContain('镜头1');
  });

  it('点「采用 Agent」记录定夺（按钮进选中态）', async () => {
    openWithConflict();
    const { container } = render(() => <BoardConflictPanel />);
    const btns = [...container.querySelectorAll('.board-conflict-btns button')];
    const adopt = btns.find((b) => b.textContent === '采用 Agent');
    expect(adopt).toBeTruthy();
    adopt!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await waitFor(() => {
      expect(conflictsState.choices['shots|g1|draft|d1']).toBe('theirs');
    });
  });

  it('「保存决定」走提交流程、「放弃编辑」走取消流程', async () => {
    openWithConflict();
    const { container } = render(() => <BoardConflictPanel />);
    const footBtns = [...container.querySelectorAll('.board-conflict-foot button')];
    const save = footBtns.find((b) => b.textContent === '保存决定');
    const cancel = footBtns.find((b) => b.textContent === '放弃编辑');
    save!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await waitFor(() => expect(resolveBoardConflicts).toHaveBeenCalled());
    cancel!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await waitFor(() => expect(cancelBoardConflicts).toHaveBeenCalled());
  });
});
