/* eslint-disable max-lines -- 故事板域集中了本地编辑/同步/持久化/卸载冲刷，超行属合理；新增代码仍受规则约束 */
/** Studio store · 故事板域（从 studio.ts 拆出）：分组/草稿本地编辑、服务端同步、持久化 */
import { produce } from 'solid-js/store';
import type {
  DraftType, Draft, SubTab, AnyGroup, ServerStateSnapshot,
} from '@/types';
import { putProjectState, getProjectState } from '@/api/project';
import { ApiError, buildAuthHeaders } from '@/api/client';
import { showToast } from '@/stores/toast';
import { debounce, uid } from '@/lib/utils';
import {
  state, setState,
  fieldForType, fieldForSubTab, groupsForType,
  findDraftRecord, selectFirstDraft,
} from '../studio-core';
import { uiActions } from './ui';

/** subTab → 草稿类型 */
function draftTypeForSubTab(subTab: SubTab): DraftType {
  return subTab === 'shots' ? 'shot' : subTab === 'audio' ? 'audio' : 'keyElement';
}

/** 项目会话纪元：每次项目切换/新建/删除自增。
 * 跨项目残留的异步回调（如旧项目 Agent 流的 SSE done）凭此被丢弃，
 * 防止旧项目快照覆盖新项目故事板（表现为切换后数据错乱/提示词丢失，刷新才恢复）。 */
let projectSession = 0;
export function getProjectSession(): number {
  return projectSession;
}

/** 构建默认分组模板（含一个默认草稿），供追加/指定位置插入共用 */
function buildDefaultGroup(subTab: SubTab, ordinal: number): { group: AnyGroup; draftId: string } {
  const type = draftTypeForSubTab(subTab);
  const gid = uid('grp');
  const did = uid('draft');
  let group: AnyGroup;
  if (type === 'keyElement') {
    group = { id: gid, title: `Element_未命名${ordinal > 1 ? ordinal : ''}`, desc: '', drafts: [{ id: did, label: `草稿 ${ordinal}`, tag: '手动', mediaType: 'image', imgUrl: '', prompt: '', model: '', aspectRatio: '1:1' }] };
  } else if (type === 'shot') {
    group = { id: gid, title: `Shot_未命名${ordinal > 1 ? ordinal : ''}`, duration: '5s', roughDesc: '', drafts: [{ id: did, label: `分镜 ${ordinal}`, tag: '手动', mediaType: 'video', videoUrl: '', prompt: '', mode: '全能参考', model: '' }] };
  } else {
    group = { id: gid, title: `Audio_未命名${ordinal > 1 ? ordinal : ''}`, timeRange: '', prompt: '', drafts: [{ id: did, label: `音频 ${ordinal}`, tag: '手动', mediaType: 'audio', audioUrl: '', prompt: '' }] };
  }
  return { group, draftId: did };
}

// ===== 持久化 =====

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

/** 内容级脏检查（业界基准 C4：读不触发写）：记录最近一次与服务器对齐的
 *  故事板内容 JSON；内容未变的"保存"直接跳过 PUT，杜绝查看/空操作与
 *  Agent 流式落盘竞出 409 */
let lastSyncedContentJson = '';

function boardContentJson(): string {
  return JSON.stringify({
    k: state.keyElements, s: state.shots, a: state.audioItems, as: state.assets,
  });
}

/** 串行化保存链：防抖触发与 flush 并发时两个 PUT 携同一 base_version 互撞，
 *  后者必被 409 拒引发整板重同步闪烁；串行后每次 PUT 都读到最新版本 */
let saveChain: Promise<void> = Promise.resolve();

async function doBoardSave(): Promise<void> {
  // 内容未变（查看/双击阅读等空操作）：跳过 PUT，不与 Agent 写入竞态
  const contentJson = boardContentJson();
  if (contentJson === lastSyncedContentJson) {
    boardDirty = false;
    setState('boardSaveStatus', 'saved');
    return;
  }
  setState('boardSaveStatus', 'saving');
  try {
    const resp = await putProjectState(boardSavePayload());
    boardDirty = false;
    lastSyncedContentJson = contentJson;
    // 乐观锁版本跟进（修复）：后端每次落盘版本 +1，前端必须同步采纳，
    // 否则下一次 PUT 永远落后 1 被 409 拒 → 重同步冲掉用户编辑（加了又没加/删了又弹回）
    setState('boardVersion', typeof resp?.board_version === 'number'
      ? resp.board_version
      : state.boardVersion + 1);
    setState('boardSaveStatus', 'saved');
  } catch (e) {
    setState('boardSaveStatus', 'error');
    if (e instanceof ApiError && e.status === 409) {
      // 版本冲突：在途期间后端已写入 → 丢弃本次陈旧保存，重新同步最新状态；
      // 项目切换 409 依旧静默丢弃（旧项目的编辑不应写进新项目）
      if (/版本冲突/.test(e.message)) {
        // 888 ：提示不得轻描淡写，必须明确告知编辑未保存需重做
        showToast('你刚才的编辑没有保存成功（期间 Agent 已更新故事板），页面已同步最新状态，请在最新状态上重做刚才的编辑', 'error');
        try {
          const snap = await getProjectState();
          storyboardActions.syncFromServer(snap);
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
  // 页面卸载（/关闭）：keepalive 尽力送达；超 keepalive 配额时退化为普通 fetch 兜底。
  // 鉴权头走 buildAuthHeaders 唯一出口：生产模式中间件对 /api/ 强制校验，
  // 裸 fetch 会被 401 截断导致卸载冲刷无效（任务#12 批次2 追加修复）。
  window.addEventListener('pagehide', () => {
    if (!boardDirty || !state.projectId) return;
    persistBoardInner.cancel();
    const payload = JSON.stringify(boardSavePayload());
    const headers = { 'Content-Type': 'application/json', ...buildAuthHeaders() };
    try {
      void fetch('/api/project/state', {
        method: 'PUT',
        keepalive: true,
        headers,
        body: payload,
      });
    } catch {
      try {
        void fetch('/api/project/state', {
          method: 'PUT',
          headers,
          body: payload,
        });
      } catch { /* 静默：卸载期最后防线，不阻塞页面退出 */ }
    }
  });
}

// ===== 本地新增保护：Agent 运行期间的快照整板替换不得冲掉用户刚手建的分组/草稿 =====

/** 本地新建但尚未被服务端快照确认的分组/草稿 ID；快照里出现即移出保护集 */
const localAddedIds = new Set<string>();

/** 把本地新增的分组/草稿合并回服务端快照（仅保护 localAddedIds 里的实体） */
function mergeLocalAdditions<G extends { id: string; drafts?: Array<{ id: string }> }>(
  incoming: G[],
  local: G[] | undefined,
): G[] {
  if (!localAddedIds.size || !local) return incoming;
  const inGroupIds = new Set(incoming.map((g) => g.id));
  const merged = incoming.map((g) => {
    const lg = local.find((x) => x.id === g.id);
    const added = (lg?.drafts || []).filter((d) => localAddedIds.has(d.id));
    if (!added.length) return g;
    const have = new Set((g.drafts || []).map((d) => d.id));
    const missing = added.filter((d) => !have.has(d.id));
    return missing.length ? { ...g, drafts: [...(g.drafts || []), ...missing] } : g;
  });
  for (const g of local) {
    if (localAddedIds.has(g.id) && !inGroupIds.has(g.id)) merged.push(g);
  }
  // 快照里已出现的实体视为已落盘，移出保护集
  for (const g of incoming) {
    localAddedIds.delete(g.id);
    for (const d of g.drafts || []) localAddedIds.delete(d.id);
  }
  return merged;
}

export const storyboardActions = {
  /** 从后端状态快照同步（SSE done 事件 / 初始加载） */
  syncFromServer(snapshot: ServerStateSnapshot) {
    // 保护生成中的草稿：agent done 快照可能早于生成结果写回，
    // 直接覆盖会把刚出图的 imgUrl 冲掉；仍在转圈的草稿保留本地媒体字段。
    // 同样保护正在提示词编辑器中聚焦编辑的草稿：快照里的旧 prompt
    // 不得覆盖用户尚未防抖落盘的输入（否则输入丢失，且随后 PUT 把旧值写回后端）
    const active = state.activeGenerations;
    const editingId = state.editingDraftId;
    const guard = <T extends { id: string; prompt?: string; imgUrl?: string; videoUrl?: string; audioUrl?: string; mediaType?: string; tag?: string }>(
      incoming: T[] | undefined,
      local: T[] | undefined,
    ): T[] | undefined => {
      if (!Array.isArray(incoming)) return incoming;
      const activeIds = new Set(Object.keys(active));
      if (!activeIds.size && !editingId) return incoming;
      return incoming.map((g) => {
        const drafts = (g as unknown as { drafts?: T[] }).drafts;
        if (!Array.isArray(drafts)) return g;
        const localDrafts = ((local || []) as unknown as Array<{ drafts?: T[] }>).find(
          (lg) => (lg as unknown as { id?: string }).id === (g as unknown as { id?: string }).id,
        )?.drafts;
        (g as unknown as { drafts: T[] }).drafts = drafts.map((d) => {
          const isActive = activeIds.has(d.id);
          const isEditing = !!editingId && d.id === editingId;
          if (!isActive && !isEditing) return d;
          const ld = localDrafts?.find((x) => x.id === d.id);
          if (!ld) return d;
          const merged = { ...d };
          if (isActive) {
            merged.imgUrl = ld.imgUrl;
            merged.videoUrl = ld.videoUrl;
            merged.audioUrl = ld.audioUrl;
            merged.mediaType = ld.mediaType;
            merged.tag = ld.tag;
          }
          if (isEditing && typeof ld.prompt === 'string') merged.prompt = ld.prompt;
          return merged;
        });
        return g;
      });
    };

    setState(produce((s) => {
      const kes = guard(snapshot.keyElements as never, s.keyElements as never);
      if (Array.isArray(kes)) s.keyElements = mergeLocalAdditions(kes as AnyGroup[], s.keyElements as AnyGroup[]) as never;
      const shots = guard(snapshot.shots as never, s.shots as never);
      if (Array.isArray(shots)) s.shots = mergeLocalAdditions(shots as AnyGroup[], s.shots as AnyGroup[]) as never;
      const audios = guard(snapshot.audioItems as never, s.audioItems as never);
      if (Array.isArray(audios)) s.audioItems = mergeLocalAdditions(audios as AnyGroup[], s.audioItems as AnyGroup[]) as never;
      if (Array.isArray(snapshot.assets)) s.assets = snapshot.assets;
      if (Array.isArray(snapshot.documents)) s.documents = snapshot.documents;
      if (Array.isArray(snapshot.usedSkills)) s.usedSkills = snapshot.usedSkills;
      if (snapshot.project_name) s.projectName = snapshot.project_name;
      if (snapshot.project_id) s.projectId = snapshot.project_id;
      if (typeof snapshot.board_version === 'number') s.boardVersion = snapshot.board_version;
    }));
    // 若当前选中草稿已不存在，自动选中第一个
    if (!findDraftRecord(state.selectedDraftId, state.selectedType)) {
      selectFirstDraft();
    }
    // 服务器快照即权威：内容基线跟进，后续空保存将被脏检查跳过。
    // 注意基线记"服务器持有的内容"（快照原文），而非合并本地未落盘新增后
    // 的 state——否则本地新增会被脏检查误判为已同步而永不上传
    lastSyncedContentJson = JSON.stringify({
      k: snapshot.keyElements ?? [], s: snapshot.shots ?? [],
      a: snapshot.audioItems ?? [], as: snapshot.assets ?? [],
    });
  },

  /** 初始加载完整状态（chatMessages 由 LayoutShell 灌入 chat store，此处不重复维护） */
  loadFullState(snapshot: ServerStateSnapshot) {
    this.syncFromServer(snapshot);
    if (!state.selectedDraftId) selectFirstDraft();
  },

  /** 项目切换/新建/删除后：重置选中态并整体替换项目数据 */
  resetForProject(snapshot: ServerStateSnapshot) {
    projectSession += 1; // 作废旧项目的在途异步回调（SSE done 等）
    localAddedIds.clear(); // 新项目的快照即权威，旧项目的本地新增保护集作废
    setState(produce((s) => {
      s.keyElements = snapshot.keyElements || [];
      s.shots = snapshot.shots || [];
      s.audioItems = snapshot.audioItems || [];
      s.assets = snapshot.assets || [];
      s.documents = snapshot.documents || [];
      s.usedSkills = snapshot.usedSkills || [];
      s.projectName = snapshot.project_name || '';
      s.projectId = snapshot.project_id || '';
      if (typeof snapshot.board_version === 'number') s.boardVersion = snapshot.board_version;
      s.editingDraftId = '';
      s.selectedDraftId = '';
      s.selectedType = 'keyElement';
      s.subTab = 'keyElements';
    }));
    selectFirstDraft();
    lastSyncedContentJson = JSON.stringify({
      k: snapshot.keyElements ?? [], s: snapshot.shots ?? [],
      a: snapshot.audioItems ?? [], as: snapshot.assets ?? [],
    });
  },

  // ===== 草稿/分组本地编辑（编辑后调 persistBoard 持久化） =====

  /** 手动新建分组（底部 + 按钮，追加到末尾） */
  addGroupLocal(subTab: SubTab) {
    const field = fieldForSubTab(subTab);
    const ordinal = (state[field] as AnyGroup[]).length + 1;
    const { group, draftId } = buildDefaultGroup(subTab, ordinal);
    localAddedIds.add(group.id).add(draftId); // D2：未落盘前不被快照冲掉
    setState(field, (prev: AnyGroup[]) => [...prev, group]);
    uiActions.selectDraft(draftId, draftTypeForSubTab(subTab));
    persistBoard();
  },

  /** 在指定位置插入新分组（列表右键菜单：向上/向下插入）。
   * index 为插入后的目标下标（0-based，越界自动夹取） */
  insertGroupLocal(subTab: SubTab, index: number) {
    const field = fieldForSubTab(subTab);
    const list = state[field] as AnyGroup[];
    const clamped = Math.max(0, Math.min(index, list.length));
    const { group, draftId } = buildDefaultGroup(subTab, clamped + 1);
    localAddedIds.add(group.id).add(draftId); // D2：未落盘前不被快照冲掉
    setState(field, (prev: AnyGroup[]) => {
      const next = [...prev];
      next.splice(clamped, 0, group);
      return next;
    });
    uiActions.selectDraft(draftId, draftTypeForSubTab(subTab));
    persistBoard();
  },

  /** 删除分组（列表右键菜单，删除前由调用方做确认弹窗） */
  removeGroupLocal(subTab: SubTab, groupId: string) {
    const field = fieldForSubTab(subTab);
    const target = (state[field] as AnyGroup[]).find((g) => g.id === groupId);
    if (!target) return;
    // ：删除的实体移出本地新增保护集，避免后续快照合并时被复活
    localAddedIds.delete(groupId);
    for (const d of target.drafts || []) localAddedIds.delete(d.id);
    setState(field, (prev: AnyGroup[]) => prev.filter((g) => g.id !== groupId));
    // 若当前选中草稿在被删分组内，自动改选第一个
    if ((target.drafts || []).some((d) => d.id === state.selectedDraftId)) {
      selectFirstDraft();
    }
    persistBoard();
    showToast(`已删除「${target.title || '未命名分组'}」`, 'success');
  },

  /** 重命名分组标题/描述/徽标（双击编辑） */
  renameGroupLocal(type: DraftType, groupId: string, patch: Record<string, string>) {
    const field = fieldForType(type);
    setState(field, (prev: AnyGroup[]) =>
      prev.map((g) => {
        if (g.id !== groupId) return g;
        const updated = { ...g } as Record<string, unknown>;
        if (patch.title !== undefined) updated.title = patch.title;
        if (patch.desc !== undefined) {
          if (type === 'keyElement') updated.desc = patch.desc;
          else if (type === 'shot') updated.roughDesc = patch.desc;
          else updated.prompt = patch.desc;
        }
        if (patch.badgeLabel !== undefined) updated.badgeLabel = patch.badgeLabel;
        if (patch.shotType !== undefined) updated.shotType = patch.shotType;
        if (patch.timeRange !== undefined) updated.timeRange = patch.timeRange;
        return updated as unknown as AnyGroup;
      }),
    );
    persistBoard();
  },

  /** 手动新建草稿卡片（+ 按钮） */
  addDraftLocal(type: DraftType, groupId: string) {
    const field = fieldForType(type);
    const newId = uid('draft');
    localAddedIds.add(newId); // D2：未落盘前不被快照冲掉
    const draft: Draft =
      type === 'keyElement'
        ? { id: newId, label: '自定义草稿', tag: '手动', mediaType: 'image', imgUrl: '', prompt: '', model: '', aspectRatio: '16:9' }
        : type === 'shot'
          ? { id: newId, label: '自定义分镜', tag: '手动', mediaType: 'video', videoUrl: '', prompt: '', mode: '图生视频', model: '' }
          : { id: newId, label: '自定义音频', tag: '手动', mediaType: 'audio', audioUrl: '', prompt: '' };
    setState(field, (prev: AnyGroup[]) =>
      prev.map((g) => (g.id === groupId ? { ...g, drafts: [...(g.drafts || []), draft] } : g)),
    );
    uiActions.selectDraft(newId, type);
    persistBoard();
  },

  /** 删除草稿（右键菜单） */
  removeDraftLocal(type: DraftType, groupId: string, draftId: string) {
    const field = fieldForType(type);
    const group = groupsForType(type).find((g) => g.id === groupId);
    if (!group) return;
    const remaining = (group?.drafts || []).filter((d) => d.id !== draftId);
    localAddedIds.delete(draftId); // D2：删除的草稿移出保护集，防快照合并复活
    setState(field, (prev: AnyGroup[]) =>
      prev.map((g) => (g.id === groupId ? { ...g, drafts: remaining } : g)),
    );
    if (state.selectedDraftId === draftId) {
      setState('selectedDraftId', remaining[0]?.id || '');
    }
    persistBoard();
  },

  /** 分镜场景引用增删（C4）：本地更新后走防抖整板保存（与其他本地编辑同路径）。
   * 删除某元素后：出视频不再自动挂该元素概念图，卡片场景 chips 同步消失 */
  setSceneRefsLocal(groupId: string, refs: string[]) {
    setState('shots', (prev: AnyGroup[]) =>
      prev.map((g) => (g.id === groupId ? { ...g, sceneRefs: refs } : g)),
    );
    persistBoard();
  },

  /** 分组拖拽排序（本地重排，调用方负责后端同步） */
  reorderGroupsLocal(subTab: SubTab, srcId: string, targetId: string) {
    const field = fieldForSubTab(subTab);
    const groups = [...(state[field] as AnyGroup[])];
    const srcIdx = groups.findIndex((g) => g.id === srcId);
    const tgtIdx = groups.findIndex((g) => g.id === targetId);
    if (srcIdx < 0 || tgtIdx < 0) return;
    const [moved] = groups.splice(srcIdx, 1);
    groups.splice(tgtIdx, 0, moved);
    setState(field, groups as never);
  },

  /** 组内草稿卡片拖拽排序（小标编号随位置自动重排），防抖持久化 */
  reorderDraftLocal(type: DraftType, groupId: string, srcDraftId: string, tgtDraftId: string) {
    const field = fieldForType(type);
    setState(field, (prev: AnyGroup[]) =>
      prev.map((g) => {
        if (g.id !== groupId) return g;
        const drafts = [...(g.drafts || [])];
        const srcIdx = drafts.findIndex((d) => d.id === srcDraftId);
        const tgtIdx = drafts.findIndex((d) => d.id === tgtDraftId);
        if (srcIdx < 0 || tgtIdx < 0) return g;
        const [movedDraft] = drafts.splice(srcIdx, 1);
        drafts.splice(tgtIdx, 0, movedDraft);
        return { ...g, drafts };
      }),
    );
    persistBoard();
  },

  /** 局部更新草稿字段（参数控件/Prompt 编辑，防抖持久化）。
   * 注意：未命中目标草稿的分组必须原样返回（保持引用不变），
   * 否则 <For> 按引用 diff 会把整个分组列表当作全新节点重建——
   * 每次点卡片/输入提示词都全量重渲染左栏（含视频缩略图重新加载），造成明显卡顿。 */
  updateDraftLocal(type: DraftType, draftId: string, patch: Partial<Draft>) {
    const field = fieldForType(type);
    // 无实际变化直接返回：不替换数组、不触发 persistBoard，
    // 避免整组级联重算与无效 PUT（点击卡片时的校正 effect 是主要调用源）
    const target = (state[field] as AnyGroup[]).flatMap((g) => g.drafts || []).find((d) => d.id === draftId);
    if (!target) return;
    const changed = (Object.keys(patch) as Array<keyof Draft>).some((k) => target[k] !== patch[k]);
    if (!changed) return;
    setState(field, (prev: AnyGroup[]) => prev.map((g) => {
      if (!(g.drafts || []).some((d) => d.id === draftId)) return g;
      return { ...g, drafts: g.drafts!.map((d) => (d.id === draftId ? { ...d, ...patch } : d)) };
    }));
    persistBoard();
  },
};

/** 当前 subTab 对应的后端 category 名 */
export function categoryForSubTab(subTab: SubTab): string {
  return fieldForSubTab(subTab);
}
