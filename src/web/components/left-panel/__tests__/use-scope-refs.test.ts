/**
 * 微调浮窗参考素材钩子单测（二期子对话批 3）：
 * ① 清单 = 已绑 + 待发合并；② 移除按来源分流（待发删暂存 / 已绑调解绑）；
 * ③ 选择文件上传入暂存（上限取自 /api/config 回带）；④ 粘贴直挂摄取。
 */
import { describe, it, expect, vi } from 'vitest';
import { createRoot } from 'solid-js';

vi.mock('@/api/providers', () => ({ getAppConfig: vi.fn() }));
vi.mock('@/lib/chat/adjust-scope-media', () => ({
  uploadScopeRefs: vi.fn(),
  pasteScopeRefs: vi.fn(async () => []),
}));
vi.mock('@/stores/adjust-scopes', () => ({
  adjustScopeActions: {
    addPendingRef: vi.fn(() => true),
    removePendingRef: vi.fn(),
    removeScopeRef: vi.fn(),
  },
}));

import { getAppConfig } from '@/api/providers';
import { uploadScopeRefs } from '@/lib/chat/adjust-scope-media';
import { adjustScopeActions } from '@/stores/adjust-scopes';
import { useScopeRefs } from '../use-scope-refs';
import type { ScopeThread } from '@/stores/adjust-scopes';

const bound = { id: 'b1', name: 'b1.png', kind: 'image', url: '/workspace/assets/b1.png' };
const pending = { id: 'p1', name: 'p1.png', kind: 'image', url: '/workspace/assets/p1.png' };

function threadWith(pendingRefs = [pending], scopeRefs = [bound]) {
  return { pendingRefs, scopeRefs } as unknown as ScopeThread;
}

describe('useScopeRefs 清单与移除分流', () => {
  it('refs 合并已绑在前 + 待发出发；移除按来源分流', () => {
    createRoot((dispose) => {
      const hook = useScopeRefs(() => 'd1', () => threadWith());
      expect(hook.refs().map((r) => r.id)).toEqual(['b1', 'p1']);

      hook.removeRef(pending);
      expect(adjustScopeActions.removePendingRef).toHaveBeenCalledWith('d1', 'p1');
      expect(adjustScopeActions.removeScopeRef).not.toHaveBeenCalled();

      hook.removeRef(bound);
      expect(adjustScopeActions.removeScopeRef).toHaveBeenCalledWith('d1', 'b1');
      dispose();
    });
  });

  it('空线程不崩（未装载键）', () => {
    createRoot((dispose) => {
      const hook = useScopeRefs(() => '', () => undefined);
      expect(hook.refs()).toEqual([]);
      expect(() => hook.removeRef(bound)).not.toThrow();
      dispose();
    });
  });
});

describe('useScopeRefs 摄取入暂存', () => {
  it('选择文件上传后经 addPendingRef 入队（携带上限）', async () => {
    vi.mocked(getAppConfig).mockResolvedValue({ max_attachments: 3 } as never);
    vi.mocked(uploadScopeRefs).mockResolvedValue([pending]);
    await createRoot(async (dispose) => {
      const hook = useScopeRefs(() => 'd1', () => threadWith([], []));
      await hook.onPick([new File(['x'], 'p1.png', { type: 'image/png' })] as unknown as FileList);
      expect(uploadScopeRefs).toHaveBeenCalled();
      expect(adjustScopeActions.addPendingRef).toHaveBeenCalledWith('d1', pending, expect.any(Number));
      dispose();
    });
  });

  it('空选择不开摄取', async () => {
    vi.mocked(uploadScopeRefs).mockClear();
    await createRoot(async (dispose) => {
      const hook = useScopeRefs(() => 'd1', () => threadWith([], []));
      await hook.onPick(null);
      expect(uploadScopeRefs).not.toHaveBeenCalled();
      dispose();
    });
  });
});
