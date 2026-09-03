/** Studio store · 故事板持久化域（Q14 裁决 2026-09-01 方案 A：自 storyboard.ts 三分）。
 * 整板保存链（防抖/串行/内容级脏检查/版本冲突三向合并回落）+ 页面卸载冲刷。
 * 状态树不动；原签名经 storyboard.ts 重导出，调用方零改动。 */
import { putProjectState, getProjectState, mergeProjectState, flushProjectStateKeepalive } from '@/api/project';
import { ApiError } from '@/api/client';
import { showToast } from '@/stores/toast';
import { debounce } from '@/lib/utils';
import { openConflicts } from './conflicts';
import { state, setState } from '../studio-core';
import { boardSyncActions, syncedContentJson, setSyncedContentJson } from './board-sync';

/** 整板保存 payload（防抖 PUT 与页面卸载冲刷共用）；
 * base_version 供后端乐观锁校验，防陈旧整板覆盖 Agent 新写入 */
function boardSavePayload() {
  return {
    project_id: state.projectId,
    base_version: state.boardVersion,
    keyElements: state.keyElements,
    shots: state.shots,
    audioItems: state.audioItems,
    assets: state.assets,
  };
}

/** 存在尚未落盘的本地编辑（页面卸载冲刷的放行条件） */
let boardDirty = false;

function boardContentJson(): string {
  return JSON.stringify({
    k: state.keyElements, s: state.shots, a: state.audioItems, as: state.assets,
  });
}

/** 串行化保存链：防抖触发与 flush 并发时两个 PUT 携同一 base_version 互撞，
 *  后者必被 409 拒引发整板重同步闪烁；串行后每次 PUT 都读到最新版本 */
let saveChain: Promise<void> = Promise.resolve();

/** G1 版本冲突回落：陈旧整板提交改走三向合并（对标 Flova 并行局部修改）。
 * 单方改动自动采纳落盘；双方同改 → 开冲突面板交用户定夺；
 * 基线不可得返 false，调用方回落旧「丢弃重做」语义。 */
async function tryMergeOnConflict(): Promise<boolean> {
  try {
    const resp = await mergeProjectState(boardSavePayload());
    if (resp.applied) {
      boardDirty = false;
      setState('boardVersion', typeof resp.board_version === 'number'
        ? resp.board_version : state.boardVersion + 1);
      setState('boardSaveStatus', 'saved');
      try {
        const snap = await getProjectState();
        boardSyncActions.syncFromServer(snap);
        setSyncedContentJson(boardContentJson());
      } catch { /* 同步失败保留本地态，下次编辑再试 */ }
      showToast('已和 Agent 的最新改动自动合并保存', 'success');
      return true;
    }
    if (resp.base_available && (resp.conflicts || []).length > 0) {
      openConflicts(resp); // 冲突面板定夺，本轮保存未落盘待提交
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

async function doBoardSave(): Promise<void> {
  // 内容未变（查看/双击阅读等空操作）：跳过 PUT，不与 Agent 写入竞态
  const contentJson = boardContentJson();
  if (contentJson === syncedContentJson()) {
    boardDirty = false;
    setState('boardSaveStatus', 'saved');
    return;
  }
  setState('boardSaveStatus', 'saving');
  try {
    const resp = await putProjectState(boardSavePayload());
    boardDirty = false;
    setSyncedContentJson(contentJson);
    // 乐观锁版本跟进（修复）：后端每次落盘版本 +1，前端必须同步采纳，
    // 否则下一次 PUT 永远落后 1 被 409 拒 → 重同步冲掉用户编辑（加了又没加/删了又弹回）
    setState('boardVersion', typeof resp?.board_version === 'number'
      ? resp.board_version
      : state.boardVersion + 1);
    setState('boardSaveStatus', 'saved');
  } catch (e) {
    setState('boardSaveStatus', 'error');
    if (e instanceof ApiError && e.status === 409) {
      // 版本冲突：在途期间后端已写入 → 先尝试三向合并（G1）；
      // 合并不可行才回落旧语义（丢弃陈旧保存 + 重同步）；
      // 项目切换 409 依旧静默丢弃（旧项目的编辑不应写进新项目）
      if (/版本冲突/.test(e.message)) {
        if (await tryMergeOnConflict()) return;
        // 888 ：提示不得轻描淡写，必须明确告知编辑未保存需重做
        showToast('你刚才的编辑没有保存成功（期间 Agent 已更新故事板），页面已同步最新状态，请在最新状态上重做刚才的编辑', 'error');
        try {
          const snap = await getProjectState();
          boardSyncActions.syncFromServer(snap);
          setState('boardSaveStatus', 'saved');
        } catch { /* 同步失败保留本地态，下次编辑再试 */ }
      }
      return;
    }
    showToast(`保存失败：${(e as Error).message}`, 'error');
  }
}

const persistBoardInner = debounce(() => {
  saveChain = saveChain.then(doBoardSave, doBoardSave);
  return saveChain;
}, 400);

/** 故事板整体保存入口（400ms 防抖，对齐旧 persistBoard 行为）。
 * 携带 project_id：若请求在途期间后端已切换项目，后端返回 409，
 * 该过期写入直接丢弃（防止旧项目数据落进新项目，表现为两项目内容一致）。
 * 调度时标记 dirty，供 pagehide keepalive 冲刷判定。 */
interface PersistBoardFn {
  (): void;
  flush: () => Promise<void>;
  cancel: () => void;
}
export const persistBoard: PersistBoardFn = Object.assign(
  () => {
    boardDirty = true;
    persistBoardInner();
  },
  { flush: persistBoardInner.flush, cancel: persistBoardInner.cancel },
);

// ===== 页面卸载/隐藏冲刷：堵住"编辑后直接  → 防抖未触发/PUT 被剪断 → 刷新丢数据"的口子 =====
if (typeof window !== 'undefined') {
  // 标签页隐藏（切走/Alt+Tab）：异步冲刷，通常能完整送达
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden' && boardDirty) void persistBoardInner.flush();
  });
  // 页面卸载（/关闭）：keepalive 尽力送达；超 keepalive 配额时退化为普通请求兜底。
  // 冲刷走 api 层 flushProjectStateKeepalive（鉴权头 + keepalive + 兜底语义均收口在彼，
  // 铁律 10.1：stores 不得裸 fetch——曾因裸 fetch 被 401 截断导致卸载冲刷无效）。
  window.addEventListener('pagehide', () => {
    if (!boardDirty || !state.projectId) return;
    persistBoardInner.cancel();
    flushProjectStateKeepalive(boardSavePayload());
  });
}
