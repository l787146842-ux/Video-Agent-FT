/**
 * 撤销/重做状态store
 * 后端 undo 栈是唯一事实源（StateManager），前端仅持有 can_undo/can_redo 两个指示位。
 */
import { createSignal } from 'solid-js';
import {
  checkpointUndo, getUndoStatus, redoAction, undoAction,
} from '@/api/project';
import { studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';

const [canUndo, setCanUndo] = createSignal(false);
const [canRedo, setCanRedo] = createSignal(false);

export const historyState = {
  get canUndo() { return canUndo(); },
  get canRedo() { return canRedo(); },
};

/** 从后端同步 undo/redo 可用状态（操作后、SSE done 后、初始化后调用） */
export async function refreshHistoryStatus(): Promise<void> {
  try {
    const s = await getUndoStatus();
    setCanUndo(!!s.can_undo);
    setCanRedo(!!s.can_redo);
  } catch { /* 后端未就绪时保持现状 */ }
}

/** 破坏性操作前压撤销检查点（失败不阻断主操作） */
export async function checkpointHistory(): Promise<void> {
  try {
    const s = await checkpointUndo();
    setCanUndo(!!s.can_undo);
    setCanRedo(!!s.can_redo);
  } catch { /* 检查点失败仅意味着本次操作不可撤销 */ }
}

export async function performUndo(): Promise<void> {
  try {
    const data = await undoAction();
    if (data.ok && data.state) {
      studioActions.syncFromServer(data.state);
      showToast('已撤销', 'success');
    } else {
      showToast(data.message || '没有可撤销的操作', 'warning');
    }
  } catch (e) {
    showToast(`撤销失败：${(e as Error).message}`, 'error');
  } finally {
    await refreshHistoryStatus();
  }
}

export async function performRedo(): Promise<void> {
  try {
    const data = await redoAction();
    if (data.ok && data.state) {
      studioActions.syncFromServer(data.state);
      showToast('已重做', 'success');
    } else {
      showToast(data.message || '没有可重做的操作', 'warning');
    }
  } catch (e) {
    showToast(`重做失败：${(e as Error).message}`, 'error');
  } finally {
    await refreshHistoryStatus();
  }
}
