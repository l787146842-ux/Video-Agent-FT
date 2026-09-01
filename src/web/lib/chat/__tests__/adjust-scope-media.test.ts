/**
 * 微调子对话浮窗素材摄取单测（二期子对话批 3）：
 * ① 文档类型入口即拒（不打上传接口，一期只开图片/视频/音频）；
 * ② 媒体上传 → 引用条目映射（非媒体回包双保险过滤）；
 * ③ 粘贴图片走同口径摄取。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/api/upload', () => ({ uploadFiles: vi.fn() }));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { uploadFiles } from '@/api/upload';
import { showToast } from '@/stores/toast';
import { uploadScopeRefs, pasteScopeRefs } from '../adjust-scope-media';

beforeEach(() => {
  vi.mocked(uploadFiles).mockReset();
  vi.mocked(showToast).mockClear();
});

describe('uploadScopeRefs 入口类型闸', () => {
  it('文档类当场拒收：不打上传接口并提示', async () => {
    const pdf = new File(['x'], 'spec.pdf', { type: 'application/pdf' });
    expect(await uploadScopeRefs([pdf])).toEqual([]);
    expect(uploadFiles).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('不支持文档'), 'warning');
  });

  it('媒体类照常上传并映射为引用条目', async () => {
    const img = new File(['x'], 'ref.png', { type: 'image/png' });
    vi.mocked(uploadFiles).mockResolvedValue([
      { name: 'ref.png', kind: 'image', url: '/workspace/assets/ref.png' },
    ]);
    const refs = await uploadScopeRefs([img]);
    expect(uploadFiles).toHaveBeenCalledWith([img]);
    expect(refs).toHaveLength(1);
    expect(refs[0]).toMatchObject({ name: 'ref.png', kind: 'image', url: '/workspace/assets/ref.png' });
    expect(refs[0].id).toBeTruthy();
  });

  it('回包中的非媒体项双保险过滤（一期口径只开图/视/音）', async () => {
    const img = new File(['x'], 'a.png', { type: 'image/png' });
    vi.mocked(uploadFiles).mockResolvedValue([
      { name: 'a.png', kind: 'image', url: '/workspace/assets/a.png' },
      { name: 'b.pdf', kind: 'doc', url: '/workspace/assets/b.pdf' },
    ]);
    const refs = await uploadScopeRefs([img]);
    expect(refs.map((r) => r.url)).toEqual(['/workspace/assets/a.png']);
  });

  it('上传异常不抛错：error toast + 空清单', async () => {
    const img = new File(['x'], 'a.png', { type: 'image/png' });
    vi.mocked(uploadFiles).mockRejectedValue(new Error('超大'));
    expect(await uploadScopeRefs([img])).toEqual([]);
    expect(showToast).toHaveBeenCalledWith('超大', 'error');
  });
});

describe('pasteScopeRefs 粘贴摄取', () => {
  function clipEvent(items: { type: string; getAsFile: () => File | null }[]) {
    let prevented = false;
    const ev = {
      clipboardData: { items },
      preventDefault: () => { prevented = true; },
    } as unknown as ClipboardEvent;
    return { ev, wasPrevented: () => prevented };
  }

  it('剪贴板图片上传为引用并阻止默认粘贴', async () => {
    const img = new File(['x'], 'clip.png', { type: 'image/png' });
    vi.mocked(uploadFiles).mockResolvedValue([
      { name: 'clip.png', kind: 'image', url: '/workspace/assets/clip.png' },
    ]);
    const { ev, wasPrevented } = clipEvent([
      { type: 'image/png', getAsFile: () => img },
      { type: 'text/plain', getAsFile: () => null },
    ]);
    const refs = await pasteScopeRefs(ev);
    expect(wasPrevented()).toBe(true);
    expect(refs.map((r) => r.url)).toEqual(['/workspace/assets/clip.png']);
  });

  it('无图片粘贴项：不阻止默认行为，返回空', async () => {
    const { ev, wasPrevented } = clipEvent([{ type: 'text/plain', getAsFile: () => null }]);
    expect(await pasteScopeRefs(ev)).toEqual([]);
    expect(wasPrevented()).toBe(false);
  });

  it('无剪贴板数据：安全返回空', async () => {
    const ev = { clipboardData: null } as unknown as ClipboardEvent;
    expect(await pasteScopeRefs(ev)).toEqual([]);
  });
});
