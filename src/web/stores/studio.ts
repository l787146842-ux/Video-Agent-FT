/** Studio store 组合出口（按域拆分后）。
 * 域实现：studio/ui.ts（选中态/页签/弹窗/附件/生成态）、
 *         studio/storyboard.ts（分组/草稿编辑、服务端同步、持久化）、
 *         studio/assets.ts（未归类素材）。
 * 组件仍只需 import '@/stores/studio'，对外 API 形状不变。 */
import { setState } from './studio-core';
import { getSkills } from '@/api/agent';
import { uiActions } from './studio/ui';
import { storyboardActions, persistBoard, categoryForSubTab, getProjectSession } from './studio/storyboard';
import { assetActions } from './studio/assets';

// 对外统一出口：组件只需 import '@/stores/studio'
export {
  state, setState, groupsForType, subTabForType, normalizeDraftType,
  findDraftRecord, findGroupRecord, getCurrentDraft, selectFirstDraft,
} from './studio-core';
export type { StudioState } from './studio-core';
export { persistBoard, categoryForSubTab, getProjectSession };

// ===== Actions（三域组合，键名与拆分前逐一对应） =====
export const studioActions = {
  ...uiActions,
  ...storyboardActions,
  ...assetActions,
};

/** 重新加载 Skill 列表（导入新 Skill 后调用） */
export async function refreshSkills(): Promise<void> {
  try {
    const skills = await getSkills();
    setState('skills', skills);
  } catch { /* 静默失败 */ }
}
