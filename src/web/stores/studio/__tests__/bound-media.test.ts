/** 绑定态 store 动作（2026-10-26 用户裁决）：同组同类型唯一，异类型互不影响。 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/api/project', () => ({
  putProjectState: vi.fn(async () => ({ board_version: 1 })),
  getProjectState: vi.fn(async () => ({})),
  mergeProjectState: vi.fn(async () => ({})),
  flushProjectStateKeepalive: vi.fn(),
}));

import { state, setState, studioActions } from '@/stores/studio';

function seed() {
  setState('keyElements', [{
    id: 'g1', title: 'Element_A',
    drafts: [
      { id: 'd1', label: '图1', mediaType: 'image', imgUrl: '/1.png', bound: true },
      { id: 'd2', label: '图2', mediaType: 'image', imgUrl: '/2.png' },
      { id: 'd3', label: '音色', mediaType: 'audio', audioUrl: '/v.mp3', bound: true },
    ],
  }]);
}

beforeEach(seed);

describe('bindDraftLocal（同组同类型唯一）', () => {
  it('绑定新图 → 同组同类型旧绑定自动解除，音频绑定不受影响', () => {
    studioActions.bindDraftLocal('keyElement', 'g1', 'd2', true);
    const drafts = state.keyElements[0].drafts;
    expect(drafts.find((d) => d.id === 'd2')?.bound).toBe(true);
    expect(drafts.find((d) => d.id === 'd1')?.bound).toBe(false);
    expect(drafts.find((d) => d.id === 'd3')?.bound).toBe(true);
  });

  it('取消绑定 → 只影响目标卡', () => {
    studioActions.bindDraftLocal('keyElement', 'g1', 'd1', false);
    const drafts = state.keyElements[0].drafts;
    expect(drafts.find((d) => d.id === 'd1')?.bound).toBe(false);
    expect(drafts.find((d) => d.id === 'd3')?.bound).toBe(true);
  });
});
