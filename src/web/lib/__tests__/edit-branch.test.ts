/**
 * 编辑即分支通道测试（editMessageInBranch）：
 * ① 空白正文 / 忙碌中一律拒收（分支会切换活跃对话，流式中禁止）；
 * ② 成功路径的固定顺序：快照 → 派生分支 → 应用载荷 → 回填输入框 → 成功提示；
 * ③ 任一步失败落错误提示并返回 false（不产生半截分支态）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const studioState = vi.hoisted(() => ({ agentBusy: false }));
const applyPayload = vi.hoisted(() => vi.fn());
const toastMock = vi.hoisted(() => vi.fn());
const snapshotMock = vi.hoisted(() => vi.fn());
const branchMock = vi.hoisted(() => vi.fn());
const backfillMock = vi.hoisted(() => vi.fn());

vi.mock('@/stores/studio', () => ({ state: studioState }));
vi.mock('@/stores/conversations', () => ({ convActions: { applyPayload } }));
vi.mock('@/stores/toast', () => ({ showToast: toastMock }));
vi.mock('@/api/conversations', () => ({
  createSnapshot: snapshotMock,
  branchSnapshot: branchMock,
}));
vi.mock('@/lib/chat-input-bridge', () => ({ requestEditBackfill: backfillMock }));

import { editMessageInBranch } from '@/lib/edit-branch';

const PAYLOAD = { conversations: [], active_id: 'c2' };

describe('editMessageInBranch 编辑即分支', () => {
  beforeEach(() => {
    studioState.agentBusy = false;
    [applyPayload, toastMock, snapshotMock, branchMock, backfillMock]
      .forEach((m) => m.mockClear());
    snapshotMock.mockResolvedValue({ snap_id: 'snap1', title: '旧对话' });
    branchMock.mockResolvedValue(PAYLOAD);
  });

  it('空白正文直接拒收（不调任何接口）', async () => {
    expect(await editMessageInBranch('   ')).toBe(false);
    expect(snapshotMock).not.toHaveBeenCalled();
  });

  it('忙碌中拒收并给出忙碌提示', async () => {
    studioState.agentBusy = true;
    expect(await editMessageInBranch('改这里')).toBe(false);
    expect(snapshotMock).not.toHaveBeenCalled();
    expect(toastMock).toHaveBeenCalledWith(expect.any(String), 'warning');
  });

  it('成功：快照 → 分支 → 应用载荷 → 回填 → 成功提示，顺序钉死', async () => {
    const order: string[] = [];
    snapshotMock.mockImplementation(() => { order.push('snapshot'); return Promise.resolve({ snap_id: 'snap1', title: '' }); });
    branchMock.mockImplementation(() => { order.push('branch'); return Promise.resolve(PAYLOAD); });
    applyPayload.mockImplementation(() => order.push('apply'));
    backfillMock.mockImplementation(() => order.push('backfill'));

    expect(await editMessageInBranch('  改写开场白  ')).toBe(true);
    expect(order).toEqual(['snapshot', 'branch', 'apply', 'backfill']);
    expect(branchMock).toHaveBeenCalledWith('snap1');
    expect(applyPayload).toHaveBeenCalledWith(PAYLOAD);
    // 回填的是 trim 后的正文（等待用户在输入框确认后经统一入口发送）
    expect(backfillMock).toHaveBeenCalledWith('改写开场白');
    expect(toastMock).toHaveBeenCalledWith(expect.any(String), 'success');
  });

  it('分支接口失败：错误提示 + 返回 false', async () => {
    branchMock.mockRejectedValue(new Error('boom'));
    expect(await editMessageInBranch('改这里')).toBe(false);
    expect(applyPayload).not.toHaveBeenCalled();
    expect(toastMock).toHaveBeenCalledWith(expect.stringContaining('boom'), 'error');
  });
});
