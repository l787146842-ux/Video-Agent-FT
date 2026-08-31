/** G1 故事板保存冲突回落钉死：409 版本冲突 → 三向合并 → 自动落盘/开冲突面板 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { putProjectState, getProjectState, mergeProjectState } from '@/api/project';
import { ApiError } from '@/api/client';
import { showToast } from '@/stores/toast';
import { state, setState } from '../studio-core';
import { conflictsState, closeConflicts } from '../studio/conflicts';
import { persistBoard, storyboardActions } from '../studio/storyboard';

vi.mock('@/api/project', () => ({
  putProjectState: vi.fn(),
  getProjectState: vi.fn(),
  mergeProjectState: vi.fn(),
}));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

function conflict409(): ApiError {
  return new ApiError(409, '版本冲突：状态已被其他窗口更新，请刷新后重试');
}

const EMPTY_SNAP = {
  project_id: 'p1', board_version: 9,
  keyElements: [], shots: [], audioItems: [], assets: [], chatMessages: [],
};

function touchBoard() {
  // 制造真实内容变化（脏检查放行）并触发防抖保存，供后续 flush 立即执行
  setState('keyElements', [{
    id: `g-${Date.now()}-${Math.random()}`, title: '用户新组', drafts: [],
  } as never as typeof state.keyElements[number]]);
  persistBoard();
}

describe('G1 保存冲突回落三向合并', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    closeConflicts();
    vi.mocked(getProjectState).mockResolvedValue(EMPTY_SNAP as never);
  });

  it('409 版本冲突且合并干净：自动落盘并采纳新版本', async () => {
    vi.mocked(putProjectState).mockRejectedValueOnce(conflict409());
    vi.mocked(mergeProjectState).mockResolvedValueOnce({
      ok: true, applied: true, base_available: true, board_version: 9,
    });
    touchBoard();
    await persistBoard.flush();
    expect(mergeProjectState).toHaveBeenCalled();
    expect(state.boardVersion).toBe(9);
    expect(state.boardSaveStatus).toBe('saved');
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('自动合并'), 'success');
  });

  it('409 版本冲突且有冲突项：开冲突面板交用户定夺', async () => {
    vi.mocked(putProjectState).mockRejectedValueOnce(conflict409());
    vi.mocked(mergeProjectState).mockResolvedValueOnce({
      ok: true, applied: false, base_available: true, board_version: 9,
      merged: { keyElements: [], shots: [], audioItems: [], assets: [] },
      conflicts: [{
        category: 'shots', category_label: '分镜', kind: 'draft',
        group_id: 'g1', group_title: '镜头1', id: 'd1', label: '草稿 1',
        mine: { id: 'd1', prompt: '我的' }, theirs: { id: 'd1', prompt: 'Agent的' },
      }],
    });
    touchBoard();
    await persistBoard.flush();
    expect(conflictsState.open).toBe(true);
    expect(conflictsState.conflicts.length).toBe(1);
    expect(conflictsState.boardVersion).toBe(9);
  });

  it('409 版本冲突但基线不可得：回落旧语义（提示重做 + 重同步）', async () => {
    vi.mocked(putProjectState).mockRejectedValueOnce(conflict409());
    vi.mocked(mergeProjectState).mockResolvedValueOnce({
      ok: false, applied: false, base_available: false, board_version: 9,
    });
    touchBoard();
    await persistBoard.flush();
    expect(conflictsState.open).toBe(false);
    expect(showToast).toHaveBeenCalledWith(
      expect.stringContaining('没有保存成功'), 'error');
  });

  it('syncFromServer 为合并结果重同步后本地态采纳服务端', () => {
    // 合并落盘后的重同步走既有 syncFromServer（保护生成中草稿的同一条路径）
    storyboardActions.syncFromServer({
      ...EMPTY_SNAP,
      keyElements: [{ id: 'g9', title: '合并后的组', drafts: [] }],
    } as never);
    expect(state.keyElements.some((g) => g.id === 'g9')).toBe(true);
  });
});
