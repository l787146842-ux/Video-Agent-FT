/** 计划清单批 2：board-sync 对 plan 键的同步语义钉死
 * （键在场即同步含清空；存量快照无键保留本地态；切项目重置）。 */
import { describe, it, expect, beforeEach } from 'vitest';
import { state, setState } from '../studio-core';
import { boardSyncActions } from '../studio/board-sync';

const BASE_SNAP = {
  project_id: 'p1', board_version: 3,
  keyElements: [], shots: [], audioItems: [], assets: [],
};

describe('plan 键同步语义', () => {
  beforeEach(() => {
    setState('plan', null);
    setState('projectId', '');
    setState('boardVersion', 0);
  });

  it('快照带 plan → state.plan 更新为清单形态', () => {
    boardSyncActions.syncFromServer({
      ...BASE_SNAP,
      plan: { items: [{ content: '拆镜', status: 'in_progress' }], updated_turn: 2 },
    } as never);
    expect(state.plan?.items).toHaveLength(1);
    expect(state.plan?.items?.[0].content).toBe('拆镜');
  });

  it('快照 plan=null → 清空本地清单', () => {
    setState('plan', { items: [{ content: '旧项', status: 'pending' }] });
    boardSyncActions.syncFromServer({ ...BASE_SNAP, plan: null } as never);
    expect(state.plan).toBeNull();
  });

  it('存量快照无 plan 键 → 保留本地态（旧口径不误清）', () => {
    setState('plan', { items: [{ content: '保留项', status: 'pending' }] });
    boardSyncActions.syncFromServer(BASE_SNAP as never);
    expect(state.plan?.items?.[0].content).toBe('保留项');
  });

  it('resetForProject：新项目带 plan 即应用', () => {
    setState('plan', { items: [{ content: '旧项目项', status: 'pending' }] });
    boardSyncActions.resetForProject({
      ...BASE_SNAP, project_id: 'p2',
      plan: { items: [{ content: '新项目项', status: 'pending' }] },
    } as never);
    expect(state.plan?.items?.[0].content).toBe('新项目项');
  });

  it('resetForProject：新项目无 plan → 重置为 null 不残留', () => {
    setState('plan', { items: [{ content: '旧项目项', status: 'pending' }] });
    boardSyncActions.resetForProject({ ...BASE_SNAP, project_id: 'p2' } as never);
    expect(state.plan).toBeNull();
  });
});
