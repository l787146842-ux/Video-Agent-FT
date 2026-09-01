/** Studio store · 故事板服务端同步域（Q14 裁决 2026-09-01 方案 A：自 storyboard.ts 三分）。
 * 快照同步（生成中/编辑中保护 + 本地新增保护集合并）、项目切换重置、
 * 项目会话纪元与内容级脏检查基线持有（持久化域单向读取）。
 * 状态树不动；原签名经 storyboard.ts 重导出，调用方零改动。 */
import { produce } from 'solid-js/store';
import type { AnyGroup, ServerStateSnapshot } from '@/types';
import {
  state, setState, findDraftRecord, selectFirstDraft,
} from '../studio-core';
import { adjustScopes, adjustScopeActions } from '../adjust-scopes';

/** 项目会话纪元：每次项目切换/新建/删除自增。
 * 跨项目残留的异步回调（如旧项目 Agent 流的 SSE done）凭此被丢弃，
 * 防止旧项目快照覆盖新项目故事板（表现为切换后数据错乱/提示词丢失，刷新才恢复）。 */
let projectSession = 0;
export function getProjectSession(): number {
  return projectSession;
}

/** 内容级脏检查基线（业界基准 C4：读不触发写）：最近一次与服务器对齐的
 *  故事板内容 JSON；内容未变的"保存"直接跳过 PUT，杜绝查看/空操作与
 *  Agent 流式落盘竞出 409。同步域持有（快照即权威后跟进），持久化域读写。 */
let lastSyncedContentJson = '';
export function syncedContentJson(): string {
  return lastSyncedContentJson;
}
export function setSyncedContentJson(json: string): void {
  lastSyncedContentJson = json;
}

// ===== 本地新增保护：Agent 运行期间的快照整板替换不得冲掉用户刚手建的分组/草稿 =====

/** 本地新建但尚未被服务端快照确认的分组/草稿 ID；快照里出现即移出保护集 */
const localAddedIds = new Set<string>();

/** 编辑域登记本地新增实体（未落盘前不被快照冲掉） */
export function addLocalAddedId(id: string): void {
  localAddedIds.add(id);
}
/** 编辑域删除实体时移出保护集（防快照合并复活） */
export function removeLocalAddedId(id: string): void {
  localAddedIds.delete(id);
}

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

/** 快照内容基线原文（服务器持有的内容，非合并本地新增后的 state） */
function snapshotBaselineJson(snapshot: ServerStateSnapshot): string {
  return JSON.stringify({
    k: snapshot.keyElements ?? [], s: snapshot.shots ?? [],
    a: snapshot.audioItems ?? [], as: snapshot.assets ?? [],
  });
}

/** 微调线程注册表对账（评审修补批）：Agent FC/他窗删除经快照同步到达本窗时，
 *  前端无独立删除入口可挂级联，改在同步收口处对账——凡注册表键对应草稿已不在
 *  三板草稿集合也不在素材池来源（可还原移动豁免）即 dropThread；
 *  幂等重建语义不变（撤销恢复后重开入口照常）。 */
function reconcileScopeThreads() {
  const keys = Object.keys(adjustScopes);
  if (!keys.length) return;
  const alive = new Set<string>();
  for (const g of [...state.keyElements, ...state.shots, ...state.audioItems] as AnyGroup[]) {
    for (const d of g.drafts || []) alive.add(d.id);
  }
  for (const a of state.assets) if (a.sourceDraft?.id) alive.add(a.sourceDraft.id);
  for (const key of keys) if (!alive.has(key)) adjustScopeActions.dropThread(key);
}

/** 从后端状态快照同步（SSE done 事件 / 初始加载） */
function syncFromServer(snapshot: ServerStateSnapshot) {
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
    // 项目态活跃 Skill 绑定（批 C）：键在场即同步（含摘除态空 slug）；
    // 存量项目无此键时保留本地态（回落旧口径）
    if ('activeSkill' in snapshot) s.activeSkill = snapshot.activeSkill || null;
    if (snapshot.project_name) s.projectName = snapshot.project_name;
    if (snapshot.project_id) s.projectId = snapshot.project_id;
    if (typeof snapshot.board_version === 'number') s.boardVersion = snapshot.board_version;
  }));
  // 若当前选中草稿已不存在，自动选中第一个
  if (!findDraftRecord(state.selectedDraftId, state.selectedType)) {
    selectFirstDraft();
  }
  reconcileScopeThreads();
  // 服务器快照即权威：内容基线跟进，后续空保存将被脏检查跳过。
  // 注意基线记"服务器持有的内容"（快照原文），而非合并本地未落盘新增后
  // 的 state——否则本地新增会被脏检查误判为已同步而永不上传
  lastSyncedContentJson = snapshotBaselineJson(snapshot);
}

/** 项目切换/新建/删除后：重置选中态并整体替换项目数据 */
function resetForProject(snapshot: ServerStateSnapshot) {
  projectSession += 1; // 作废旧项目的在途异步回调（SSE done 等）
  localAddedIds.clear(); // 新项目的快照即权威，旧项目的本地新增保护集作废
  setState(produce((s) => {
    s.keyElements = snapshot.keyElements || [];
    s.shots = snapshot.shots || [];
    s.audioItems = snapshot.audioItems || [];
    s.assets = snapshot.assets || [];
    s.documents = snapshot.documents || [];
    s.usedSkills = snapshot.usedSkills || [];
    // 项目切换：新项目无绑定登记即回落自由对话（建议值另由 agent-prefs 呈现）
    s.activeSkill = snapshot.activeSkill || null;
    s.projectName = snapshot.project_name || '';
    s.projectId = snapshot.project_id || '';
    if (typeof snapshot.board_version === 'number') s.boardVersion = snapshot.board_version;
    s.editingDraftId = '';
    s.selectedDraftId = '';
    s.selectedType = 'keyElement';
    s.subTab = 'keyElements';
  }));
  selectFirstDraft();
  reconcileScopeThreads();
  lastSyncedContentJson = snapshotBaselineJson(snapshot);
}

/** 同步域动作（薄聚合层与编辑域合并为原 storyboardActions 导出） */
export const boardSyncActions = {
  syncFromServer,
  /** 初始加载完整状态（chatMessages 由 LayoutShell 灌入 chat store，此处不重复维护） */
  loadFullState(snapshot: ServerStateSnapshot) {
    syncFromServer(snapshot);
    if (!state.selectedDraftId) selectFirstDraft();
  },
  resetForProject,
};
