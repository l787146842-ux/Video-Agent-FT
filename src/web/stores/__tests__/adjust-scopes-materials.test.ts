/**
 * 微调线程参考素材单测（二期子对话批 3）：
 * ① loadThread 装载后端回带 scope_refs（清单重建，重开不丢）；
 * ② addPendingRef 上限守卫 / removePendingRef 仅删暂存；
 * ③ sendAdjust 携带 attachments 且本地乐观并入已绑清单（主对话零污染面）；
 * ④ removeScopeRef 乐观剔除 + 调后端解绑（只删引用）；
 * ⑤ sendAdjust 流式失败回滚（评审修补批：本批并入退回待发）；
 * ⑥ addPendingRef 同 url 去重（防幽灵条目误导 toast）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/api/conversations', () => ({
  getOrCreateAdjustThread: vi.fn(),
  unrefThreadMaterial: vi.fn(async () => ({ ok: true })),
}));
vi.mock('@/hooks/use-sse', () => ({ streamAgentChat: vi.fn(async () => {}) }));
vi.mock('@/stores/agent-prefs', () => ({ agentProvider: () => 'provA', agentModel: () => 'model-A' }));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { getOrCreateAdjustThread, unrefThreadMaterial } from '@/api/conversations';
import { streamAgentChat } from '@/hooks/use-sse';
import { showToast } from '@/stores/toast';
import { adjustScopes, adjustScopeActions, type AdjustScopeTarget } from '../adjust-scopes';

const target: AdjustScopeTarget = {
  kind: 'adjust', cat: 'shotGroups', group_id: 'g1', draft_id: 'd1', label: '分镜 1-1',
};
const ref = (id: string) => ({ id, name: `${id}.png`, kind: 'image', url: `/workspace/assets/${id}.png` });

beforeEach(() => {
  adjustScopeActions.reset();
  vi.mocked(getOrCreateAdjustThread).mockReset();
  vi.mocked(unrefThreadMaterial).mockClear();
  vi.mocked(streamAgentChat).mockReset().mockResolvedValue(undefined);
  vi.mocked(showToast).mockClear();
});

describe('loadThread 装载 scope_refs', () => {
  it('后端回带清单重建；无回带时空清单', async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({
      conversation_id: 'convT', messages: [],
      scope_refs: [{ id: 'r1', name: 'a.png', kind: 'image', url: '/workspace/assets/a.png' }],
    });
    await adjustScopeActions.openThread(target);
    expect(adjustScopes['d1'].scopeRefs).toHaveLength(1);
    expect(adjustScopes['d1'].scopeRefs[0]).toMatchObject({ id: 'r1', url: '/workspace/assets/a.png' });
    expect(adjustScopes['d1'].pendingRefs).toEqual([]);

    adjustScopeActions.reset();
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({ conversation_id: 'convT', messages: [] });
    await adjustScopeActions.openThread(target);
    expect(adjustScopes['d1'].scopeRefs).toEqual([]);
  });
});

describe('pendingRefs 暂存与上限', () => {
  beforeEach(async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({ conversation_id: 'convT', messages: [] });
    await adjustScopeActions.openThread(target);
  });

  it('addPendingRef 入队；已绑 + 待发合计达上限拒收并提示', () => {
    expect(adjustScopeActions.addPendingRef('d1', ref('p1'), 2)).toBe(true);
    expect(adjustScopes['d1'].pendingRefs).toHaveLength(1);
    expect(adjustScopeActions.addPendingRef('d1', ref('p2'), 2)).toBe(true);
    expect(adjustScopeActions.addPendingRef('d1', ref('p3'), 2)).toBe(false);
    expect(adjustScopes['d1'].pendingRefs).toHaveLength(2);
    expect(showToast).toHaveBeenCalled();
  });

  it('同 url 重复添加静默拒收（待发与已绑双口径去重）', () => {
    expect(adjustScopeActions.addPendingRef('d1', ref('p1'), 5)).toBe(true);
    // 同 url 不同 id：前端不去重会产生幽灵条目，删除时误报移除失败
    expect(adjustScopeActions.addPendingRef(
      'd1', { id: 'p1-ghost', name: 'g.png', kind: 'image', url: '/workspace/assets/p1.png' }, 5,
    )).toBe(false);
    expect(adjustScopes['d1'].pendingRefs).toHaveLength(1);
  });

  it('已绑清单同 url 同样去重（后端按 url 先入者保留其 id）', async () => {
    adjustScopeActions.reset();
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({
      conversation_id: 'convT', messages: [],
      scope_refs: [{ id: 'r1', name: 'a.png', kind: 'image', url: '/workspace/assets/a.png' }],
    });
    await adjustScopeActions.openThread(target);
    expect(adjustScopeActions.addPendingRef(
      'd1', { id: 'r1-ghost', name: 'a.png', kind: 'image', url: '/workspace/assets/a.png' }, 5,
    )).toBe(false);
    expect(adjustScopes['d1'].pendingRefs).toEqual([]);
  });

  it('removePendingRef 仅删暂存（未发送不打后端）', () => {
    adjustScopeActions.addPendingRef('d1', ref('p1'), 5);
    adjustScopeActions.removePendingRef('d1', 'p1');
    expect(adjustScopes['d1'].pendingRefs).toEqual([]);
    expect(unrefThreadMaterial).not.toHaveBeenCalled();
  });
});

describe('sendAdjust 携带 attachments（绑线程，不进全局）', () => {
  it('待发引用随请求携带并乐观并入已绑清单', async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({ conversation_id: 'convT', messages: [] });
    await adjustScopeActions.openThread(target);
    adjustScopeActions.addPendingRef('d1', ref('p1'), 5);
    expect(adjustScopeActions.sendAdjust(target, '照这个风格改')).toBe(true);

    const [reqArg] = vi.mocked(streamAgentChat).mock.calls[0];
    expect(reqArg?.attachments).toEqual([
      { id: 'p1', name: 'p1.png', kind: 'image', url: '/workspace/assets/p1.png' },
    ]);
    // 本地乐观：已绑清单并入、暂存清空（后端按 url 去重，重开浮窗回带为准）
    expect(adjustScopes['d1'].pendingRefs).toEqual([]);
    expect(adjustScopes['d1'].scopeRefs.map((r) => r.id)).toEqual(['p1']);
  });

  it('流式失败：本批乐观并入的引用回滚退回待发（防假已绑静默丢失）', async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({ conversation_id: 'convT', messages: [] });
    await adjustScopeActions.openThread(target);
    adjustScopeActions.addPendingRef('d1', ref('p1'), 5);
    vi.mocked(streamAgentChat).mockRejectedValue(new Error('SSE 断'));
    expect(adjustScopeActions.sendAdjust(target, '照这个风格改')).toBe(true);
    // 乐观并入先行：已绑清单含本批、暂存清空；失败后必须原样退回
    expect(adjustScopes['d1'].scopeRefs.map((r) => r.id)).toEqual(['p1']);
    await Promise.resolve();
    await Promise.resolve();
    expect(adjustScopes['d1'].scopeRefs).toEqual([]);
    expect(adjustScopes['d1'].pendingRefs.map((r) => r.id)).toEqual(['p1']);
    // 错误可见：线程视图落 error 态与错误文案（浮窗呈现，不静默吞）
    expect(adjustScopes['d1'].status).toBe('error');
    expect(adjustScopes['d1'].errorText).toBe('SSE 断');
  });

  it('无待发引用时不带 attachments（瘦身请求口径不变）', async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({ conversation_id: 'convT', messages: [] });
    await adjustScopeActions.openThread(target);
    expect(adjustScopeActions.sendAdjust(target, '改亮一点')).toBe(true);
    const [reqArg] = vi.mocked(streamAgentChat).mock.calls[0];
    expect(reqArg?.attachments).toBeUndefined();
  });
});

describe('removeScopeRef 解绑', () => {
  it('乐观剔除并调后端 unref（只删引用，物理文件不清）', async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({
      conversation_id: 'convT', messages: [],
      scope_refs: [{ id: 'r1', name: 'a.png', kind: 'image', url: '/workspace/assets/a.png' }],
    });
    await adjustScopeActions.openThread(target);
    adjustScopeActions.removeScopeRef('d1', 'r1');
    expect(adjustScopes['d1'].scopeRefs).toEqual([]);
    expect(unrefThreadMaterial).toHaveBeenCalledWith('convT', 'r1');
  });

  it('后端解绑失败：本地已剔除不回滚，error toast 可见', async () => {
    vi.mocked(getOrCreateAdjustThread).mockResolvedValue({
      conversation_id: 'convT', messages: [],
      scope_refs: [{ id: 'r1', name: 'a.png', kind: 'image', url: '/workspace/assets/a.png' }],
    });
    vi.mocked(unrefThreadMaterial).mockRejectedValue(new Error('500'));
    await adjustScopeActions.openThread(target);
    adjustScopeActions.removeScopeRef('d1', 'r1');
    await Promise.resolve();
    await Promise.resolve();
    expect(showToast).toHaveBeenCalled();
  });
});
