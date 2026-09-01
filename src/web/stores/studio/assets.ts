/** Studio store · 素材域（自 studio.ts 拆出）：未归类素材的选择/删除/移入/还原 */
import type { AnyGroup, Draft, DraftType } from '@/types';
import { showToast } from '@/stores/toast';
import { uid } from '@/lib/utils';
import { state, setState, groupsForType, fieldForType } from '../studio-core';
import { storyboardActions, persistBoard } from './storyboard';

export const assetActions = {
  /** 选中未归类素材：只在中间预览区展示媒体，不切换故事板 subTab。
   * 同步设置 selectedType（按素材媒体类型映射），与故事板选中语义保持一致。 */
  selectAsset(assetId: string) {
    const asset = state.assets.find((a) => a.id === assetId);
    const type: DraftType =
      asset?.type === 'video' ? 'shot' : asset?.type === 'audio' ? 'audio' : 'keyElement';
    setState('selectedDraftId', assetId);
    setState('selectedType', type);
    setState('selectTick', (v) => v + 1);
  },

  /** 删除未归类素材（未归类面板右键菜单） */
  removeAssetLocal(assetId: string) {
    setState('assets', (prev) => prev.filter((a) => a.id !== assetId));
    if (state.selectedDraftId === assetId) setState('selectedDraftId', '');
    persistBoard();
  },

  /** 移除草稿到未归类素材（记录来源分组与草稿快照，供右键还原）。
   *  非破坏移动（可还原）：不级联微调线程（评审修补批：前端线程键保留、
   *  浮窗不关；服务端整板 PUT diff 把素材池来源草稿计入存活集同口径豁免）。 */
  moveDraftToAssets(type: DraftType, groupId: string, draftId: string) {
    const group = groupsForType(type).find((g) => g.id === groupId);
    const draft = group?.drafts?.find((d) => d.id === draftId);
    if (!group || !draft) return;
    storyboardActions.removeDraftLocal(type, groupId, draftId, true);
    setState('assets', (prev) => [
      {
        id: uid('ast'),
        name: draft.label || '未命名素材',
        type: draft.mediaType || 'image',
        isBound: false,
        url: draft.imgUrl || draft.videoUrl || draft.audioUrl || '',
        sourceType: type,
        sourceGroupId: groupId,
        sourceDraft: { ...draft },
      },
      ...prev,
    ]);
    showToast('已移除到未归类素材', 'success');
  },

  /** 右键未归类素材：还原到原来被移除的故事板分组。
   *  返回 false 表示无来源信息或原分组已不存在。 */
  restoreAssetToSource(assetId: string): boolean {
    const asset = state.assets.find((a) => a.id === assetId);
    if (!asset || !asset.sourceType || !asset.sourceGroupId || !asset.sourceDraft) return false;
    const group = groupsForType(asset.sourceType).find((g) => g.id === asset.sourceGroupId);
    if (!group) return false;
    const draft = asset.sourceDraft;
    const field = fieldForType(asset.sourceType);
    setState(field, (prev: AnyGroup[]) => prev.map((g) => {
      if (g.id !== asset.sourceGroupId) return g;
      // 原组内已存在同 id 草稿时不重复还原
      if ((g.drafts || []).some((d) => d.id === draft.id)) return g;
      return { ...g, drafts: [...(g.drafts || []), draft] };
    }));
    setState('assets', (prev) => prev.filter((a) => a.id !== assetId));
    if (state.selectedDraftId === assetId) setState('selectedDraftId', draft.id);
    persistBoard();
    showToast(`已还原到「${group.title}」`, 'success');
    return true;
  },

  /** 右键「还原」无来源快照/原分组已不存在时：按用户选择的目标分组，
   *  以素材信息合成草稿放入。返回是否成功。 */
  restoreAssetToGroup(assetId: string, type: DraftType, groupId: string): boolean {
    const asset = state.assets.find((a) => a.id === assetId);
    const group = groupsForType(type).find((g) => g.id === groupId);
    if (!asset || !group) return false;
    const draft: Draft = {
      id: uid('draft'),
      label: asset.name || '还原素材',
      tag: '还原',
      mediaType: asset.type,
      imgUrl: asset.type === 'image' ? asset.url : '',
      videoUrl: asset.type === 'video' ? asset.url : '',
      audioUrl: asset.type === 'audio' ? asset.url : '',
      prompt: '',
    };
    const field = fieldForType(type);
    setState(field, (prev: AnyGroup[]) => prev.map((g) => (
      g.id === groupId ? { ...g, drafts: [...(g.drafts || []), draft] } : g
    )));
    setState('assets', (prev) => prev.filter((a) => a.id !== assetId));
    if (state.selectedDraftId === assetId) setState('selectedDraftId', draft.id);
    persistBoard();
    showToast(`已还原到「${group.title}」`, 'success');
    return true;
  },
};
