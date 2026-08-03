/** rich-input 富文本工具测试：序列化 / 占位符 / 草稿转内联媒体 */
import { describe, it, expect } from 'vitest';
import {
  serializeEditorToParts, partsToPlainText, mediaPlaceholder,
  draftToInlineMedia, createMediaChip, insertNodeAtCursor, INLINE_MEDIA_CLASS,
} from '../rich-input';
import type { Draft, RichContentPart } from '@/types';

function makeEditor(): HTMLDivElement {
  const el = document.createElement('div');
  document.body.appendChild(el);
  return el;
}

function makeChip(kind: string, url: string, name: string): HTMLSpanElement {
  const chip = document.createElement('span');
  chip.className = INLINE_MEDIA_CLASS;
  chip.dataset.kind = kind;
  chip.dataset.url = url;
  chip.dataset.name = name;
  return chip;
}

describe('partsToPlainText', () => {
  it('文字原样、媒体转占位符', () => {
    const parts: RichContentPart[] = [
      { type: 'text', text: '请看' },
      { type: 'image', url: '/a.png', name: '图A' },
      { type: 'text', text: '和' },
      { type: 'video', url: '/v.mp4', name: '视频B' },
      { type: 'audio', url: '/a.mp3', name: '音频C' },
    ];
    expect(partsToPlainText(parts)).toBe('请看[图片:图A]和[视频:视频B][音频:音频C]');
  });
});

describe('mediaPlaceholder', () => {
  it('按类型生成中文占位符', () => {
    expect(mediaPlaceholder('image', 'x')).toBe('[图片:x]');
    expect(mediaPlaceholder('video', 'y')).toBe('[视频:y]');
    expect(mediaPlaceholder('audio', 'z')).toBe('[音频:z]');
  });
});

describe('serializeEditorToParts', () => {
  it('纯文本 → 单个 text part（去首尾空白）', () => {
    const el = makeEditor();
    el.textContent = '  你好 Agent  ';
    expect(serializeEditorToParts(el)).toEqual([{ type: 'text', text: '你好 Agent' }]);
  });

  it('文字 + 缩略块交错 → 有序 parts', () => {
    const el = makeEditor();
    el.appendChild(document.createTextNode('前文 '));
    el.appendChild(makeChip('image', '/workspace/a.png', '元素A'));
    el.appendChild(document.createTextNode(' 后文'));
    expect(serializeEditorToParts(el)).toEqual([
      { type: 'text', text: '前文' },
      { type: 'image', url: '/workspace/a.png', name: '元素A' },
      { type: 'text', text: '后文' },
    ]);
  });

  it('空编辑器 → 空数组', () => {
    const el = makeEditor();
    expect(serializeEditorToParts(el)).toEqual([]);
  });

  it('无 url 的缩略块被丢弃', () => {
    const el = makeEditor();
    el.appendChild(makeChip('image', '', '坏图'));
    el.appendChild(document.createTextNode('文字'));
    expect(serializeEditorToParts(el)).toEqual([{ type: 'text', text: '文字' }]);
  });
});

describe('insertNodeAtCursor（无光标回退到末尾）', () => {
  it('追加节点到末尾', () => {
    const el = makeEditor();
    el.textContent = '已有文字';
    const chip = makeChip('video', '/v.mp4', '视频');
    insertNodeAtCursor(el, chip);
    const parts = serializeEditorToParts(el);
    expect(parts[parts.length - 1]).toEqual({ type: 'video', url: '/v.mp4', name: '视频' });
  });

  it('传入 savedRange 时插在记忆光标处（而非开头/末尾）', () => {
    const el = makeEditor();
    el.textContent = 'Hello world';
    const textNode = el.firstChild as Text;
    // 记忆光标："Hello" 与 " world" 之间（偏移 5）
    const saved = document.createRange();
    saved.setStart(textNode, 5);
    saved.collapse(true);
    const chip = makeChip('image', '/a.png', '图');
    insertNodeAtCursor(el, chip, saved);
    const parts = serializeEditorToParts(el);
    expect(parts).toEqual([
      { type: 'text', text: 'Hello' },
      { type: 'image', url: '/a.png', name: '图' },
      { type: 'text', text: 'world' },
    ]);
  });
});

describe('createMediaChip', () => {
  it('图片块含 img 与元数据，且不带文字标签', () => {
    const chip = createMediaChip({ id: 'i1', name: '图', url: '/a.png', kind: 'image', thumb: '/a.png' });
    expect(chip.classList.contains(INLINE_MEDIA_CLASS)).toBe(true);
    expect(chip.dataset.kind).toBe('image');
    expect(chip.dataset.url).toBe('/a.png');
    expect(chip.querySelector('img')).not.toBeNull();
    // 只显示媒体本身，无文字名称标签
    expect(chip.querySelector('.inline-media-name')).toBeNull();
    expect(chip.title).toBe('图');
  });

  it('视频块：有海报图时用 img，并携带 thumb 元数据', () => {
    const chip = createMediaChip({ id: 'i2', name: '视频', url: '/v.mp4', kind: 'video', thumb: '/poster.png' });
    expect(chip.querySelector('img')).not.toBeNull();
    expect(chip.querySelector('video')).toBeNull();
    expect(chip.dataset.thumb).toBe('/poster.png');
  });

  it('视频块：无海报图时用 video 首帧', () => {
    const chip = createMediaChip({ id: 'i3', name: '视频', url: '/v.mp4', kind: 'video' });
    expect(chip.querySelector('video')).not.toBeNull();
  });

  it('音频块含音符图标', () => {
    const chip = createMediaChip({ id: 'i4', name: '音', url: '/a.mp3', kind: 'audio' });
    expect(chip.querySelector('.inline-media-audio')).not.toBeNull();
  });
});

describe('serializeEditorToParts 视频携带 thumb', () => {
  it('视频缩略块序列化出 thumb（供后端注入首帧）', () => {
    const el = makeEditor();
    const chip = makeChip('video', '/v.mp4', '视频');
    chip.dataset.thumb = '/poster.png';
    el.appendChild(chip);
    expect(serializeEditorToParts(el)).toEqual([
      { type: 'video', url: '/v.mp4', name: '视频', thumb: '/poster.png' },
    ]);
  });
});

describe('draftToInlineMedia', () => {
  const base = { id: 'd1', label: '草稿', mediaType: 'image' } as Draft;

  it('图片草稿（有 imgUrl）→ image 媒体', () => {
    const m = draftToInlineMedia({ ...base, imgUrl: '/x.png' });
    expect(m?.kind).toBe('image');
    expect(m?.url).toBe('/x.png');
  });

  it('picsum 占位图 → null', () => {
    expect(draftToInlineMedia({ ...base, imgUrl: 'https://picsum.photos/1' })).toBeNull();
  });

  it('视频草稿（有 videoUrl）→ video 媒体；imgUrl 为图片时作为 thumb', () => {
    const m = draftToInlineMedia({ ...base, mediaType: 'video', videoUrl: '/v.mp4', imgUrl: '/p.png' });
    expect(m?.kind).toBe('video');
    expect(m?.url).toBe('/v.mp4');
    expect(m?.thumb).toBe('/p.png');
  });

  it('视频草稿：imgUrl 非图片时 thumb 留空', () => {
    const m = draftToInlineMedia({ ...base, mediaType: 'video', videoUrl: '/v.mp4', imgUrl: '' });
    expect(m?.thumb).toBe('');
  });

  it('音频草稿（有 audioUrl）→ audio 媒体', () => {
    const m = draftToInlineMedia({ ...base, mediaType: 'audio', audioUrl: '/a.mp3' });
    expect(m?.kind).toBe('audio');
  });

  it('空卡片（无媒体）→ null', () => {
    expect(draftToInlineMedia({ ...base, mediaType: 'video', videoUrl: '' })).toBeNull();
  });
});
