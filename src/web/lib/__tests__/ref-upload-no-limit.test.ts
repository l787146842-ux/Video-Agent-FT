/**
 * 任务 #8 机械断言（前端体验规范 §二 参考图上传 / 台账 #16）：
 * 「分镜面板不设数量上限」的行为与契约断言——
 * ① 上传通道（uploadRefFile）在 maxRefs=Infinity 下不拦截（30 张仍可加）；
 * ② 对照口径：有限上限（关键元素 5）到达即拦截，证明拦截逻辑只在有限值生效；
 * ③ 参考栏存储容量远大于任何生成时上限（无上限语义的工程兜底，不得反向收窄）；
 * ④ 源头契约：PromptEditor 对分镜（shot）的 maxRefs 解析为 Infinity。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, it, expect, vi, beforeEach } from 'vitest';

/** 整板保存旁路：本地编辑的防抖落盘不发真实请求 */
vi.mock('@/api/project', () => ({
  putProjectState: vi.fn(async () => ({ board_version: 1 })),
  getProjectState: vi.fn(async () => ({})),
}));
/** 上传接口旁路：恒成功返回固定地址 */
const uploadFilesMock = vi.fn(async (_files: File[]) => ([{ name: 'new.png', kind: 'image', url: '/assets/uploaded-new.png' }]));
vi.mock('@/api/upload', () => ({ uploadFiles: (files: File[]) => uploadFilesMock(files) }));

import { uploadRefFile } from '../ref-upload';
import { REF_BAR_CAPACITY, VIDEO_GEN_LIMITS, IMAGE_GEN_LIMIT } from '../ref-limits';
import { state, setState } from '@/stores/studio';
import type { Draft, KeyElementGroup, ShotGroup } from '@/types';

/** src/web 根（本文件位于 src/web/lib/__tests__/） */
const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

function refsOf(n: number): string[] {
  return Array.from({ length: n }, (_, i) => `/assets/ref-${i}.png`);
}

function seedShotDraft(refs: string[]) {
  setState({
    shots: [{
      id: 'sh1', title: '分镜 1',
      drafts: [{ id: 'v1', label: '分镜 1', mediaType: 'video', videoUrl: '', prompt: '', refAssets: refs } as Draft],
    } as ShotGroup],
    keyElements: [], audioItems: [], assets: [],
  });
}

function seedKeyElementDraft(refs: string[]) {
  setState({
    keyElements: [{
      id: 'ke1', title: '元素 1',
      drafts: [{ id: 'd1', label: '草稿 1', mediaType: 'image', imgUrl: '', prompt: '', refAssets: refs } as Draft],
    } as KeyElementGroup],
    shots: [], audioItems: [], assets: [],
  });
}

describe('参考图上传不设数量上限（台账 #16）', () => {
  beforeEach(() => {
    uploadFilesMock.mockClear();
    seedShotDraft(refsOf(30));
  });

  it('分镜口径（maxRefs=Infinity）：已有 30 张参考图仍正常上传追加', async () => {
    const rec = { type: 'shot' as const, group: state.shots[0], draft: state.shots[0].drafts[0] };
    await uploadRefFile(rec, Infinity, new File(['x'], 'new.png'));
    expect(uploadFilesMock).toHaveBeenCalledTimes(1);
    const refs = (state.shots[0].drafts[0] as Draft).refAssets || [];
    expect(refs).toHaveLength(31);
    expect(refs[refs.length - 1]).toBe('/assets/uploaded-new.png');
  });

  it('对照：有限上限（关键元素 5）到达即拦截，不触达上传接口', async () => {
    seedKeyElementDraft(refsOf(5));
    const rec = { type: 'keyElement' as const, group: state.keyElements[0], draft: state.keyElements[0].drafts[0] };
    await uploadRefFile(rec, 5, new File(['x'], 'new.png'));
    expect(uploadFilesMock).not.toHaveBeenCalled();
    expect((state.keyElements[0].drafts[0] as Draft).refAssets || []).toHaveLength(5);
  });

  it('参考栏存储容量不窄于生成时上限（无上限语义不得被兜底值反向收窄）', () => {
    expect(REF_BAR_CAPACITY).toBeGreaterThan(VIDEO_GEN_LIMITS.total);
    expect(REF_BAR_CAPACITY).toBeGreaterThan(IMAGE_GEN_LIMIT);
  });

  it('源头契约：PromptEditor 对分镜（shot）解析 maxRefs 为 Infinity', () => {
    const src = fs.readFileSync(
      path.join(WEB_ROOT, 'components/middle-panel/PromptEditor.tsx'),
      'utf-8',
    );
    expect(src).toMatch(/selectedType\s*===\s*'shot'\s*\?\s*Infinity/);
  });
});
