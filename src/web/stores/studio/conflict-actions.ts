/** G1 冲突面板提交/取消动作（独立成文件：避免 storyboard 行数棘轮与环依赖）。
 * 定夺结果整板回提（携合并端点回传的最新版号），成功后重同步本地态。 */
import { putProjectState, getProjectState } from '@/api/project';
import { ApiError } from '@/api/client';
import { showToast } from '@/stores/toast';
import { state, setState } from '../studio-core';
import { storyboardActions } from './storyboard';
import {
  conflictsState, closeConflicts, applyChoices, setResolving,
} from './conflicts';

/** 面板定夺后提交：合并板套用户选择整板回提（版号=合并端点回传，正常情况无再冲突） */
export async function resolveBoardConflicts(): Promise<void> {
  const board = applyChoices();
  if (!board || conflictsState.resolving) return;
  setResolving(true);
  try {
    const resp = await putProjectState({
      project_id: state.projectId,
      base_version: conflictsState.boardVersion,
      keyElements: board.keyElements as never as typeof state.keyElements,
      shots: board.shots as never as typeof state.shots,
      audioItems: board.audioItems as never as typeof state.audioItems,
      assets: board.assets as never as typeof state.assets,
    } as Parameters<typeof putProjectState>[0]);
    closeConflicts();
    setState('boardVersion', typeof resp?.board_version === 'number'
      ? resp.board_version : conflictsState.boardVersion + 1);
    try {
      const snap = await getProjectState();
      storyboardActions.syncFromServer(snap);
    } catch { /* 重同步失败保留本地态，下次编辑再试 */ }
    setState('boardSaveStatus', 'saved');
    showToast('冲突已按你的选择保存', 'success');
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      // 定夺期间又有新写入：本次冲突裁决失效，重同步最新状态让用户在最新态上重编
      closeConflicts();
      try {
        const snap = await getProjectState();
        storyboardActions.syncFromServer(snap);
      } catch { /* 保留本地态 */ }
      showToast('故事板又有了新改动，刚才的冲突已失效，页面已同步最新状态', 'error');
      return;
    }
    showToast(`冲突保存失败：${(e as Error).message}`, 'error');
  } finally {
    setResolving(false);
  }
}

/** 放弃裁决：丢弃本次编辑，同步服务端最新状态（等价选「全部采用 Agent」再放弃合并外的本地改动） */
export async function cancelBoardConflicts(): Promise<void> {
  closeConflicts();
  try {
    const snap = await getProjectState();
    storyboardActions.syncFromServer(snap);
    setState('boardSaveStatus', 'saved');
  } catch { /* 同步失败保留本地态 */ }
}
