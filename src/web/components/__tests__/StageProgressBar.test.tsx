/**
 * 长任务阶段进度条测试：
 * ① 无任何进度信息（无轮次事件且故事板全空）时整体不渲染；
 * ② 轮次段由 status 事件结构化参数驱动（step/max 文案 + 百分比宽度）；
 * ③ 故事板区只展示有草稿的板块，done/total 为客观媒体落位口径。
 */
import { render } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockState = vi.hoisted(() => ({
  keyElements: [] as unknown[], shots: [] as unknown[], audioItems: [] as unknown[],
}));
vi.mock('@/stores/studio', () => ({ state: mockState }));

import { StageProgressBar } from '../right-panel/StageProgressBar';
import { setChatState } from '@/stores/chat';

function setRound(step: number, max: number) {
  setChatState('roundStep', step);
  setChatState('roundMax', max);
}

/** 草稿组 fixture（只给进度派生关心的字段） */
function group(drafts: Array<{ media?: boolean }>) {
  return {
    id: 'g', title: '组',
    drafts: drafts.map((d, i) => ({
      id: `d${i}`, label: `d${i}`, mediaType: 'image',
      ...(d.media ? { imgUrl: `/i${i}.png` } : {}),
    })),
  };
}

describe('StageProgressBar 阶段进度条', () => {
  beforeEach(() => {
    setRound(0, 0);
    mockState.keyElements = [];
    mockState.shots = [];
    mockState.audioItems = [];
  });

  it('无轮次事件且故事板全空 → 整体不渲染', () => {
    const { container } = render(() => <StageProgressBar />);
    expect(container.querySelector('.stage-progress')).toBeNull();
  });

  it('收到轮次进度 → 渲染轮次段（step/max 文案 + 百分比宽度）', () => {
    setRound(2, 4);
    const { container } = render(() => <StageProgressBar />);
    const bar = container.querySelector('.stage-progress');
    expect(bar).toBeTruthy();
    expect(bar?.getAttribute('role')).toBe('status');
    const label = container.querySelector('.stage-progress-round-label');
    expect(label?.textContent).toContain('2');
    expect(label?.textContent).toContain('4');
    const fill = container.querySelector('.stage-progress-fill') as HTMLElement;
    expect(fill.style.width).toBe('50%');
  });

  it('故事板区：仅有草稿的板块展示，计数为媒体落位口径', () => {
    mockState.keyElements = [group([{ media: true }, { media: true }, {}])];
    mockState.shots = [group([{}])];
    // audioItems 为空 → 不渲染音频板块 chip
    const { container } = render(() => <StageProgressBar />);
    const chips = container.querySelectorAll('.stage-progress-board');
    expect(chips.length).toBe(2);
    expect(chips[0].textContent).toContain('2/3');
    expect(chips[0].classList.contains('done')).toBe(false);
    expect(chips[1].textContent).toContain('0/1');
  });

  it('板块全部落位 → done 标记；无轮次事件时轮次段不渲染', () => {
    mockState.shots = [group([{ media: true }])];
    const { container } = render(() => <StageProgressBar />);
    expect(container.querySelector('.stage-progress-round')).toBeNull();
    const chip = container.querySelector('.stage-progress-board');
    expect(chip?.classList.contains('done')).toBe(true);
    expect(chip?.textContent).toContain('1/1');
  });
});
