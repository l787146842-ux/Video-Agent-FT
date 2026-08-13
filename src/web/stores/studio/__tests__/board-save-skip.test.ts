import { describe, it, expect, vi, beforeEach } from 'vitest';

/** 业界基准 C4（读不触发写）：内容未变的"保存"不得发 PUT，
 *  杜绝查看/空操作与 Agent 流式落盘竞出 409。 */
const putMock = vi.fn(async (_body?: unknown) => ({ board_version: 1 }));
vi.mock('@/api/project', () => ({
  putProjectState: (body: unknown) => putMock(body),
  getProjectState: vi.fn(async () => ({})),
}));

import { setState, studioActions } from '@/stores/studio';
import { persistBoard } from '@/stores/studio';
import { storyboardActions } from '@/stores/studio/storyboard';
import type { KeyElementGroup } from '@/types';

function snapshot() {
  return {
    keyElements: [{
      id: 'ke1', title: '元素', desc: '描述',
      drafts: [{ id: 'd1', label: '卡', mediaType: 'image', prompt: '' }],
    }] as KeyElementGroup[],
    shots: [], audioItems: [], assets: [],
    board_version: 1,
  };
}

describe('整板保存内容级脏检查', () => {
  beforeEach(() => {
    putMock.mockClear();
    storyboardActions.resetForProject(snapshot() as never);
  });

  it('内容未变：persistBoard 冲刷不发 PUT', async () => {
    // 模拟一次"空保存"调度（如双击阅读触发的编辑态退出）
    persistBoard();
    await persistBoard.flush();
    expect(putMock).not.toHaveBeenCalled();
  });

  it('真实编辑：冲刷发 PUT 且仅一次', async () => {
    studioActions.updateDraftLocal('keyElement', 'd1', { prompt: '新提示词' });
    await persistBoard.flush();
    expect(putMock).toHaveBeenCalledTimes(1);
    // 保存成功后基线跟进：再次空冲刷不再发 PUT
    putMock.mockClear();
    persistBoard();
    await persistBoard.flush();
    expect(putMock).not.toHaveBeenCalled();
  });

  it('服务器快照更新后基线跟进，空保存跳过', async () => {
    storyboardActions.syncFromServer({
      ...snapshot(),
      keyElements: [{
        id: 'ke1', title: '元素', desc: '服务器新描述',
        drafts: [{ id: 'd1', label: '卡', mediaType: 'image', prompt: 'p' }],
      }] as KeyElementGroup[],
    } as never);
    persistBoard();
    await persistBoard.flush();
    expect(putMock).not.toHaveBeenCalled();
  });
});
