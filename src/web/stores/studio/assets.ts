/** Studio store · 素材域（批次6 从 studio.ts 拆出）：未归类素材的选择/删除/移入 */
import type { DraftType } from '@/types';
import { showToast } from '@/stores/toast';
import { uid } from '@/lib/utils';
import { state, setState, groupsForType } from '../studio-core';
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

  /** 移除草稿到未归类素材 */
  moveDraftToAssets(type: DraftType, groupId: string, draftId: string) {
    const group = groupsForType(type).find((g) => g.id === groupId);
    const draft = group?.drafts?.find((d) => d.id === draftId);
    if (!group || !draft) return;
    storyboardActions.removeDraftLocal(type, groupId, draftId);
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
};
