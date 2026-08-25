/** studio store 按域拆分后的行为回归 */
import { describe, it, expect, beforeEach } from 'vitest';
import { studioActions, state, setState } from '@/stores/studio';
import type { KeyElementGroup, ShotGroup, AudioGroup } from '@/types';

function seedBoard() {
  setState('keyElements', [{
    id: 'ke1', title: '主角', desc: '',
    drafts: [
      { id: 'd1', label: '草稿1', tag: '', mediaType: 'image', imgUrl: '', prompt: 'p1' },
      { id: 'd2', label: '草稿2', tag: '', mediaType: 'image', imgUrl: '', prompt: 'p2' },
    ],
  } as KeyElementGroup]);
  setState('shots', [{
    id: 's1', title: 'Shot_1', duration: '5s', roughDesc: '',
    drafts: [{ id: 'sd1', label: '分镜1', tag: '', mediaType: 'video', videoUrl: '', prompt: '' }],
  } as ShotGroup]);
  setState('audioItems', [] as AudioGroup[]);
  setState('assets', []);
  setState('selectedDraftId', 'd1');
  setState('selectedType', 'keyElement');
}

describe('studio 域拆分后行为', () => {
  beforeEach(seedBoard);

  it('ui 域：selectDraft 联动 subTab', () => {
    studioActions.selectDraft('sd1', 'shot');
    expect(state.selectedDraftId).toBe('sd1');
    expect(state.subTab).toBe('shots');
  });

  it('storyboard 域：updateDraftLocal 命中分组外的分组保持引用不变（防全量重渲染回归）', () => {
    const before = state.shots;
    studioActions.updateDraftLocal('keyElement', 'd1', { prompt: 'new' });
    expect(state.keyElements[0].drafts[0].prompt).toBe('new');
    expect(state.shots).toBe(before); // 未命中的数组引用不变
  });

  it('storyboard 域：removeDraftLocal 删除后选中态回退', () => {
    studioActions.removeDraftLocal('keyElement', 'ke1', 'd1');
    expect(state.keyElements[0].drafts.map((d) => d.id)).toEqual(['d2']);
    expect(state.selectedDraftId).toBe('d2');
  });

  it('assets 域：moveDraftToAssets 移入未归类素材', () => {
    studioActions.moveDraftToAssets('keyElement', 'ke1', 'd2');
    expect(state.keyElements[0].drafts.map((d) => d.id)).toEqual(['d1']);
    expect(state.assets).toHaveLength(1);
    expect(state.assets[0].name).toBe('草稿2');
  });

  it('assets 域：removeAssetLocal 清理选中态', () => {
    studioActions.moveDraftToAssets('keyElement', 'ke1', 'd2');
    const aid = state.assets[0].id;
    studioActions.selectAsset(aid);
    expect(state.selectedDraftId).toBe(aid);
    studioActions.removeAssetLocal(aid);
    expect(state.assets).toHaveLength(0);
    expect(state.selectedDraftId).toBe('');
  });

  it('ui 域：markSkillUsed 去重追加', () => {
    setState('usedSkills', []);
    studioActions.markSkillUsed('screenwriter');
    studioActions.markSkillUsed('screenwriter');
    expect(state.usedSkills).toEqual(['screenwriter']);
  });
});
