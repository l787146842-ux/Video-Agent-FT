/**
 * 绑定批 + 卡内读秒（2026-10-26 用户裁决）：
 * ① 绑定卡 → 右上角绿勾（细黑边框）；
 * ② 右键菜单：有媒体的卡出现「绑定为分组媒体 / 取消绑定」；
 * ③ 生成中且无媒体 → 卡内紧凑读秒环（与中间预览框同源）；已有媒体则让位；
 * ④ 图文组内绑定音频 → 缩为小卡（图5 形态）；纯音频组保持原尺寸。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, afterEach } from 'vitest';

const showContextMenu = vi.fn();
vi.mock('@/components/shared/ContextMenu', () => ({
  showContextMenu: (...args: unknown[]) => showContextMenu(...args),
}));
vi.mock('@/lib/chat/chat-input-bridge', () => ({
  requestInsertMedia: vi.fn(),
  requestInsertText: vi.fn(),
}));
vi.mock('@/lib/rich-input', () => ({ draftToInlineMedia: vi.fn(() => null) }));
vi.mock('@/stores/history', () => ({ checkpointHistory: vi.fn(), performUndo: vi.fn() }));
vi.mock('@/components/shared/ConfirmDialog', () => ({ confirmDialog: vi.fn() }));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { studioActions } from '@/stores/studio';
import { DraftCard } from '../left-panel/DraftCard';
import type { Draft, DraftType } from '@/types';

function setup(draft: Draft, type: DraftType, groupHasVisual?: boolean) {
  return render(() => (
    <DraftCard draft={draft} type={type} groupId="g1" cardCode="1-1" groupHasVisual={groupHasVisual} />
  ));
}

afterEach(() => {
  vi.clearAllMocks();
  studioActions.finishGeneration('d-ring');
  studioActions.finishGeneration('d-ring2');
});

describe('绑定绿勾（右上角，细黑边框）', () => {
  it('已绑定卡 → 渲染绿勾；未绑定卡 → 无勾', () => {
    const bound = setup({
      id: 'b1', label: '设定图', mediaType: 'image', imgUrl: '/a.png', bound: true,
    }, 'keyElement');
    expect(bound.container.querySelector('.draft-card-bound-badge')).toBeTruthy();

    const plain = setup({
      id: 'b2', label: '设定图', mediaType: 'image', imgUrl: '/a.png',
    }, 'keyElement');
    expect(plain.container.querySelector('.draft-card-bound-badge')).toBeNull();
  });
});

describe('右键菜单：绑定 / 取消绑定', () => {
  it('有媒体的未绑定卡 → 首项「绑定为分组媒体」', () => {
    const { container } = setup({
      id: 'm1', label: '分镜视频', mediaType: 'video', videoUrl: '/v.mp4',
    }, 'shot');
    fireEvent.contextMenu(container.querySelector('.draft-card') as HTMLElement);
    const items = showContextMenu.mock.calls[0][1] as Array<{ label: string }>;
    expect(items[0].label).toBe('绑定为分组媒体');
    expect(items.map((i) => i.label)).toContain('添加到对话');
  });

  it('已绑定卡 → 首项「取消绑定」', () => {
    const { container } = setup({
      id: 'm2', label: '设定图', mediaType: 'image', imgUrl: '/a.png', bound: true,
    }, 'keyElement');
    fireEvent.contextMenu(container.querySelector('.draft-card') as HTMLElement);
    const items = showContextMenu.mock.calls[0][1] as Array<{ label: string }>;
    expect(items[0].label).toBe('取消绑定');
  });

  it('空卡（无任何媒体）→ 不出现绑定项', () => {
    const { container } = setup({
      id: 'm3', label: '空卡', mediaType: 'image', imgUrl: '',
    }, 'keyElement');
    fireEvent.contextMenu(container.querySelector('.draft-card') as HTMLElement);
    const items = showContextMenu.mock.calls[0][1] as Array<{ label: string }>;
    expect(items.map((i) => i.label)).not.toContain('绑定为分组媒体');
    expect(items[0].label).toBe('添加到对话');
  });
});

describe('卡内读秒环（与中间预览框同源）', () => {
  it('生成中且无媒体 → 紧凑读秒环在场', () => {
    studioActions.startGeneration('d-ring', 'image');
    const { container } = setup({
      id: 'd-ring', label: '设定图', mediaType: 'image', imgUrl: '',
    }, 'keyElement');
    expect(container.querySelector('.gen-progress--compact')).toBeTruthy();
    expect(container.querySelector('.gen-progress-time')?.textContent).toMatch(/s$/);
  });

  it('生成中但已有媒体 → 读秒环让位（与中间预览框同规则）', () => {
    studioActions.startGeneration('d-ring2', 'image');
    const { container } = setup({
      id: 'd-ring2', label: '设定图', mediaType: 'image', imgUrl: '/a.png',
    }, 'keyElement');
    expect(container.querySelector('.gen-progress--compact')).toBeNull();
  });
});

describe('绑定音频小卡（仅图文组内，图5 形态）', () => {
  it('分镜组（含视觉卡）内绑定音频 → 小卡形态', () => {
    const { container } = setup({
      id: 'a1', label: '分镜音频', mediaType: 'audio', audioUrl: '/a.mp3', bound: true,
    }, 'shot', true);
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card.classList.contains('draft-card--voice')).toBe(true);
  });

  it('纯音频组（无视觉卡）内绑定音频 → 保持原尺寸', () => {
    const { container } = setup({
      id: 'a2', label: 'BGM', mediaType: 'audio', audioUrl: '/a.mp3', bound: true,
    }, 'audio', false);
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card.classList.contains('draft-card--voice')).toBe(false);
  });
});
