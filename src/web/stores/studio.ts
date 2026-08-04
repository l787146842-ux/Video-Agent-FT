/* eslint-disable max-lines -- 存量超行（铁律 10.1），待后续拆分；新增代码仍受规则约束 */
import { produce } from 'solid-js/store';
import type {
  DraftType, Draft, LeftTab, SubTab, AnyGroup,
  ApiProvider, Skill, PendingAttachment,
  ServerStateSnapshot,
} from '@/types';
import { putProjectState } from '@/api/project';
import { ApiError } from '@/api/client';
import { getSkills } from '@/api/agent';
import { showToast } from '@/stores/toast';
import { debounce, uid } from '@/lib/utils';
import {
  state, setState,
  fieldForType, fieldForSubTab, groupsForType,
  subTabForType, findDraftRecord, selectFirstDraft,
} from './studio-core';

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

// 对外统一出口：组件只需 import '@/stores/studio'
export {
  state, setState, groupsForType, subTabForType, normalizeDraftType,
  findDraftRecord, findGroupRecord, getCurrentDraft, selectFirstDraft,
} from './studio-core';
export type { StudioState } from './studio-core';

// ===== Actions =====
export const studioActions = {
  selectDraft(id: string, type: DraftType) {
    setState('selectedDraftId', id);
    setState('selectedType', type);
    setState('subTab', subTabForType(type));
  },

  /** 选中未归类素材：只在中间预览区展示媒体，不切换故事板 subTab */
  selectAsset(assetId: string) {
    setState('selectedDraftId', assetId);
  },

  /** 删除未归类素材（未归类面板右键菜单） */
  removeAssetLocal(assetId: string) {
    setState('assets', (prev) => prev.filter((a) => a.id !== assetId));
    if (state.selectedDraftId === assetId) setState('selectedDraftId', '');
    persistBoard();
  },

  setLeftTab(tab: LeftTab) {
    setState('leftTab', tab);
  },

  setSubTab(tab: SubTab) {
    // 切换故事板子页签不改变选中草稿：中间预览框不跟随故事板切换而变，
    // 需要定位时由预览框右下角导航按钮（locateSelectedInBoard）反向找回
    setState('subTab', tab);
  },

  /** 预览框导航按钮：左面板切到预览草稿所在子页签，选中该卡片并滚动定位 */
  locateSelectedInBoard() {
    const rec = findDraftRecord(state.selectedDraftId, state.selectedType);
    if (!rec) {
      showToast('当前没有选中任何草稿卡片', 'warning');
      return;
    }
    if (rec.group.id === '__assets__') {
      showToast('当前预览来自未归类素材，无法在故事板内定位', 'warning');
      return;
    }
    setState('leftTab', 'storyboard');
    setState('subTab', subTabForType(rec.type));
    setState('selectedType', rec.type);
    setState('locateTick', (v) => v + 1);
  },

  togglePromptCollapse() {
    setState('isPromptCollapsed', (v) => !v);
  },

  setAgentBusy(busy: boolean) {
    setState('agentBusy', busy);
  },

  setShowAllAssets(show: boolean) {
    setState('showAllAssets', show);
  },

  /** 全局"画布素材库"模态框开关（左栏 AssetCard / ChatInput 工具栏共用）。
   * 用 store 而非 component-local signal，避免 AssetCard 在 LeftPanel 里触发
   * LayoutShell 层级的 modal 时还要 prop drilling。 */
  openAssetLibrary() {
    setState('assetLibraryOpen', true);
  },
  closeAssetLibrary() {
    setState('assetLibraryOpen', false);
  },

  setPendingAttachments(items: PendingAttachment[]) {
    setState('pendingAttachments', items);
  },

  startGeneration(draftId: string, kind: 'image' | 'video', fromEpoch?: number) {
    // fromEpoch：刷新页面后从后端 processing 任务恢复读秒时，
    // 用任务创建时间回填，避免已耗时被重置为 0
    setState('activeGenerations', draftId, { start: fromEpoch || Date.now(), kind });
  },

  finishGeneration(draftId: string): number | null {
    const rec = state.activeGenerations[draftId];
    setState('activeGenerations', (prev) => {
      const next = { ...prev };
      delete next[draftId];
      return next;
    });
    return rec ? (Date.now() - rec.start) / 1000 : null;
  },

  /** 乐观登记已发送的 Skill slug（后端随快照回传权威值，此处先更新保证文档面板即时展示） */
  markSkillUsed(slug: string) {
    if (!slug || (state.usedSkills || []).includes(slug)) return;
    setState('usedSkills', (prev) => [...(prev || []), slug]);
  },

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
      if (Array.isArray(kes)) s.keyElements = kes as never;
      const shots = guard(snapshot.shots as never, s.shots as never);
      if (Array.isArray(shots)) s.shots = shots as never;
      const audios = guard(snapshot.audioItems as never, s.audioItems as never);
      if (Array.isArray(audios)) s.audioItems = audios as never;
      if (Array.isArray(snapshot.assets)) s.assets = snapshot.assets;
      if (Array.isArray(snapshot.documents)) s.documents = snapshot.documents;
      if (Array.isArray(snapshot.usedSkills)) s.usedSkills = snapshot.usedSkills;
      if (snapshot.project_name) s.projectName = snapshot.project_name;
      if (snapshot.project_id) s.projectId = snapshot.project_id;
    }));
    // 若当前选中草稿已不存在，自动选中第一个
    if (!findDraftRecord(state.selectedDraftId, state.selectedType)) {
      selectFirstDraft();
    }
  },

  /** 初始加载完整状态（chatMessages 由 LayoutShell 灌入 chat store，此处不重复维护） */
  loadFullState(snapshot: ServerStateSnapshot) {
    this.syncFromServer(snapshot);
    if (!state.selectedDraftId) selectFirstDraft();
  },

  /** 项目切换/新建/删除后：重置选中态并整体替换项目数据 */
  resetForProject(snapshot: ServerStateSnapshot) {
    projectSession += 1; // 作废旧项目的在途异步回调（SSE done 等）
    setState(produce((s) => {
      s.keyElements = snapshot.keyElements || [];
      s.shots = snapshot.shots || [];
      s.audioItems = snapshot.audioItems || [];
      s.assets = snapshot.assets || [];
      s.documents = snapshot.documents || [];
      s.usedSkills = snapshot.usedSkills || [];
      s.projectName = snapshot.project_name || '';
      s.projectId = snapshot.project_id || '';
      s.editingDraftId = '';
      s.selectedDraftId = '';
      s.selectedType = 'keyElement';
      s.subTab = 'keyElements';
    }));
    selectFirstDraft();
  },

  setApiConfig(config: {
    providers?: ApiProvider[];
    skills?: Skill[];
    chatModels?: string[];
    imageModels?: string[];
    videoModels?: string[];
    canvasUrl?: string;
  }) {
    setState(produce((s) => {
      if (config.providers) s.apiProviders = config.providers;
      if (config.skills) s.skills = config.skills;
      if (config.chatModels) s.availableChatModels = config.chatModels;
      if (config.imageModels) s.availableImageModels = config.imageModels;
      if (config.videoModels) s.availableVideoModels = config.videoModels;
      if (config.canvasUrl) s.canvasUrl = config.canvasUrl;
    }));
  },

  /** Agent 联动更新故事板后调用，驱动左面板闪烁提示 */
  markBoardApplied() {
    setState('lastAppliedAt', Date.now());
  },

  addPendingAttachment(att: PendingAttachment) {
    setState('pendingAttachments', (prev) => [...prev, att]);
  },

  removePendingAttachment(id: string) {
    setState('pendingAttachments', (prev) => prev.filter((a) => a.id !== id));
  },

  // ===== 草稿/分组本地编辑（编辑后调 persistBoard 持久化） =====

  /** 手动新建分组（底部 + 按钮，追加到末尾） */
  addGroupLocal(subTab: SubTab) {
    const field = fieldForSubTab(subTab);
    const ordinal = (state[field] as AnyGroup[]).length + 1;
    const { group, draftId } = buildDefaultGroup(subTab, ordinal);
    setState(field, (prev: AnyGroup[]) => [...prev, group]);
    this.selectDraft(draftId, draftTypeForSubTab(subTab));
    persistBoard();
  },

  /** 在指定位置插入新分组（列表右键菜单：向上/向下插入）。
   * index 为插入后的目标下标（0-based，越界自动夹取） */
  insertGroupLocal(subTab: SubTab, index: number) {
    const field = fieldForSubTab(subTab);
    const list = state[field] as AnyGroup[];
    const clamped = Math.max(0, Math.min(index, list.length));
    const { group, draftId } = buildDefaultGroup(subTab, clamped + 1);
    setState(field, (prev: AnyGroup[]) => {
      const next = [...prev];
      next.splice(clamped, 0, group);
      return next;
    });
    this.selectDraft(draftId, draftTypeForSubTab(subTab));
    persistBoard();
  },

  /** 删除分组（列表右键菜单，删除前由调用方做确认弹窗） */
  removeGroupLocal(subTab: SubTab, groupId: string) {
    const field = fieldForSubTab(subTab);
    const target = (state[field] as AnyGroup[]).find((g) => g.id === groupId);
    if (!target) return;
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
    const draft: Draft =
      type === 'keyElement'
        ? { id: newId, label: '自定义草稿', tag: '手动', mediaType: 'image', imgUrl: '', prompt: '', model: '', aspectRatio: '16:9' }
        : type === 'shot'
          ? { id: newId, label: '自定义分镜', tag: '手动', mediaType: 'video', videoUrl: '', prompt: '', mode: '图生视频', model: '' }
          : { id: newId, label: '自定义音频', tag: '手动', mediaType: 'audio', audioUrl: '', prompt: '' };
    setState(field, (prev: AnyGroup[]) =>
      prev.map((g) => (g.id === groupId ? { ...g, drafts: [...(g.drafts || []), draft] } : g)),
    );
    this.selectDraft(newId, type);
    persistBoard();
  },

  /** 删除草稿（右键菜单） */
  removeDraftLocal(type: DraftType, groupId: string, draftId: string) {
    const field = fieldForType(type);
    const group = groupsForType(type).find((g) => g.id === groupId);
    if (!group) return;
    const remaining = (group.drafts || []).filter((d) => d.id !== draftId);
    setState(field, (prev: AnyGroup[]) =>
      prev.map((g) => (g.id === groupId ? { ...g, drafts: remaining } : g)),
    );
    if (state.selectedDraftId === draftId) {
      setState('selectedDraftId', remaining[0]?.id || '');
    }
    persistBoard();
  },

  /** 移除草稿到未归类素材 */
  moveDraftToAssets(type: DraftType, groupId: string, draftId: string) {
    const group = groupsForType(type).find((g) => g.id === groupId);
    const draft = group?.drafts?.find((d) => d.id === draftId);
    if (!group || !draft) return;
    this.removeDraftLocal(type, groupId, draftId);
    setState('assets', (prev) => [
      {
        id: uid('ast'),
        name: draft.label || '未命名素材',
        type: draft.mediaType || 'image',
        isBound: false,
        url: draft.imgUrl || draft.videoUrl || draft.audioUrl || '',
      },
      ...prev,
    ]);
    showToast('已移除到未归类素材', 'success');
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
    setState(field, (prev: AnyGroup[]) =>
      prev.map((g) => {
        if (!(g.drafts || []).some((d) => d.id === draftId)) return g;
        return {
          ...g,
          drafts: (g.drafts || []).map((d) => (d.id === draftId ? { ...d, ...patch } : d)),
        };
      }),
    );
    persistBoard();
  },

  /** 按标题跳转到关键元素（分镜 sceneRefs chip 点击） */
  jumpToElementByTitle(title: string) {
    const el = state.keyElements.find((k) => k.title === title);
    if (!el) {
      showToast(`未找到关键元素「${title}」`, 'warning');
      return;
    }
    setState('leftTab', 'storyboard');
    setState('subTab', 'keyElements');
    if (el.drafts?.length) {
      setState('selectedDraftId', el.drafts[0].id);
      setState('selectedType', 'keyElement');
    }
  },
};

// ===== 持久化 =====

/** 故事板整体保存（400ms 防抖，对齐旧 persistBoard 行为）。
 * 携带 project_id：若请求在途期间后端已切换项目，后端返回 409，
 * 该过期写入直接丢弃（防止旧项目数据落进新项目，表现为两项目内容一致） */
export const persistBoard = debounce(async () => {
  try {
    await putProjectState({
      project_id: state.projectId,
      keyElements: state.keyElements,
      shots: state.shots,
      audioItems: state.audioItems,
      assets: state.assets,
    });
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) return; // 跨项目的过期保存，丢弃
    showToast(`保存失败：${(e as Error).message}`, 'error');
  }
}, 400);

/** 当前 subTab 对应的后端 category 名 */
export function categoryForSubTab(subTab: SubTab): string {
  return fieldForSubTab(subTab);
}

/** 重新加载 Skill 列表（导入新 Skill 后调用） */
export async function refreshSkills(): Promise<void> {
  try {
    const skills = await getSkills();
    setState('skills', skills);
  } catch { /* 静默失败 */ }
}
