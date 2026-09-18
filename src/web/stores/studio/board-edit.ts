/** Studio store · 故事板本地编辑域（Q14 裁决 2026-09-01 方案 A：自 storyboard.ts 三分）。
 * 分组/草稿的本地编辑 actions（编辑后调持久化域 persistBoard 防抖落盘）。
 * 状态树不动；原签名经 storyboard.ts 重导出，调用方零改动。 */
import type { DraftType, Draft, SubTab, AnyGroup } from '@/types';
import { CAT_SHOTS } from '@/lib/state-keys';
import { canonicalGroupTitle } from '@/lib/desc-ref-utils';
import { showToast } from '@/stores/toast';
import { uid } from '@/lib/utils';
import {
  state, setState,
  fieldForType, fieldForSubTab, groupsForType, selectFirstDraft,
} from '../studio-core';
import { uiActions } from './ui';
import { persistBoard } from './board-persist';
import { addLocalAddedId, removeLocalAddedId } from './board-sync';
import { adjustScopeActions } from '../adjust-scopes';

/** subTab → 草稿类型 */
export function draftTypeForSubTab(subTab: SubTab): DraftType {
  return subTab === 'shots' ? 'shot' : subTab === 'audio' ? 'audio' : 'keyElement';
}

/** 当前 subTab 对应的后端 category 名 */
export function categoryForSubTab(subTab: SubTab): string {
  return fieldForSubTab(subTab);
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

/** 本地编辑动作（薄聚合层与同步域合并为原 storyboardActions 导出） */
export const boardEditActions = {
  /** 手动新建分组（底部 + 按钮，追加到末尾） */
  addGroupLocal(subTab: SubTab) {
    const field = fieldForSubTab(subTab);
    const ordinal = (state[field] as AnyGroup[]).length + 1;
    const { group, draftId } = buildDefaultGroup(subTab, ordinal);
    addLocalAddedId(group.id); addLocalAddedId(draftId); // D2：未落盘前不被快照冲掉
    setState(field, (prev: AnyGroup[]) => [...prev, group]);
    uiActions.selectDraft(draftId, draftTypeForSubTab(subTab));
    persistBoard();
  },

  /** 在指定位置插入新分组（列表右键菜单：向上/向下插入）。
   * index 为插入后的目标下标（0-based，越界自动夹取） */
  insertGroupLocal(subTab: SubTab, index: number) {
    const field = fieldForSubTab(subTab);
    const list = state[field] as AnyGroup[];
    const clamped = Math.max(0, Math.min(index, list.length));
    const { group, draftId } = buildDefaultGroup(subTab, clamped + 1);
    addLocalAddedId(group.id); addLocalAddedId(draftId); // D2：未落盘前不被快照冲掉
    setState(field, (prev: AnyGroup[]) => {
      const next = [...prev];
      next.splice(clamped, 0, group);
      return next;
    });
    uiActions.selectDraft(draftId, draftTypeForSubTab(subTab));
    persistBoard();
  },

  /** 删除分组（列表右键菜单，删除前由调用方做确认弹窗） */
  removeGroupLocal(subTab: SubTab, groupId: string) {
    const field = fieldForSubTab(subTab);
    const target = (state[field] as AnyGroup[]).find((g) => g.id === groupId);
    if (!target) return;
    // ：删除的实体移出本地新增保护集，避免后续快照合并时被复活
    removeLocalAddedId(groupId);
    for (const d of target.drafts || []) removeLocalAddedId(d.id);
    // 对象删除级联（二期子对话批 1）：微调线程注册表对应键移除，
    // 浮窗若正开着该线程随之关闭（后端线程随整板 PUT 同帧硬删）
    for (const d of target.drafts || []) adjustScopeActions.dropThread(d.id);
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
        if (patch.title !== undefined) {
          // 容器 ID 约定写口归一（2026-09-17 裁决）：裸名补类型前缀落盘，
          // 与后端建组 normalize_group_title 同契约（显示层只显裸名）
          updated.title = canonicalGroupTitle(patch.title, type);
        }
        if (patch.desc !== undefined) {
          // shot 分镜正文唯一载体 = desc（roughDesc 双通道写口 2026-09-15 退役，
          // 与后端建组入参/patch 白名单一致，ShotDescEditor 编辑的正是 desc）；
          // keyElement 元素设定同写 desc；audio 走 prompt
          if (type === 'audio') updated.prompt = patch.desc;
          else updated.desc = patch.desc;
        }
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
    addLocalAddedId(newId); // D2：未落盘前不被快照冲掉
    const draft: Draft =
      type === 'keyElement'
        ? { id: newId, label: '自定义草稿', tag: '手动', mediaType: 'image', imgUrl: '', prompt: '', model: '', aspectRatio: '16:9' }
        : type === 'shot'
          ? { id: newId, label: '自定义分镜', tag: '手动', mediaType: 'video', videoUrl: '', prompt: '', mode: '图生视频', model: '' }
          : { id: newId, label: '自定义音频', tag: '手动', mediaType: 'audio', audioUrl: '', prompt: '' };
    setState(field, (prev: AnyGroup[]) =>
      prev.map((g) => (g.id === groupId ? { ...g, drafts: [...(g.drafts || []), draft] } : g)),
    );
    uiActions.selectDraft(newId, type);
    persistBoard();
  },

  /** 删除草稿（右键菜单）；keepThread：非破坏移动（移入素材池，可还原）
   *  不级联线程注册表（评审修补批：前端线程键保留、浮窗不关） */
  removeDraftLocal(type: DraftType, groupId: string, draftId: string, keepThread = false) {
    const field = fieldForType(type);
    const group = groupsForType(type).find((g) => g.id === groupId);
    if (!group) return;
    const remaining = (group?.drafts || []).filter((d) => d.id !== draftId);
    removeLocalAddedId(draftId); // D2：删除的草稿移出保护集，防快照合并复活
    // 对象删除级联：微调线程注册表键移除（可还原移动除外；服务端 diff 同口径豁免）
    if (!keepThread) adjustScopeActions.dropThread(draftId);
    setState(field, (prev: AnyGroup[]) =>
      prev.map((g) => (g.id === groupId ? { ...g, drafts: remaining } : g)),
    );
    if (state.selectedDraftId === draftId) {
      setState('selectedDraftId', remaining[0]?.id || '');
    }
    persistBoard();
  },

  /** 分镜场景引用增删（C4）：本地更新后走防抖整板保存（与其他本地编辑同路径）。
   * 删除某元素后：出视频不再自动挂该元素概念图，卡片场景 chips 同步消失 */
  setSceneRefsLocal(groupId: string, refs: string[]) {
    setState(CAT_SHOTS, (prev: AnyGroup[]) =>
      prev.map((g) => (g.id === groupId ? { ...g, sceneRefs: refs } : g)),
    );
    persistBoard();
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
    // 无实际变化直接返回：不替换数组、不触发 persistBoard，
    // 避免整组级联重算与无效 PUT（点击卡片时的校正 effect 是主要调用源）
    const target = (state[field] as AnyGroup[]).flatMap((g) => g.drafts || []).find((d) => d.id === draftId);
    if (!target) return;
    const changed = (Object.keys(patch) as Array<keyof Draft>).some((k) => target[k] !== patch[k]);
    if (!changed) return;
    setState(field, (prev: AnyGroup[]) => prev.map((g) => {
      if (!(g.drafts || []).some((d) => d.id === draftId)) return g;
      return { ...g, drafts: g.drafts!.map((d) => (d.id === draftId ? { ...d, ...patch } : d)) };
    }));
    persistBoard();
  },
};
