/**
 * 长任务阶段进度条测试：
 * ① 故事板全空时整体不渲染；
 * ② 故事板区只展示有草稿的板块，done/total 为客观媒体落位口径；
 * （推理轮次段已随阶段规则去代码化批退役，2026-09-10——不设步数上限后
 *   「第 N/M 轮」无分母，该段与 roundStep/roundMax 状态一并删除。）
 */
import { render } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockState = vi.hoisted(() => ({
  keyElements: [] as unknown[], shots: [] as unknown[], audioItems: [] as unknown[],
}));
vi.mock('@/stores/studio', () => ({ state: mockState }));

import { StageProgressBar } from '../right-panel/StageProgressBar';

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
    mockState.keyElements = [];
    mockState.shots = [];
    mockState.audioItems = [];
  });

  it('故事板全空 → 整体不渲染', () => {
    const { container } = render(() => <StageProgressBar />);
    expect(container.querySelector('.stage-progress')).toBeNull();
  });

  it('故事板区：仅有草稿的板块展示，计数为媒体落位口径', () => {
    mockState.keyElements = [group([{ media: true }, { media: true }, {}])];
    mockState.shots = [group([{}])];
    // audioItems 为空 → 不渲染音频板块 chip
    const { container } = render(() => <StageProgressBar />);
    const bar = container.querySelector('.stage-progress');
    expect(bar?.getAttribute('role')).toBe('status');
    const chips = container.querySelectorAll('.stage-progress-board');
    expect(chips.length).toBe(2);
    expect(chips[0].textContent).toContain('2/3');
    expect(chips[0].classList.contains('done')).toBe(false);
    expect(chips[1].textContent).toContain('0/1');
  });

  it('板块全部落位 → done 标记；不再渲染轮次段', () => {
    mockState.shots = [group([{ media: true }])];
    const { container } = render(() => <StageProgressBar />);
    expect(container.querySelector('.stage-progress-round')).toBeNull();
    const chip = container.querySelector('.stage-progress-board');
    expect(chip?.classList.contains('done')).toBe(true);
    expect(chip?.textContent).toContain('1/1');
  });
});
