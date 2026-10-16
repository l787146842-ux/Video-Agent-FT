/**
 * 卡片手势回预览（2026-10-16 用户裁决）：中间面板为子任务视图时，
 * **只有点击草稿卡 / 素材卡**才切回预览框。
 *
 * 钉死：
 * ① 草稿卡 click / Enter → 回预览 + 选中该卡（子任务视图 → 预览）；
 * ② 素材卡 click / Enter → 回预览 + 选中该素材；
 * ③ 回预览落点单点 = studioActions.returnToPreview（草稿域与素材域共用，
 *    规则不在两处各写一遍）；
 * ④ **selectDraft / selectAsset 本体的非手势调用不回预览**——Agent 建卡
 *    （board-edit 内联 draft）等路径不得抢用户视图（本批不改其语义）。
 */
import { render, fireEvent, cleanup } from '@solidjs/testing-library';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';

import { DraftCard } from '../left-panel/DraftCard';
import { AssetCard } from '../left-panel/AssetCard';
import { state, setState, studioActions } from '@/stores/studio';
import type { Asset, Draft } from '@/types';

const DRAFT: Draft = {
  id: 'd1', label: '主角', tag: '', mediaType: 'image',
  imgUrl: '', prompt: '一个少年',
};

const ASSET: Asset = {
  id: 'a1', name: '素材图', type: 'image', isBound: false, url: '/workspace/assets/a.png',
};

beforeEach(() => {
  setState({
    middleView: 'subagents', selectedDraftId: '', selectedType: 'keyElement',
    keyElements: [], shots: [], audioItems: [], assets: [],
  });
});
afterEach(() => { cleanup(); });

describe('草稿卡手势：点卡回预览并选中', () => {
  it('click → 回预览 + 选中该卡', () => {
    const { container } = render(() => (
      <DraftCard draft={DRAFT} type="keyElement" groupId="g1" />
    ));
    fireEvent.click(container.querySelector('.draft-card')!);
    expect(state.middleView).toBe('preview');
    expect(state.selectedDraftId).toBe('d1');
    expect(state.selectedType).toBe('keyElement');
  });

  it('Enter 键 → 同样回预览 + 选中（键盘可达）', () => {
    const { container } = render(() => (
      <DraftCard draft={DRAFT} type="keyElement" groupId="g1" />
    ));
    fireEvent.keyDown(container.querySelector('.draft-card')!, { key: 'Enter' });
    expect(state.middleView).toBe('preview');
    expect(state.selectedDraftId).toBe('d1');
  });

  it('非 Enter 键不回预览（不误触）', () => {
    const { container } = render(() => (
      <DraftCard draft={DRAFT} type="keyElement" groupId="g1" />
    ));
    fireEvent.keyDown(container.querySelector('.draft-card')!, { key: 'Tab' });
    expect(state.middleView).toBe('subagents');
  });
});

describe('素材卡手势：点卡回预览并选中', () => {
  it('click → 回预览 + 选中该素材', () => {
    setState('assets', [ASSET]);
    setState('showAllAssets', false);
    const { container } = render(() => <AssetCard asset={ASSET} />);
    fireEvent.click(container.querySelector('.draft-card')!);
    expect(state.middleView).toBe('preview');
    expect(state.selectedDraftId).toBe('a1');
    expect(state.selectedType).toBe('keyElement');   // 图片素材映射
  });

  it('Enter 键 → 同样回预览 + 选中', () => {
    const { container } = render(() => <AssetCard asset={ASSET} />);
    fireEvent.keyDown(container.querySelector('.draft-card')!, { key: 'Enter' });
    expect(state.middleView).toBe('preview');
    expect(state.selectedDraftId).toBe('a1');
  });
});

describe('非手势调用不回预览（Agent 动作不得抢用户视图）', () => {
  it('selectDraft 本体（board-edit / Agent 建卡路径）不动 middleView', () => {
    setState('middleView', 'subagents');
    studioActions.selectDraft('d9', 'shot');
    expect(state.middleView).toBe('subagents');   // 视图不被抢
    expect(state.selectedDraftId).toBe('d9');
  });

  it('selectAsset 本体同样不动 middleView', () => {
    setState('middleView', 'subagents');
    studioActions.selectAsset('a9');
    expect(state.middleView).toBe('subagents');
    expect(state.selectedDraftId).toBe('a9');
  });

  it('returnToPreview 是两域共用的同一落点（草稿域与素材域都指向它）', () => {
    setState('middleView', 'subagents');
    studioActions.returnToPreview();
    expect(state.middleView).toBe('preview');
  });
});
