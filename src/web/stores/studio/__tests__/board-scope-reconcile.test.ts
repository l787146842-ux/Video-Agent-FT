/**
 * 微调线程注册表对账与素材池豁免单测（评审修补批）：
 * ① 移入素材池是非破坏移动（可还原）：前端线程键保留、浮窗不关，
 *    还原后线程仍在（历史不丢）；普通删除照旧级联清键；
 * ② Agent FC/他窗删分组经快照同步到达本窗时无独立删除入口可挂级联，
 *    同步收口处按存活集对账（三板草稿 + 素材池来源豁免），死键清线程。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/api/conversations', () => ({
  getOrCreateAdjustThread: vi.fn(),
  unrefThreadMaterial: vi.fn(async () => ({ ok: true })),
}));
vi.mock('@/hooks/use-sse', () => ({ streamAgentChat: vi.fn(async () => {}) }));
vi.mock('@/stores/agent-prefs', () => ({ agentProvider: () => 'provA', agentModel: () => 'model-A' }));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { getOrCreateAdjustThread } from '@/api/conversations';
import { studioActions, state, setState } from '@/stores/studio';
import { boardSyncActions } from '../board-sync';
import { adjustScopes, adjustScopeActions, type AdjustScopeTarget } from '../../adjust-scopes';
import type { Draft, KeyElementGroup, ServerStateSnapshot } from '@/types';

const target: AdjustScopeTarget = {
  kind: 'adjust', cat: 'keyElement', group_id: 'ke1', draft_id: 'd2', label: '元素 1-2',
};

function seedBoard() {
  setState('keyElements', [{
    id: 'ke1', title: '主角', desc: '',
    drafts: [
      { id: 'd1', label: '草稿1', tag: '', mediaType: 'image', imgUrl: '', prompt: '' },
      { id: 'd2', label: '草稿2', tag: '', mediaType: 'image', imgUrl: '', prompt: '' },
    ],
  } as KeyElementGroup]);
  setState('shots', []);
  setState('audioItems', []);
  setState('assets', []);
  setState('selectedDraftId', 'd1');
  setState('selectedType', 'keyElement');
}

async function openThreadFor(draftId: string) {
  vi.mocked(getOrCreateAdjustThread).mockResolvedValue({ conversation_id: `conv-${draftId}`, messages: [] });
  const ok = await adjustScopeActions.openThread({ ...target, draft_id: draftId });
  expect(ok).toBe(true);
}

beforeEach(() => {
  seedBoard();
  adjustScopeActions.reset();
  vi.mocked(getOrCreateAdjustThread).mockReset();
});

describe('移入素材池：非破坏移动不级联线程（评审修补批第 2 项）', () => {
  it('移入素材池线程键保留、浮窗不关；还原后线程仍在', async () => {
    await openThreadFor('d2');
    expect(adjustScopes['d2']).toBeTruthy();

    studioActions.moveDraftToAssets('keyElement', 'ke1', 'd2');
    // 线程仍在（可还原移动不得硬删）；浮窗开合状态不被级联触碰
    expect(adjustScopes['d2']).toBeTruthy();
    expect(adjustScopes['d2'].open).toBe(true);
    expect(state.assets[0].sourceDraft?.id).toBe('d2');

    // 还原回板：历史还在（线程从未被删）
    expect(studioActions.restoreAssetToSource(state.assets[0].id)).toBe(true);
    expect(state.keyElements[0].drafts.map((d) => d.id)).toEqual(['d1', 'd2']);
    expect(adjustScopes['d2']).toBeTruthy();
    expect(adjustScopes['d2'].convId).toBe('conv-d2');
  });

  it('普通删除照旧级联：线程键移除（回归守卫，豁免只开给可还原移动）', async () => {
    await openThreadFor('d2');
    studioActions.removeDraftLocal('keyElement', 'ke1', 'd2');
    expect(adjustScopes['d2']).toBeUndefined();
  });
});

const draft = (id: string, label: string): Draft => (
  { id, label, tag: '', mediaType: 'image', imgUrl: '', prompt: '' });

describe('快照同步收口对账（评审修补批第 4 项）', () => {
  function snapshot(patch: Partial<ServerStateSnapshot>): ServerStateSnapshot {
    return {
      keyElements: [{ id: 'ke1', title: '主角', drafts: [] }],
      shots: [], audioItems: [], assets: [],
      ...patch,
    } as ServerStateSnapshot;
  }

  it('草稿已不在三板也不在素材池：同步到达即清死线程键', async () => {
    await openThreadFor('d2');
    // Agent 在他窗删了含 d2 的分组：快照到达本窗（无 d2、无素材池来源）
    boardSyncActions.syncFromServer(snapshot({
      keyElements: [{ id: 'ke1', title: '主角', drafts: [draft('d1', '草稿1')] }],
    }));
    expect(adjustScopes['d2']).toBeUndefined();
  });

  it('草稿仍在三板：线程键不动（对账不误伤）', async () => {
    await openThreadFor('d2');
    boardSyncActions.syncFromServer(snapshot({
      keyElements: [{ id: 'ke1', title: '主角', drafts: [draft('d2', '草稿2')] }],
    }));
    expect(adjustScopes['d2']).toBeTruthy();
  });

  it('草稿在素材池来源（可还原移动）：豁免不清线程', async () => {
    await openThreadFor('d2');
    boardSyncActions.syncFromServer(snapshot({
      keyElements: [{ id: 'ke1', title: '主角', drafts: [draft('d1', '草稿1')] }],
      assets: [{
        id: 'a1', name: '草稿2', type: 'image', isBound: false, url: '',
        sourceDraft: draft('d2', '草稿2'),
      }],
    }));
    expect(adjustScopes['d2']).toBeTruthy();
  });
});
