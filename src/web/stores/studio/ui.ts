/** Studio store · UI 域（从 studio.ts 拆出）：选中态/页签/弹窗/附件/生成态/配置 */
import { produce } from 'solid-js/store';
import type {
  DraftType, LeftTab, MiddleView, SubTab, ApiProvider, Skill, PendingAttachment,
} from '@/types';
import { showToast } from '@/stores/toast';
import { state, setState, findDraftRecord, subTabForType } from '../studio-core';

export const uiActions = {
  selectDraft(id: string, type: DraftType) {
    setState('selectedDraftId', id);
    setState('selectedType', type);
    setState('subTab', subTabForType(type));
    // 强制通知：同 id 同 type 重复点击也让所有预览派生重算（store 同值零通知的兜底）
    setState('selectTick', (v) => v + 1);
  },

  setLeftTab(tab: LeftTab) {
    setState('leftTab', tab);
  },

  /** 中间面板视图切换：顶栏「子任务」→ subagents；点左栏任意处 → preview */
  setMiddleView(view: MiddleView) {
    setState('middleView', view);
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
    setState('locateGroupId', ''); // 按选中草稿定位，清除分组定位目标
    setState('locateTick', (v) => v + 1);
  },

  togglePromptCollapse() {
    setState('isPromptCollapsed', (v) => !v);
  },

  /* setAgentBusy 已迁 chat/agent 域（任务 #11）：见 stores/agent-state.ts */

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

  addPendingAttachment(att: PendingAttachment) {
    setState('pendingAttachments', (prev) => [...prev, att]);
  },

  removePendingAttachment(id: string) {
    setState('pendingAttachments', (prev) => prev.filter((a) => a.id !== id));
  },

  startGeneration(draftId: string, kind: 'image' | 'video', fromEpoch?: number) {
    // fromEpoch：刷新页面后从后端 processing 任务恢复读秒时，
    // 用任务创建时间回填，避免已耗时被重置为 0
    setState('activeGenerations', draftId, { start: fromEpoch || Date.now(), kind });
  },

  finishGeneration(draftId: string): number | null {
    const rec = state.activeGenerations[draftId];
    // Solid store 对象赋值是合并语义：返回删掉 key 的新对象不会移除旧 key，
    // 会导致读秒条目残留（生成报错后进度环永远转圈）。必须用 produce 真删。
    setState('activeGenerations', produce((next) => {
      delete next[draftId];
    }));
    return rec ? (Date.now() - rec.start) / 1000 : null;
  },

  /** 乐观登记已发送的 Skill slug（后端随快照回传权威值，此处先更新保证文档面板即时展示） */
  markSkillUsed(slug: string) {
    if (!slug || (state.usedSkills || []).includes(slug)) return;
    setState('usedSkills', (prev) => [...(prev || []), slug]);
  },

  setApiConfig(config: {
    providers?: ApiProvider[];
    skills?: Skill[];
    chatModels?: string[];
    imageModels?: string[];
    videoModels?: string[];
    canvasUrl?: string;
  }) {
    setState('apiProviders', config.providers ?? state.apiProviders);
    setState('skills', config.skills ?? state.skills);
    setState('availableChatModels', config.chatModels ?? state.availableChatModels);
    setState('availableImageModels', config.imageModels ?? state.availableImageModels);
    setState('availableVideoModels', config.videoModels ?? state.availableVideoModels);
    setState('canvasUrl', config.canvasUrl ?? state.canvasUrl);
  },

  /** Agent 联动更新故事板后调用，驱动左面板闪烁提示 */
  markBoardApplied() {
    setState('lastAppliedAt', Date.now());
  },

  /** 按标题或分组 id 跳转到关键元素（分镜 sceneRefs chip 点击；
   * sceneRefs 存的是 ke-xxx id，需同时支持 id 命中，888 ：只匹配标题报「未找到」）。
   * 跳转效果与预览框「定位」一致：滚动到目标分组卡并闪烁，没有草稿卡也能看到。 */
  jumpToElementByTitle(title: string) {
    const el = state.keyElements.find((k) => k.title === title || k.id === title);
    if (!el) {
      showToast(`未找到关键元素「${title}」`, 'warning');
      return;
    }
    setState('leftTab', 'storyboard');
    setState('subTab', 'keyElements');
    setState('locateGroupId', el.id);
    if (el.drafts?.length) {
      setState('selectedDraftId', el.drafts[0].id);
      setState('selectedType', 'keyElement');
      setState('selectTick', (v) => v + 1);
    }
    setState('locateTick', (v) => v + 1);
  },
};
