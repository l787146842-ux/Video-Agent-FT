/** Studio store 组合出口（按域拆分后）。
 * 域实现：./ui.ts（选中态/页签/弹窗/附件/生成态）、
 *         ./storyboard.ts（分组/草稿编辑、服务端同步、持久化）、
 *         ./assets.ts（未归类素材）。
 * 状态本体仍在 ../studio-core（单一 createStore）。
 * 组件仍只需 import '@/stores/studio'（解析到本目录 index.ts），对外 API 形状不变。
 * 说明：原 stores/studio.ts 与 stores/studio/ 目录同名并存造成歧义，已并入本文件消歧。 */
import { setState } from '../studio-core';
import { getSkills } from '@/api/agent';
import { uiActions } from './ui';
import { storyboardActions, persistBoard, categoryForSubTab, getProjectSession } from './storyboard';
import { assetActions } from './assets';

// 对外统一出口：组件只需 import '@/stores/studio'
export {
  state, setState, groupsForType, subTabForType, normalizeDraftType,
  findDraftRecord, findGroupRecord, getCurrentDraft, selectFirstDraft,
} from '../studio-core';
export type { StudioState } from '../studio-core';
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
