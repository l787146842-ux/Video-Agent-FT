/**
 * 角色音色卡半尺寸图标化（对齐 flova 小图标子卡）防回归断言：
 * ① 关键元素组内的 audio 草稿（角色音色卡）→ .draft-card--voice 半尺寸类 + 音频符号在，
 *    且卡面不渲染名称/描述文字（.draft-card-label / .draft-card-desc 为 null）；
 * ② 音频 tab 的 audio 草稿（BGM/旁白卡）→ 不加 --voice，文字照常渲染（不受影响）；
 * ③ 关键元素组内的 image 草稿 → 不加 --voice，文字照常渲染。
 */
import { render } from '@solidjs/testing-library';
import { describe, it, expect, vi } from 'vitest';

/** 旁路通道打桩：只测渲染面，不触真发送/撤销/菜单 */
vi.mock('@/lib/chat/chat-input-bridge', () => ({
  requestInsertMedia: vi.fn(),
  requestInsertText: vi.fn(),
}));
vi.mock('@/lib/rich-input', () => ({ draftToInlineMedia: vi.fn(() => null) }));
vi.mock('@/stores/history', () => ({ checkpointHistory: vi.fn(), performUndo: vi.fn() }));
vi.mock('@/components/shared/ContextMenu', () => ({ showContextMenu: vi.fn() }));
vi.mock('@/components/shared/ConfirmDialog', () => ({ confirmDialog: vi.fn() }));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { DraftCard } from '../left-panel/DraftCard';
import type { Draft, DraftType } from '@/types';

function setup(draft: Draft, type: DraftType) {
  return render(() => <DraftCard draft={draft} type={type} groupId="g1" cardCode="1-1" />);
}

describe('角色音色卡半尺寸图标化（draft-card--voice）', () => {
  it('keyElement + audio → 半尺寸类 + 音频符号在，卡面无名称/描述文字', () => {
    const voice: Draft = {
      id: 'd-voice', label: 'Audio_程心', mediaType: 'audio',
      desc: '声音特征：女声，中音，音色温润略带沙哑', prompt: 'tts prompt', audioUrl: '',
    };
    const { container } = setup(voice, 'keyElement');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card).toBeTruthy();
    expect(card.classList.contains('draft-card--voice')).toBe(true);
    // 音频符号（音符+波形）仍在
    expect(container.querySelector('.draft-card-audio-indicator')).toBeTruthy();
    // 卡面不渲染任何文字
    expect(container.querySelector('.draft-card-label')).toBeNull();
    expect(container.querySelector('.draft-card-desc')).toBeNull();
    expect(container.querySelector('.draft-card-tag')).toBeNull();
  });

  it('audio tab 的 audio 草稿（BGM/旁白）→ 不加半尺寸类，文字照常渲染', () => {
    const bgm: Draft = {
      id: 'd-bgm', label: 'BGM_末日', mediaType: 'audio',
      desc: '压迫而辽阔的科幻氛围', prompt: 'p', audioUrl: '',
    };
    const { container } = setup(bgm, 'audio');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card.classList.contains('draft-card--voice')).toBe(false);
    expect(container.querySelector('.draft-card-label')).toBeTruthy();
  });

  it('keyElement + image 草稿 → 不加半尺寸类，文字照常渲染', () => {
    const img: Draft = {
      id: 'd-img', label: '程心', mediaType: 'image',
      desc: '约28岁东亚女性', prompt: 'p', imgUrl: '',
    };
    const { container } = setup(img, 'keyElement');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card.classList.contains('draft-card--voice')).toBe(false);
    expect(container.querySelector('.draft-card-label')).toBeTruthy();
  });
});
