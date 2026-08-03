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
  agentBusy: boolean;
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
  /** 当前项目已发送给 Agent 的 Skill slug（文档面板只展示这些 Skill 文档） */
  usedSkills: string[];
  /** Agent 联动更新故事板的时间戳（驱动左面板闪烁动画） */
  lastAppliedAt: number;
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
  agentBusy: false,
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
  usedSkills: [],
  lastAppliedAt: 0,
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
  const normalized = normalizeDraftType(type) || state.selectedType || 'keyElement';
  const targetId = (draftId && draftId !== 'current') ? draftId : state.selectedDraftId;
  if (!targetId) return null;
  const types = [normalized, 'keyElement', 'shot', 'audio'] as const;
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
  }
}

export { state, setState };
