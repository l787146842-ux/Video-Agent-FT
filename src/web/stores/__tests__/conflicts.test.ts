/** G1 冲突面板域单测：冲突清单状态机 + applyChoices 定夺套用逻辑 */
import { describe, expect, it, beforeEach } from 'vitest';
import {
  conflictsState, openConflicts, chooseConflict, chooseAll, closeConflicts,
  conflictKey, applyChoices, type BoardConflict,
} from '../studio/conflicts';

const CONFLICT: BoardConflict = {
  category: 'shots',
  category_label: '分镜',
  kind: 'draft',
  group_id: 'g1',
  group_title: '镜头1',
  id: 'd1',
  label: '草稿 1',
  mine: { id: 'd1', prompt: '用户版' },
  theirs: { id: 'd1', prompt: 'Agent版' },
};

const MERGED = {
  keyElements: [],
  shots: [
    { id: 'g1', title: '镜头1', drafts: [{ id: 'd1', prompt: '用户版' }] },
  ],
  audioItems: [],
  assets: [],
};

/** applyChoices 结果的本地收窄形态（生成物为 unknown 字典） */
type MergedGroup = { title?: string; drafts: Array<{ prompt?: string }> };

function open() {
  openConflicts({
    ok: true, applied: false, base_available: true,
    board_version: 7, merged: MERGED, conflicts: [CONFLICT as never as Record<string, unknown>],
  });
}

describe('conflicts store', () => {
  beforeEach(() => closeConflicts());

  it('openConflicts 载入冲突清单与合并板', () => {
    open();
    expect(conflictsState.open).toBe(true);
    expect(conflictsState.conflicts.length).toBe(1);
    expect(conflictsState.boardVersion).toBe(7);
  });

  it('conflictKey 稳定唯一', () => {
    expect(conflictKey(CONFLICT)).toBe('shots|g1|draft|d1');
  });

  it('chooseConflict/chooseAll 记录定夺', () => {
    open();
    chooseConflict(conflictKey(CONFLICT), 'theirs');
    expect(conflictsState.choices[conflictKey(CONFLICT)]).toBe('theirs');
    chooseAll('mine');
    expect(conflictsState.choices[conflictKey(CONFLICT)]).toBe('mine');
  });

  it('closeConflicts 复位', () => {
    open();
    closeConflicts();
    expect(conflictsState.open).toBe(false);
    expect(conflictsState.conflicts.length).toBe(0);
    expect(conflictsState.merged).toBeNull();
  });
});

describe('applyChoices', () => {
  beforeEach(() => closeConflicts());

  it('缺省保留用户版（与合并板默认一致）', () => {
    open();
    const board = applyChoices();
    expect((board?.shots[0] as MergedGroup).drafts[0].prompt).toBe('用户版');
  });

  it('选 Agent 版回替草稿', () => {
    open();
    chooseConflict(conflictKey(CONFLICT), 'theirs');
    const board = applyChoices();
    expect((board?.shots[0] as MergedGroup).drafts[0].prompt).toBe('Agent版');
  });

  it('delete_vs_modify 选 Agent=采纳删除（草稿级移除）', () => {
    openConflicts({
      ok: true, applied: false, base_available: true, board_version: 3,
      merged: MERGED,
      conflicts: [{
        ...CONFLICT, kind: 'delete_vs_modify', theirs: null,
      } as never as Record<string, unknown>],
    });
    chooseConflict(conflictKey({ ...CONFLICT, kind: 'delete_vs_modify', theirs: null }), 'theirs');
    const board = applyChoices();
    expect((board?.shots[0] as MergedGroup).drafts.length).toBe(0);
  });

  it('group 冲突选 Agent 版回替外壳字段、保留合并草稿', () => {
    openConflicts({
      ok: true, applied: false, base_available: true, board_version: 3,
      merged: MERGED,
      conflicts: [{
        ...CONFLICT, kind: 'group', id: 'g1', label: '镜头1',
        mine: { id: 'g1', title: '用户标题' },
        theirs: { id: 'g1', title: 'Agent标题' },
      } as never as Record<string, unknown>],
    });
    chooseConflict('shots|g1|group|g1', 'theirs');
    const board = applyChoices();
    const g = board?.shots[0] as MergedGroup;
    expect(g.title).toBe('Agent标题');
    expect(g.drafts.length).toBe(1);
  });

  it('无合并板返 null', () => {
    expect(applyChoices()).toBeNull();
  });
});
