import { describe, it, expect, beforeEach } from 'vitest';
import {
  state, setState, studioActions,
  normalizeDraftType, findDraftRecord, groupsForType, subTabForType,
} from '@/stores/studio';
import type { KeyElementGroup, ShotGroup, AudioGroup } from '@/types';

function makeKeyGroup(id: string, draftIds: string[]): KeyElementGroup {
  return {
    id,
    title: `元素${id}`,
    desc: '',
    drafts: draftIds.map((d) => ({ id: d, label: d, mediaType: 'image' as const })),
  };
}

function resetState() {
  setState({
    keyElements: [makeKeyGroup('ke1', ['d1', 'd2']), makeKeyGroup('ke2', ['d3'])],
    shots: [{
      id: 'sh1', title: '分镜1', duration: '5s', sceneRefs: [],
      drafts: [{ id: 'v1', label: 'v1', mediaType: 'video' }],
    }] as ShotGroup[],
    audioItems: [{
      id: 'au1', title: '音频1', timeRange: '0-5s',
      drafts: [{ id: 'a1', label: 'a1', mediaType: 'audio' }],
    }] as AudioGroup[],
    assets: [],
    selectedDraftId: '',
    selectedType: 'keyElement',
    subTab: 'keyElements',
  });
}

describe('studio-core 查询', () => {
  beforeEach(resetState);

  it('normalizeDraftType 兼容多种别名', () => {
    expect(normalizeDraftType('keyElement')).toBe('keyElement');
    expect(normalizeDraftType('元素')).toBe('keyElement');
    expect(normalizeDraftType('SHOT')).toBe('shot');
    expect(normalizeDraftType('音频')).toBe('audio');
    expect(normalizeDraftType('current')).toBe('');
    expect(normalizeDraftType('未知')).toBe('');
  });

  it('findDraftRecord 跨类型查找草稿', () => {
    expect(findDraftRecord('d3')?.type).toBe('keyElement');
    expect(findDraftRecord('v1')?.type).toBe('shot');
    expect(findDraftRecord('a1')?.type).toBe('audio');
    expect(findDraftRecord('不存在')).toBeNull();
  });

  it('groupsForType / subTabForType 映射', () => {
    expect(groupsForType('shot')).toHaveLength(1);
    expect(subTabForType('audio')).toBe('audio');
    expect(subTabForType('keyElement')).toBe('keyElements');
  });
});

describe('studioActions', () => {
  beforeEach(resetState);

  it('selectDraft 联动 subTab', () => {
    studioActions.selectDraft('v1', 'shot');
    expect(state.selectedDraftId).toBe('v1');
    expect(state.subTab).toBe('shots');
  });

  it('updateDraftLocal 局部更新草稿字段', () => {
    studioActions.updateDraftLocal('keyElement', 'd1', { prompt: '新提示词' });
    const rec = findDraftRecord('d1');
    expect(rec?.draft.prompt).toBe('新提示词');
    // 其他草稿不受影响
    expect(findDraftRecord('d2')?.draft.prompt).toBeUndefined();
  });

  it('addDraftLocal 新建草稿并选中', () => {
    studioActions.addDraftLocal('keyElement', 'ke1');
    const g = state.keyElements.find((x) => x.id === 'ke1');
    expect(g?.drafts).toHaveLength(3);
    expect(state.selectedDraftId).toBe(g!.drafts[2].id);
  });

  it('removeDraftLocal 删除后自动选中剩余草稿', () => {
    studioActions.selectDraft('d1', 'keyElement');
    studioActions.removeDraftLocal('keyElement', 'ke1', 'd1');
    const g = state.keyElements.find((x) => x.id === 'ke1');
    expect(g?.drafts).toHaveLength(1);
    expect(state.selectedDraftId).toBe('d2');
  });

  it('reorderGroupsLocal 拖拽重排', () => {
    studioActions.reorderGroupsLocal('keyElements', 'ke2', 'ke1');
    expect(state.keyElements.map((g) => g.id)).toEqual(['ke2', 'ke1']);
  });

  it('jumpToElementByTitle 跳转并选中首个草稿', () => {
    studioActions.jumpToElementByTitle('元素ke2');
    expect(state.subTab).toBe('keyElements');
    expect(state.selectedDraftId).toBe('d3');
  });

  it('syncFromServer 快照同步', () => {
    studioActions.syncFromServer({
      keyElements: [makeKeyGroup('keNew', ['dn1'])],
      shots: [],
      audioItems: [],
      assets: [],
      chatMessages: [],
      project_name: '新项目',
    } as never);
    expect(state.projectName).toBe('新项目');
    expect(state.keyElements[0].id).toBe('keNew');
  });
});
