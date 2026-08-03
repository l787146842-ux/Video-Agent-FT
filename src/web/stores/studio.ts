/* eslint-disable max-lines -- 存量超行（铁律 10.1），待后续拆分；新增代码仍受规则约束 */
import { produce } from 'solid-js/store';
import type {
  DraftType, Draft, LeftTab, SubTab, AnyGroup,
  KeyElementGroup, ShotGroup, AudioGroup,
  ApiProvider, Skill, PendingAttachment,
  ServerStateSnapshot,
} from '@/types';
import { putProjectState } from '@/api/project';
import { getSkills } from '@/api/agent';
import { showToast } from '@/stores/toast';
import { debounce, uid } from '@/lib/utils';
import {
  state, setState,
  fieldForType, fieldForSubTab, groupsForType,
  subTabForType, findDraftRecord, selectFirstDraft,
} from './studio-core';

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
    // 切换 tab 时同步 selectedType，并自动选中新 tab 的第一个草稿
    const type: DraftType = tab === 'shots' ? 'shot' : tab === 'audio' ? 'audio' : 'keyElement';
    const field = fieldForSubTab(tab);
    const groups = state[field] as AnyGroup[];
    const firstDraftId = groups?.[0]?.drafts?.[0]?.id || '';
    // 单次原子更新，避免中间状态触发 effect 级联
    setState(produce((s) => {
      s.subTab = tab;
      s.selectedType = type;
      s.selectedDraftId = firstDraftId;
    }));
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

  startGeneration(draftId: string, kind: 'image' | 'video') {
    setState('activeGenerations', draftId, { start: Date.now(), kind });
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
    setState(produce((s) => {
      if (Array.isArray(snapshot.keyElements)) s.keyElements = snapshot.keyElements;
      if (Array.isArray(snapshot.shots)) s.shots = snapshot.shots;
      if (Array.isArray(snapshot.audioItems)) s.audioItems = snapshot.audioItems;
      if (Array.isArray(snapshot.assets)) s.assets = snapshot.assets;
      if (Array.isArray(snapshot.documents)) s.documents = snapshot.documents;
      if (Array.isArray(snapshot.usedSkills)) s.usedSkills = snapshot.usedSkills;
      if (snapshot.project_name) s.projectName = snapshot.project_name;
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
    setState(produce((s) => {
      s.keyElements = snapshot.keyElements || [];
      s.shots = snapshot.shots || [];
      s.audioItems = snapshot.audioItems || [];
      s.assets = snapshot.assets || [];
      s.documents = snapshot.documents || [];
      s.usedSkills = snapshot.usedSkills || [];
      s.projectName = snapshot.project_name || '';
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

  /** 手动新建分组（底部 + 按钮） */
  addGroupLocal(subTab: SubTab) {
    const field = fieldForSubTab(subTab);
    const groups = state[field] as AnyGroup[];
    const idx = groups.length + 1;
    const type: DraftType = subTab === 'shots' ? 'shot' : subTab === 'audio' ? 'audio' : 'keyElement';
    const gid = uid('grp');
    const did = uid('draft');

    let group: AnyGroup;
    if (type === 'keyElement') {
      group = { id: gid, title: `Element_未命名${idx > 1 ? idx : ''}`, desc: '', drafts: [{ id: did, label: `草稿 ${idx}`, tag: '手动', mediaType: 'image', imgUrl: '', prompt: '', model: '', aspectRatio: '1:1' }] };
    } else if (type === 'shot') {
      group = { id: gid, title: `Shot_未命名${idx > 1 ? idx : ''}`, duration: '5s', roughDesc: '', drafts: [{ id: did, label: `分镜 ${idx}`, tag: '手动', mediaType: 'video', videoUrl: '', prompt: '', mode: '全能参考', model: '' }] };
    } else {
      group = { id: gid, title: `Audio_未命名${idx > 1 ? idx : ''}`, timeRange: '', prompt: '', drafts: [{ id: did, label: `音频 ${idx}`, tag: '手动', mediaType: 'audio', audioUrl: '', prompt: '' }] };
    }

    setState(field, (prev: AnyGroup[]) => [...prev, group]);
    this.selectDraft(did, type);
    persistBoard();
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

  /** 局部更新草稿字段（参数控件/Prompt 编辑，防抖持久化） */
  updateDraftLocal(type: DraftType, draftId: string, patch: Partial<Draft>) {
    const field = fieldForType(type);
    setState(field, (prev: AnyGroup[]) =>
      prev.map((g) => ({
        ...g,
        drafts: (g.drafts || []).map((d) => (d.id === draftId ? { ...d, ...patch } : d)),
      })),
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

/** 故事板整体保存（400ms 防抖，对齐旧 persistBoard 行为） */
export const persistBoard = debounce(async () => {
  try {
    await putProjectState({
      keyElements: state.keyElements,
      shots: state.shots,
      audioItems: state.audioItems,
      assets: state.assets,
    });
  } catch (e) {
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
