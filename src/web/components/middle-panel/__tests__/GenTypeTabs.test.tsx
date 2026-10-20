/**
 * middle-panel GenTypeTabs 关键交互最小用例（任务 #30 口径纳入）。
 * 钉死：切换只改 genType 不清媒体、激活态回退（genType → mediaType → image）、
 * 收缩/展开、无选中草稿时不写状态；分镜卡只给图片/视频两种生成类型
 * （2026-10-20 用户裁决：分镜面板的卡可出图与出视频）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { GenTypeTabs } from '../GenTypeTabs';
import { setState, studioActions } from '@/stores/studio';

function selectDraft(draftId: string) {
  setState('keyElements', [{
    id: 'g1', title: '组', desc: '',
    drafts: [{ id: 'd1', label: '卡', mediaType: 'image', prompt: 'p' }],
  }] as never);
  setState('selectedType', 'keyElement');
  setState('selectedDraftId', draftId);
}

function selectShotDraft(draftId: string) {
  setState('shots', [{
    id: 'g2', title: 'Shot_1', desc: '',
    drafts: [{ id: 'v1', label: '分镜卡', mediaType: 'video', prompt: 'p' }],
  }] as never);
  setState('selectedType', 'shot');
  setState('selectedDraftId', draftId);
}

beforeEach(() => {
  setState('keyElements', []);
  setState('shots', []);
  setState('selectedDraftId', '');
  setState('selectedType', 'keyElement');
});

describe('GenTypeTabs', () => {
  it('渲染三个生成类型标签；未选草稿时切换不写状态', () => {
    const spy = vi.spyOn(studioActions, 'updateDraftLocal');
    const { container } = render(() => <GenTypeTabs />);
    const tabs = container.querySelectorAll('.gen-type-tab');
    expect(tabs.length).toBe(3);
    fireEvent.click(tabs[1]); // 视频
    expect(spy).not.toHaveBeenCalled(); // 无选中草稿的守卫
    spy.mockRestore();
  });

  it('选中草稿后切换：只写 genType（不清已有媒体）', () => {
    selectDraft('d1');
    const spy = vi.spyOn(studioActions, 'updateDraftLocal');
    const { container } = render(() => <GenTypeTabs />);
    const tabs = container.querySelectorAll('.gen-type-tab');
    // 激活态回退链：无 genType → mediaType（image）为激活
    expect(tabs[0].className).toContain('active');
    fireEvent.click(tabs[2]); // 音频
    expect(spy).toHaveBeenCalledWith('keyElement', 'd1', { genType: 'audio' });
    spy.mockRestore();
  });

  it('点击已激活类型不重复写状态', () => {
    selectDraft('d1');
    const spy = vi.spyOn(studioActions, 'updateDraftLocal');
    const { container } = render(() => <GenTypeTabs />);
    fireEvent.click(container.querySelectorAll('.gen-type-tab')[0]);
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it('收缩/展开：收起后标签行隐藏，展开恢复', () => {
    selectDraft('d1');
    const { container } = render(() => <GenTypeTabs />);
    const toggle = container.querySelector('.gen-type-toggle') as HTMLButtonElement;
    expect(container.querySelector('.gen-type-tabs')).not.toBeNull();
    fireEvent.click(toggle);
    expect(container.querySelector('.gen-type-tabs')).toBeNull();
    fireEvent.click(toggle);
    expect(container.querySelector('.gen-type-tabs')).not.toBeNull();
  });

  it('分镜卡只渲染图片/视频两个标签，切换写回 shot 域', () => {
    selectShotDraft('v1');
    const spy = vi.spyOn(studioActions, 'updateDraftLocal');
    const { container } = render(() => <GenTypeTabs />);
    const tabs = container.querySelectorAll('.gen-type-tab');
    expect(tabs.length).toBe(2);
    expect(tabs[0].textContent).toContain('图片生成');
    expect(tabs[1].textContent).toContain('视频生成');
    // 激活态回退链：无 genType → mediaType（video）为激活
    expect(tabs[1].className).toContain('active');
    fireEvent.click(tabs[0]);
    expect(spy).toHaveBeenCalledWith('shot', 'v1', { genType: 'image' });
    spy.mockRestore();
  });
});
