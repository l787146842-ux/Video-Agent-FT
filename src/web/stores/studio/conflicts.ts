/** G1 并行局部修改 · 冲突面板域：三向合并冲突清单 + 用户定夺选择。
 * 纯状态域（不发请求）：提交/取消动作归 storyboard.ts（避免环依赖）。 */
import { createStore } from 'solid-js/store';
import type { BoardMergeResponse } from '@/types/api.generated';

/** 后端下发的冲突项（board_merge._conflict 同构） */
export interface BoardConflict {
  category: string;
  category_label: string;
  kind: string; // group=分组字段 / draft=草稿 / delete_vs_modify=删改
  group_id: string;
  group_title: string;
  id: string;
  label: string;
  mine: Record<string, unknown> | null;
  theirs: Record<string, unknown> | null;
}

interface ConflictsState {
  open: boolean;
  conflicts: BoardConflict[];
  /** 后端三向合并结果（冲突项默认保留用户版）四类别 */
  merged: Record<string, Record<string, unknown>[]> | null;
  boardVersion: number;
  /** 冲突项 → 定夺（key=conflictKey）；缺省=保留用户版（与 merged 默认一致） */
  choices: Record<string, 'mine' | 'theirs'>;
  resolving: boolean;
}

const [state, setState] = createStore<ConflictsState>({
  open: false,
  conflicts: [],
  merged: null,
  boardVersion: 0,
  choices: {},
  resolving: false,
});

export const conflictsState = state;

export function conflictKey(c: BoardConflict): string {
  return `${c.category}|${c.group_id}|${c.kind}|${c.id}`;
}

export function openConflicts(resp: BoardMergeResponse): void {
  setState({
    open: true,
    conflicts: (resp.conflicts || []) as unknown as BoardConflict[],
    merged: (resp.merged || null) as ConflictsState['merged'],
    boardVersion: resp.board_version ?? 0,
    choices: {},
    resolving: false,
  });
}

export function chooseConflict(key: string, side: 'mine' | 'theirs'): void {
  setState('choices', key, side);
}

export function chooseAll(side: 'mine' | 'theirs'): void {
  const next: Record<string, 'mine' | 'theirs'> = {};
  for (const c of state.conflicts) next[conflictKey(c)] = side;
  setState('choices', next);
}

export function setResolving(v: boolean): void {
  setState('resolving', v);
}

export function closeConflicts(): void {
  setState({ open: false, conflicts: [], merged: null, choices: {}, resolving: false });
}

/** 把定夺结果套进合并板：返回可直接整板回提的四类别。
 * 缺省选择=保留用户版（merged 已默认如此），选 Agent 版则回替；
 * delete_vs_modify 选 theirs=采纳删除（对应条目移除）。 */
export function applyChoices(): Record<string, Record<string, unknown>[]> | null {
  if (!state.merged) return null;
  const board: Record<string, Record<string, unknown>[]> = {};
  for (const cat of Object.keys(state.merged)) {
    board[cat] = (state.merged[cat] || []).map((g) => ({
      ...g,
      drafts: Array.isArray(g.drafts) ? [...(g.drafts as Record<string, unknown>[])] : [],
    }));
  }
  for (const c of state.conflicts) {
    const side = state.choices[conflictKey(c)] || 'mine';
    const groups = board[c.category];
    if (!groups) continue;
    const gi = groups.findIndex((g) => String(g.id || '') === c.group_id);
    if (gi < 0) continue;
    if (c.kind === 'group') {
      if (side === 'theirs' && c.theirs) {
        groups[gi] = { ...groups[gi], ...c.theirs, drafts: groups[gi].drafts };
      } // mine=缺省，merged 已是用户版
      continue;
    }
    const drafts = groups[gi].drafts as Record<string, unknown>[];
    const di = drafts.findIndex((d) => String(d.id || '') === c.id);
    if (c.kind === 'delete_vs_modify') {
      if (side === 'theirs') {
        // Agent 已删、用户选采纳删除 → 移除该分组/草稿
        if (di >= 0 && c.group_id && c.group_id !== c.id) drafts.splice(di, 1);
        else groups.splice(gi, 1);
      }
      continue;
    }
    if (di < 0) continue;
    if (side === 'theirs' && c.theirs) drafts[di] = { ...c.theirs };
  }
  return board;
}
