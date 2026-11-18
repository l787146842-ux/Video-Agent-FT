/**
 * 草稿卡卡面契约（2026-10-22 用户裁决「卡面文字信息删掉，图片/未生成分开」）：
 * ① **零文字**：任何草稿卡都不渲染名称/描述/状态标签（.draft-card-label /
 *    .draft-card-desc / .draft-card-tag 恒为 null），名称+描述改走悬停 title；
 * ② **图片**：已生成 → 背景缩略图 + 实线窄边框（.draft-card--filled）；
 * ③ **视频**：已生成 → 首帧缩略图 <video> + 左上角类型角标；
 * ④ **音频**：未生成 → 只留广播符号（.draft-card-audio-indicator.is-empty，
 *    图4 口径，无波形）；已生成 → 音符 + 波形（现行符号）；
 * ⑤ **未生成**：虚线窄边框（.draft-card--empty）+ 居中类型占位符号。
 */
import { render } from '@solidjs/testing-library';
import { describe, it, expect, vi } from 'vitest';

/** 旁路通道打桩：只测渲染面，不触真发送/撤销/菜单 */
vi.mock('@/lib/chat/chat-input-bridge', () => ({
  requestInsertMedia: vi.fn(),
  requestInsertText: vi.fn(),
}));
vi.mock('@/lib/rich-input', () => ({ draftToInlineMedia: vi.fn(() => null) }));
vi.mock('@/stores/history', () => ({ checkpointHistory: vi.fn(), performUndo: vi.fn() }));
vi.mock('@/components/shared/ContextMenu', () => ({ showContextMenu: vi.fn() }));
vi.mock('@/components/shared/ConfirmDialog', () => ({ confirmDialog: vi.fn() }));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { DraftCard } from '../left-panel/DraftCard';
import type { Draft, DraftType } from '@/types';

function setup(draft: Draft, type: DraftType) {
  return render(() => <DraftCard draft={draft} type={type} groupId="g1" cardCode="1-1" />);
}

/** 卡面零文字断言（三类文字元素一个都不许出现） */
function expectNoCardText(container: HTMLElement) {
  expect(container.querySelector('.draft-card-label')).toBeNull();
  expect(container.querySelector('.draft-card-desc')).toBeNull();
  expect(container.querySelector('.draft-card-tag')).toBeNull();
}

describe('草稿卡卡面零文字（2026-10-22 用户裁决）', () => {
  const cases: Array<[string, Draft, DraftType]> = [
    ['关键元素设定图（未生成）', {
      id: 'd1', label: '设定图 · 程心（三视图）', tag: 'Agent', mediaType: 'image',
      desc: '【角色视觉设定 · 程心】约 28 岁女性，东亚面孔…', prompt: 'p', imgUrl: '',
    }, 'keyElement'],
    ['关键元素音色卡（未生成）', {
      id: 'd2', label: '音色 · 程心', tag: 'Agent', mediaType: 'audio',
      desc: '声音特征：女声，中音，音色温润略带沙哑', prompt: 'tts', audioUrl: '',
    }, 'keyElement'],
    ['分镜视频卡（未生成）', {
      id: 'd3', label: '分镜视频 3-2', tag: 'Agent', mediaType: 'video',
      desc: '中景 · 平视 · 推进', prompt: 'p', videoUrl: '',
    }, 'shot'],
    ['音频 tab 的 BGM 卡（未生成）', {
      id: 'd4', label: 'BGM_末日静默', tag: '', mediaType: 'audio',
      desc: '压迫而辽阔的科幻氛围', prompt: 'p', audioUrl: '',
    }, 'audio'],
  ];

  for (const [name, draft, type] of cases) {
    it(`${name} → 卡面无名称/描述/状态文字，名称+描述落 title`, () => {
      const { container } = setup(draft, type);
      expectNoCardText(container);
      const card = container.querySelector('.draft-card') as HTMLElement;
      expect(card.getAttribute('title')).toContain(draft.label!);
      expect(card.getAttribute('title')).toContain(draft.desc!);
    });
  }
});

describe('图片：有图/无图两种形态分开', () => {
  it('已生成图片 → 背景缩略图 + 实线窄边框（--filled），无占位符号', () => {
    const { container } = setup({
      id: 'd1', label: '设定图 · 程心', tag: '已生成', mediaType: 'image',
      prompt: 'p', imgUrl: '/workspace/assets/a.png',
    }, 'keyElement');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card.style.backgroundImage).toContain('/workspace/assets/a.png');
    expect(card.classList.contains('draft-card--filled')).toBe(true);
    expect(card.classList.contains('draft-card--empty')).toBe(false);
    expect(container.querySelector('.draft-card-placeholder-icon')).toBeNull();
    expectNoCardText(container);
  });

  it('未生成图片 → 虚线窄边框（--empty）+ 居中类型占位符号', () => {
    const { container } = setup({
      id: 'd2', label: '设定图 · AA', tag: 'Agent', mediaType: 'image', prompt: 'p', imgUrl: '',
    }, 'keyElement');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card.classList.contains('draft-card--empty')).toBe(true);
    expect(card.classList.contains('draft-card--filled')).toBe(false);
    expect(container.querySelector('.draft-card-placeholder-icon')).toBeTruthy();
    expectNoCardText(container);
  });
});

describe('视频：已生成用首帧，未生成用占位符号', () => {
  it('已生成视频 → 首帧 <video> + 左上角类型角标，无占位符号', () => {
    const { container } = setup({
      id: 'd1', label: '分镜视频 1-1', mediaType: 'video',
      prompt: 'p', videoUrl: '/workspace/assets/v.mp4',
    }, 'shot');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(container.querySelector('.draft-card-thumb-video')).toBeTruthy();
    expect(container.querySelector('.draft-card-media-badge')).toBeTruthy();
    expect(card.classList.contains('draft-card--filled')).toBe(true);
    expect(container.querySelector('.draft-card-placeholder-icon')).toBeNull();
    expectNoCardText(container);
  });

  it('未生成视频 → 虚线边 + 占位符号（不渲染 <video>）', () => {
    const { container } = setup({
      id: 'd2', label: '分镜视频 1-2', mediaType: 'video', prompt: 'p', videoUrl: '',
    }, 'shot');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(container.querySelector('.draft-card-thumb-video')).toBeNull();
    expect(card.classList.contains('draft-card--empty')).toBe(true);
    expect(container.querySelector('.draft-card-placeholder-icon')).toBeTruthy();
  });
});

describe('生成失败态：文字摘除后仍须可辨识（非文字信号）', () => {
  it('tag=生成失败 → 挂 --failed 类（危险色窄边），且 title 头部点明「生成失败」', () => {
    const { container } = setup({
      id: 'd1', label: '设定图 · 曹彬', tag: '生成失败', mediaType: 'image',
      desc: '老年态胸像', prompt: 'p', imgUrl: '',
    }, 'keyElement');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card.classList.contains('draft-card--failed')).toBe(true);
    expect(card.getAttribute('title')).toContain('生成失败');
    expectNoCardText(container);
  });

  it('未失败的空卡不挂 --failed（第三态不得误伤正常空卡）', () => {
    const { container } = setup({
      id: 'd2', label: '设定图 · 瓦西里', tag: 'Agent', mediaType: 'image',
      desc: '', prompt: 'p', imgUrl: '',
    }, 'keyElement');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card.classList.contains('draft-card--failed')).toBe(false);
  });

  it('生成失败 + 已出图 → 仍挂 --failed（失败态与媒体本体并存时状态优先可见）', () => {
    const { container } = setup({
      id: 'd3', label: '设定图 · AA', tag: '生成失败', mediaType: 'image',
      desc: '', prompt: 'p', imgUrl: '/workspace/assets/a.png',
    }, 'keyElement');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card.classList.contains('draft-card--failed')).toBe(true);
    expect(card.classList.contains('draft-card--filled')).toBe(true);
  });
});

describe('视频卡带参考图（有 imgUrl 无 videoUrl）不得两层打架', () => {
  it('有参考图 → 底图铺参考图 + --filled，且不叠加占位符号', () => {
    const { container } = setup({
      id: 'd1', label: '分镜视频 1-1', tag: 'Agent', mediaType: 'video',
      prompt: 'p', videoUrl: '', imgUrl: '/workspace/assets/ref.png',
    }, 'shot');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card.style.backgroundImage).toContain('/workspace/assets/ref.png');
    expect(card.classList.contains('draft-card--filled')).toBe(true);
    expect(container.querySelector('.draft-card-placeholder-icon')).toBeNull();
  });

  it('无参考图无视频 → 虚线边 + 占位符号（真·未生成）', () => {
    const { container } = setup({
      id: 'd2', label: '分镜视频 1-2', tag: 'Agent', mediaType: 'video',
      prompt: 'p', videoUrl: '', imgUrl: '',
    }, 'shot');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card.classList.contains('draft-card--empty')).toBe(true);
    expect(container.querySelector('.draft-card-placeholder-icon')).toBeTruthy();
  });
});

describe('可访问名称：卡面零文字后读屏不得读到空按钮', () => {
  it('有名称的卡 → aria-label 含名称 + 状态', () => {
    const { container } = setup({
      id: 'd1', label: '设定图 · 程心', tag: 'Agent', mediaType: 'image', prompt: 'p', imgUrl: '',
    }, 'keyElement');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card.getAttribute('aria-label')).toBe('设定图 · 程心（未生成）');
  });

  it('已出图 → 状态位为「已生成」', () => {
    const { container } = setup({
      id: 'd2', label: '设定图 · AA', tag: '已生成', mediaType: 'image',
      prompt: 'p', imgUrl: '/workspace/assets/a.png',
    }, 'keyElement');
    expect(container.querySelector('.draft-card')!.getAttribute('aria-label'))
      .toBe('设定图 · AA（已生成）');
  });

  it('生成失败 → 状态位优先报「生成失败」', () => {
    const { container } = setup({
      id: 'd3', label: '设定图 · 曹彬', tag: '生成失败', mediaType: 'image', prompt: 'p', imgUrl: '',
    }, 'keyElement');
    expect(container.querySelector('.draft-card')!.getAttribute('aria-label'))
      .toBe('设定图 · 曹彬（生成失败）');
  });

  it('无名称的卡 → 回落「未命名草稿」，不产出空名称', () => {
    const { container } = setup({
      id: 'd4', label: '', tag: '手动', mediaType: 'image', prompt: 'p', imgUrl: '',
    }, 'keyElement');
    expect(container.querySelector('.draft-card')!.getAttribute('aria-label'))
      .toBe('未命名草稿（未生成）');
  });
});

describe('音频：没音频=广播符号，有音频=现行音符+波形', () => {
  it('未生成音频 → 只有广播符号（is-empty），无波形', () => {
    const { container } = setup({
      id: 'd1', label: '音色 · 程心', mediaType: 'audio', prompt: 'p', audioUrl: '',
    }, 'keyElement');
    const indicator = container.querySelector('.draft-card-audio-indicator') as HTMLElement;
    expect(indicator).toBeTruthy();
    expect(indicator.classList.contains('is-empty')).toBe(true);
    expect(container.querySelector('.draft-card-wave')).toBeNull();
    expectNoCardText(container);
  });

  it('已生成音频 → 音符 + 波形（is-empty 不挂）', () => {
    const { container } = setup({
      id: 'd2', label: '音色 · 程心', mediaType: 'audio',
      prompt: 'p', audioUrl: '/workspace/assets/a.flac',
    }, 'keyElement');
    const indicator = container.querySelector('.draft-card-audio-indicator') as HTMLElement;
    expect(indicator.classList.contains('is-empty')).toBe(false);
    expect(container.querySelector('.draft-card-wave')).toBeTruthy();
    expectNoCardText(container);
  });

  it('关键元素组内的音色卡仍为半尺寸（--voice）且不渲染文字（既有裁决不退化）', () => {
    const { container } = setup({
      id: 'd3', label: '音色 · AA', mediaType: 'audio', prompt: 'p', audioUrl: '',
    }, 'keyElement');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card.classList.contains('draft-card--voice')).toBe(true);
    expectNoCardText(container);
  });

  it('音频 tab 的 BGM 卡不加 --voice，但同样不渲染文字', () => {
    const { container } = setup({
      id: 'd4', label: 'BGM_末日静默', mediaType: 'audio', prompt: 'p', audioUrl: '',
    }, 'audio');
    const card = container.querySelector('.draft-card') as HTMLElement;
    expect(card.classList.contains('draft-card--voice')).toBe(false);
    expectNoCardText(container);
  });
});
