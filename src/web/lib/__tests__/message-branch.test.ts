/**
 * 消息级分支动作通道测试（任务 #17：悬停工具条「分支」）。
 *
 * 钉死 branchAtMessage 编排：以该消息下标为分叉点打截断快照
 * （up_to_index）→ 派生分支 → applyPayload 切换；忙碌守卫兜底；
 * 失败弹 toast 且不切换对话。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const snapshotMock = vi.fn(async (_idx?: number) => ({ snap_id: 's1', title: '快照' }));
const branchApiMock = vi.fn(async (_id: string) => ({ conv: { id: 'c2', title: '分支' } }));
vi.mock('@/api/conversations', () => ({
  createSnapshot: (idx?: number) => snapshotMock(idx),
  branchSnapshot: (id: string) => branchApiMock(id),
}));

const applyMock = vi.fn();
vi.mock('@/stores/conversations', () => ({
  convActions: { applyPayload: (p: unknown) => applyMock(p) },
}));

const toastMock = vi.fn();
vi.mock('@/stores/toast', () => ({
  showToast: (msg: string, kind: string) => toastMock(msg, kind),
}));

import { branchAtMessage } from '../message-branch';
import { studioActions } from '@/stores/studio';

describe('branchAtMessage', () => {
  beforeEach(() => {
    snapshotMock.mockClear();
    branchApiMock.mockClear();
    applyMock.mockClear();
    toastMock.mockClear();
    studioActions.setAgentBusy(false);
  });

  it('以消息下标为分叉点：snapshot 带 up_to_index → branch → applyPayload', async () => {
    const ok = await branchAtMessage(3);
    expect(ok).toBe(true);
    expect(snapshotMock).toHaveBeenCalledWith(3);
    expect(branchApiMock).toHaveBeenCalledWith('s1');
    expect(applyMock).toHaveBeenCalledTimes(1);
  });

  it('忙碌中拒发（分支会切换活跃对话）', async () => {
    studioActions.setAgentBusy(true);
    const ok = await branchAtMessage(1);
    expect(ok).toBe(false);
    expect(snapshotMock).not.toHaveBeenCalled();
    expect(applyMock).not.toHaveBeenCalled();
  });

  it('快照/派生失败：toast 报错，不切换对话', async () => {
    snapshotMock.mockRejectedValueOnce(new Error('越界'));
    const ok = await branchAtMessage(99);
    expect(ok).toBe(false);
    expect(applyMock).not.toHaveBeenCalled();
    expect(toastMock).toHaveBeenCalled();
    expect(toastMock.mock.calls[0][0]).toContain('越界');
  });
});
