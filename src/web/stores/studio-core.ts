import { createStore } from 'solid-js/store';
import type {
  DraftType, Draft, LeftTab, SubTab, AnyGroup,
  KeyElementGroup, ShotGroup, AudioGroup,
  Asset, ApiProvider, Skill, PendingAttachment,
  DocRecord, ActiveGeneration,
  DraftRecord, GroupRecord,
} from '@/types';

// ===== State 接口 =====
export interface StudioState {
  leftTab: LeftTab;
  subTab: SubTab;
  showAllAssets: boolean;
  selectedDraftId: string;
  selectedType: DraftType;
  isPromptCollapsed: boolean;
  /** 画布素材库全局模态框开关（左栏 AssetCard / ChatInput 工具栏共用） */
  assetLibraryOpen: boolean;
  apiProviders: ApiProvider[];
  skills: Skill[];
  /* agentBusy 已迁 chat/agent 域（任务 #11）：见 stores/agent-state.ts */
  pendingAttachments: PendingAttachment[];
  keyElements: KeyElementGroup[];
  shots: ShotGroup[];
  audioItems: AudioGroup[];
  assets: Asset[];
  documents: DocRecord[];
  availableChatModels: string[];
  availableImageModels: string[];
  availableVideoModels: string[];
  canvasUrl: string;
  activeGenerations: Record<string, ActiveGeneration>;
  projectName: string;
  /** 当前项目 ID（来自后端快照 project_id，persistBoard 回传供后端校验防止跨项目写入） */
  projectId: string;
  /** 提示词编辑器聚焦中的草稿 ID（SSE done 快照同步时保护其 prompt 不被覆盖） */
  editingDraftId: string;
  /** 当前项目已发送给 Agent 的 Skill slug（文档面板只展示这些 Skill 文档） */
  usedSkills: string[];
  /** Agent 联动更新故事板的时间戳（驱动左面板闪烁动画） */
  lastAppliedAt: number;
  /** 预览框导航按钮触发左面板定位的计数（驱动滚动到选中卡片并闪烁） */
  locateTick: number;
  /** 定位目标分组 ID（分镜 sceneRefs 点击跳转用；无草稿卡可选时按分组定位） */
  locateGroupId: string;
  /** 选中操作单调序号：每次 selectDraft/selectAsset 自增。
   * findDraftRecord 响应式读取它，保证"重复点击同一张卡"也能强制所有预览派生重算，
   * 规避 Solid store 同值零通知导致的预览停留问题。 */
  selectTick: number;
  /** 故事板保存状态（D1）：saving=PUT 在途；saved=最近一次保存成功；error=保存失败（顶部常驻提示） */
  boardSaveStatus: 'saving' | 'saved' | 'error';
  /** 故事板乐观锁版本（D2）：来自后端快照 board_version，整板保存回携防陈旧覆盖 */
  boardVersion: number;
}

const defaultState: StudioState = {
  leftTab: 'storyboard',
  subTab: 'keyElements',
  showAllAssets: false,
  selectedDraftId: '',
  selectedType: 'keyElement',
  isPromptCollapsed: false,
  assetLibraryOpen: false,
  apiProviders: [],
  skills: [],
  pendingAttachments: [],
  keyElements: [],
  shots: [],
  audioItems: [],
  assets: [],
  documents: [],
  availableChatModels: [],
  availableImageModels: [],
  availableVideoModels: [],
  canvasUrl: 'http://localhost:3000',
  activeGenerations: {},
  projectName: '',
  projectId: '',
  editingDraftId: '',
  usedSkills: [],
  lastAppliedAt: 0,
  locateTick: 0,
  locateGroupId: '',
  selectTick: 0,
  boardSaveStatus: 'saved',
  boardVersion: 0,
};

const [state, setState] = createStore<StudioState>(defaultState);

// ===== 字段映射 =====

export function fieldForType(type: DraftType): 'keyElements' | 'shots' | 'audioItems' {
  return type === 'shot' ? 'shots' : type === 'audio' ? 'audioItems' : 'keyElements';
}

export function fieldForSubTab(subTab: SubTab): 'keyElements' | 'shots' | 'audioItems' {
  return subTab === 'shots' ? 'shots' : subTab === 'audio' ? 'audioItems' : 'keyElements';
}

// ===== 查询工具 =====

export function normalizeDraftType(value: unknown): DraftType | '' {
  const text = String(value || '').trim();
  if (!text || text === 'current') return '';
  if (/^(keyElement|key-element|key_element|element|image)$/i.test(text) || /关键|元素|图片/.test(text)) return 'keyElement';
  if (/^(shot|shots|storyboard|video)$/i.test(text) || /分镜|镜头|视频/.test(text)) return 'shot';
  if (/^(audio|audioItem|audio_item)$/i.test(text) || /音频|旁白|声音/.test(text)) return 'audio';
  return '';
}

export function subTabForType(type: DraftType): SubTab {
  if (type === 'shot') return 'shots';
  if (type === 'audio') return 'audio';
  return 'keyElements';
}

export function groupsForType(type: DraftType | string): AnyGroup[] {
  if (type === 'shot') return state.shots;
  if (type === 'audio') return state.audioItems;
  return state.keyElements;
}

export function findDraftRecord(draftId?: string, type?: DraftType | string): DraftRecord | null {
  // 订阅选中序号：任何 selectDraft/selectAsset 调用（含同值重复点击）都强制派生重算
  void state.selectTick;
  // 显式传入类型时严格限定该类型查找，不跨类型兜底命中同 id 卡；
  // 未传类型（如按 id 反查的轮询/事件路径）保持原有优先级回退。
  const explicit = normalizeDraftType(type);
  const normalized = explicit || state.selectedType || 'keyElement';
  const targetId = (draftId && draftId !== 'current') ? draftId : state.selectedDraftId;
  if (!targetId) return null;
  const types = explicit ? [explicit] : [normalized, 'keyElement', 'shot', 'audio'] as const;
  const seen = new Set<string>();
  for (const t of types) {
    if (!t || seen.has(t)) continue;
    seen.add(t);
    for (const group of groupsForType(t)) {
      const draft = group.drafts?.find((d) => d.id === targetId);
      if (draft) return { type: t as DraftType, group, draft };
    }
  }
  // 未归类素材回退：资产不在故事板分组里，合成只读 DraftRecord，
  // 让点击未归类卡片也能在中间预览区展示媒体（同故事板体验）。
  const asset = state.assets.find((a) => a.id === targetId);
  if (asset) {
    const draft: Draft = {
      id: asset.id,
      label: asset.name,
      tag: '',
      mediaType: asset.type,
      imgUrl: asset.type === 'image' ? asset.url : '',
      videoUrl: asset.type === 'video' ? asset.url : '',
      audioUrl: asset.type === 'audio' ? asset.url : '',
      prompt: '',
    };
    const type: DraftType = asset.type === 'video' ? 'shot' : asset.type === 'audio' ? 'audio' : 'keyElement';
    const group = { id: '__assets__', title: '未归类素材', drafts: [draft] } as unknown as AnyGroup;
    return { type, group, draft };
  }
  return null;
}

export function findGroupRecord(groupId?: string, type?: DraftType | string): GroupRecord | null {
  const normalized = normalizeDraftType(type) || state.selectedType || 'keyElement';
  if (!groupId || groupId === 'current') {
    const current = findDraftRecord(state.selectedDraftId, normalized);
    return current ? { type: current.type, group: current.group } : null;
  }
  const types = [normalized, 'keyElement', 'shot', 'audio'] as const;
  const seen = new Set<string>();
  for (const t of types) {
    if (!t || seen.has(t)) continue;
    seen.add(t);
    const group = groupsForType(t).find((g) => g.id === groupId);
    if (group) return { type: t as DraftType, group };
  }
  return null;
}

export function getCurrentDraft(): Draft | null {
  const rec = findDraftRecord(state.selectedDraftId, state.selectedType);
  return rec?.draft ?? null;
}

/** 选中第一个分组的第一个草稿（初始加载 / 项目切换后调用） */
export function selectFirstDraft() {
  const firstGroup = state.keyElements[0] || state.shots[0] || state.audioItems[0];
  if (firstGroup?.drafts?.length) {
    const type: DraftType = state.keyElements.includes(firstGroup as KeyElementGroup)
      ? 'keyElement'
      : state.shots.includes(firstGroup as ShotGroup) ? 'shot' : 'audio';
    setState('selectedDraftId', firstGroup.drafts[0].id);
    setState('selectedType', type);
    setState('subTab', subTabForType(type));
    setState('selectTick', (v) => v + 1);
  }
}

export { state, setState };
