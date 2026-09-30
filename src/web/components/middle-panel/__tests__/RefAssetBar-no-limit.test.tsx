/**
 * 任务 #8 机械断言（前端体验规范 §二 参考图上传 / 台账 #16）：
 * 「分镜面板不设数量上限」的 UI 入口断言——
 * ① 无上限口径（maxRefs=Infinity）下，即便参考素材已达 30 张，
 *    「+」添加入口仍然显示（不得因数量隐藏上传入口）；
 * ② 对照口径：有限上限到达时入口隐藏（证明显隐逻辑由 maxRefs 驱动）；
 * ③ 移除一张后素材数如实减少（入口与列表联动可用）。
 *
 * 选择弹窗以捕获型桩替代（仅截留 onPick 回调，不渲染真实弹窗）；
 * @提及映射、素材类型判定亦以桩替代控制测试面；
 * 上传通道行为断言见 lib/__tests__/ref-upload-no-limit.test.ts。
 */
import { render, fireEvent, waitFor } from '@solidjs/testing-library';
import { describe, it, expect, beforeEach, vi } from 'vitest';

/** 捕获选择弹窗的 onPick（桩不渲染弹窗本体，只留回调通道） */
const pickRef = vi.hoisted(() => ({
  onPick: undefined as undefined | ((items: Array<{ url: string; name?: string }>) => void),
}));

/** 旁路打桩：选择弹窗（含画布拉取）、@提及映射、素材类型判定不进测试面 */
vi.mock('../RefAssetPickerModal', () => ({
  // JSX 插值点随渲染响应式求值：弹窗打开即截留 onPick（不渲染弹窗本体）
  RefAssetPickerModal: (p: { open: boolean; onPick: (items: Array<{ url: string; name?: string }>) => void }) => (
    <>{p.open ? (pickRef.onPick = p.onPick) && null : null}</>
  ),
}));
vi.mock('@/lib/prompt-mentions', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/prompt-mentions')>();
  return {
    // 只桩掉媒体映射（画布素材面），`mentionNamesIn` 用**真实现**——
    // 本次修复的正是「计数与提示词框同口径」，桩掉它就等于测不到。
    ...actual,
    storyboardMediaMap: () => ({ '月球': { url: '/assets/moon.png', kind: 'image' } }),
  };
});
vi.mock('@/api/upload', () => ({
  uploadFiles: async (_files: File[]) => [{ name: 'up.png', kind: 'image', url: '/assets/up.png' }],
}));
vi.mock('@/lib/prompt-ref-utils', () => ({
  refAssetType: (url: string) => (url.endsWith('.mp4') ? 'video' : url.endsWith('.mp3') ? 'audio' : 'image'),
  refAssetName: (_url: string, idx: number) => `参考素材 ${idx + 1}`,
  videoThumb: (u: string) => u,
}));

import { RefAssetBar } from '../RefAssetBar';
import { state, setState } from '@/stores/studio';
import type { DraftRecord, ShotGroup } from '@/types';

function refsOf(n: number): string[] {
  return Array.from({ length: n }, (_, i) => `/assets/ref-${i}.png`);
}

/** rec 指向真实 store 内的分镜草稿（移除/添加操作走真实 updateDraftLocal） */
function seedShotDraft(refs: string[], prompt = '') {
  setState({
    shots: [{
      id: 'sh1', title: '分镜 1',
      drafts: [{
        id: 'v1', label: '分镜 1', mediaType: 'video',
        videoUrl: '', prompt, refAssets: refs,
      }],
    } as ShotGroup],
    keyElements: [], audioItems: [], assets: [],
  });
  const group = state.shots[0];
  return { type: 'shot' as const, group, draft: group.drafts[0] } as DraftRecord;
}

describe('参考素材栏添加入口不受数量限制（台账 #16）', () => {
  beforeEach(() => {
    // 上一用例可能改过 selectedDraftId 等，收拢到干净基线
    setState({ selectedDraftId: '', selectedType: 'shot' });
  });

  it('无上限口径：已有 30 张参考素材，「+」添加入口仍在', () => {
    const refs = refsOf(30);
    const rec = seedShotDraft(refs);
    const { container } = render(() => (
      <RefAssetBar rec={() => rec} refAssets={() => refs} maxRefs={() => Infinity} />
    ));
    expect(container.querySelector('.ref-upload-btn')).toBeTruthy();
    expect(container.querySelectorAll('.ref-thumb-wrap')).toHaveLength(30);
  });

  it('对照：有限上限（5）到达时添加入口隐藏', () => {
    const refs = refsOf(5);
    const rec = seedShotDraft(refs);
    const { container } = render(() => (
      <RefAssetBar rec={() => rec} refAssets={() => refs} maxRefs={() => 5} />
    ));
    expect(container.querySelector('.ref-upload-btn')).toBeNull();
  });

  it('点 × 移除一张：草稿参考素材如实减少', () => {
    const refs = refsOf(3);
    const rec = seedShotDraft(refs);
    const { container } = render(() => (
      <RefAssetBar rec={() => rec} refAssets={() => state.shots[0].drafts[0].refAssets || []} maxRefs={() => Infinity} />
    ));
    const removeBtn = container.querySelector('.ref-thumb-remove') as HTMLElement;
    fireEvent.click(removeBtn);
    expect(state.shots[0].drafts[0].refAssets).toHaveLength(2);
  });

  it('点 + 开菜单、从画布选一张：无上限口径 30→31 仍能添加', () => {
    const refs = refsOf(30);
    const rec = seedShotDraft(refs);
    const { container } = render(() => (
      <RefAssetBar rec={() => rec} refAssets={() => state.shots[0].drafts[0].refAssets || []} maxRefs={() => Infinity} />
    ));
    fireEvent.click(container.querySelector('.ref-upload-btn') as HTMLElement);
    const menu = container.querySelector('.ref-add-menu');
    expect(menu).toBeTruthy();
    // 点「画布」项 → 打开选择弹窗（桩捕获 onPick），菜单收起
    const canvasItem = Array.from(container.querySelectorAll('.ref-add-menu-item'))
      .find((el) => el.textContent?.includes('画布')) as HTMLElement;
    fireEvent.click(canvasItem);
    expect(container.querySelector('.ref-add-menu')).toBeNull();
    expect(pickRef.onPick).toBeTruthy();
    pickRef.onPick!([{ url: '/assets/picked.png', name: '画布图' }]);
    expect(state.shots[0].drafts[0].refAssets).toHaveLength(31);
    // 重复添加同一素材 → 拒绝（数量不涨）
    fireEvent.click(container.querySelector('.ref-upload-btn') as HTMLElement);
    fireEvent.click(Array.from(container.querySelectorAll('.ref-add-menu-item'))
      .find((el) => el.textContent?.includes('画布')) as HTMLElement);
    pickRef.onPick!([{ url: '/assets/picked.png', name: '画布图' }]);
    expect(state.shots[0].drafts[0].refAssets).toHaveLength(31);
  });

  it('菜单打开后点击外部：菜单自动收起', () => {
    const rec = seedShotDraft(refsOf(2));
    const { container } = render(() => (
      <RefAssetBar rec={() => rec} refAssets={() => state.shots[0].drafts[0].refAssets || []} maxRefs={() => Infinity} />
    ));
    fireEvent.click(container.querySelector('.ref-upload-btn') as HTMLElement);
    expect(container.querySelector('.ref-add-menu')).toBeTruthy();
    fireEvent.pointerDown(document.body);
    expect(container.querySelector('.ref-add-menu')).toBeNull();
  });

  it('视频/音频/图片素材按类型分别渲染缩略形态', () => {
    const rec = seedShotDraft(['/assets/a.png', '/assets/b.mp4', '/assets/c.mp3']);
    const { container } = render(() => (
      <RefAssetBar rec={() => rec} refAssets={() => ['/assets/a.png', '/assets/b.mp4', '/assets/c.mp3']} maxRefs={() => Infinity} />
    ));
    expect(container.querySelector('.ref-video-wrap video')).toBeTruthy();
    expect(container.querySelector('.ref-thumb-audio')).toBeTruthy();
    expect(container.querySelectorAll('.ref-thumb-wrap')).toHaveLength(3);
  });

  it('本地上传：选文件即上传并追加（无上限口径 3→4）', async () => {
    const rec = seedShotDraft(refsOf(3));
    const { container } = render(() => (
      <RefAssetBar rec={() => rec} refAssets={() => state.shots[0].drafts[0].refAssets || []} maxRefs={() => Infinity} />
    ));
    fireEvent.click(container.querySelector('.ref-upload-btn') as HTMLElement);
    const localItem = Array.from(container.querySelectorAll('.ref-add-menu-item'))
      .find((el) => el.textContent?.includes('本地上传')) as HTMLElement;
    fireEvent.click(localItem);
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [new File(['x'], 'a.png', { type: 'image/png' })] } });
    await waitFor(() => expect(state.shots[0].drafts[0].refAssets).toHaveLength(4));
    expect(state.shots[0].drafts[0].refAssets).toContain('/assets/up.png');
  });

  it('拖入文件即上传追加（整框接收拖拽）', async () => {
    const rec = seedShotDraft(refsOf(1));
    const { container } = render(() => (
      <RefAssetBar rec={() => rec} refAssets={() => state.shots[0].drafts[0].refAssets || []} maxRefs={() => Infinity} />
    ));
    const zone = container.querySelector('.ref-drop-zone') as HTMLElement;
    fireEvent.drop(zone, { dataTransfer: { files: [new File(['x'], 'd.png', { type: 'image/png' })] } });
    await waitFor(() => expect(state.shots[0].drafts[0].refAssets).toHaveLength(2));
  });

  it('右侧计数含提示词 @ 引用的故事板素材（去重）', () => {
    // 参考栏 1 张 + 提示词 @月球 1 张（画布素材）→ 计 2；同 URL 不重复计
    const rec = seedShotDraft(['/assets/moon.png'], '月光下 @月球 特写');
    const { container } = render(() => (
      <RefAssetBar rec={() => rec} refAssets={() => ['/assets/moon.png']} maxRefs={() => Infinity} />
    ));
    const badge = container.querySelector('.ref-count-badge') as HTMLElement;
    expect(badge.title).toContain('已加载参考素材 1 个');
  });

  it('计数容 `@[名称]` 写法（剥方括号，与提示词框内图块同口径）', () => {
    // 参考栏空 + 提示词 @[月球] → 应计 1。
    // 2026-09-26 前此处手抄正则不剥方括号 ⇒ 捕获 `[月球]` 查表落空、计数恒 0，
    // 与已经渲染出图块的提示词框自相矛盾（用户所报「栏里有、图块没有」的观感来源之一）。
    const rec = seedShotDraft([], '参考 @[月球] 的构图');
    const { container } = render(() => (
      <RefAssetBar rec={() => rec} refAssets={() => []} maxRefs={() => Infinity} />
    ));
    const badge = container.querySelector('.ref-count-badge') as HTMLElement;
    expect(badge.title).toContain('已加载参考素材 1 个');
  });

  it('分镜卡不渲染「绑定元素参考」只读胶囊行，只留方形缩略图（2026-09-30 用户裁决）', () => {
    // 现场：9999 的 S11「运镜轨迹图」参考栏里，同一组 refAssets 被画两遍——
    // 三枚只读胶囊（`.shot-refs > .shot-ref-chip`，带 `Element_xxx` 文字）
    // + 三张方形缩略图（`.ref-thumb-wrap`）。用户裁决：删胶囊、留方图。
    // 防翻案：本钉锁死 `.ref-thumbs` 下**不得**再出现胶囊行。
    const refs = ['/assets/a.png', '/assets/b.png'];
    const rec = seedShotDraft(refs);
    const { container } = render(() => (
      <RefAssetBar rec={() => rec} refAssets={() => refs} maxRefs={() => Infinity} />
    ));
    expect(container.querySelector('.ref-thumbs .shot-refs')).toBeNull();
    expect(container.querySelectorAll('.shot-ref-chip')).toHaveLength(0);
    // 方图仍在（删胶囊不得连带删缩略图）
    expect(container.querySelectorAll('.ref-thumb-wrap')).toHaveLength(2);
  });
});
