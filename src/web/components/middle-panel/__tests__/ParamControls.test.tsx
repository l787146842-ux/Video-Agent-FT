/**
 * ParamControls 分镜生成类型分发（2026-10-20 用户裁决：
 * 分镜面板的卡可以有图片生成和视频生成，分镜表格图要能出）。
 *
 * 钉死：分镜图片卡（Agent 建的 `mediaType=image` 表格图卡，或视频卡切到图片生成）
 * 渲染图片参数栏 + 「生成图片」；分镜视频卡仍渲染视频参数栏 + 「生成视频」。
 * 此前 `selectedType === 'shot'` 无条件走 VideoParams ⇒ 表格图只能被当成视频生成。
 */
import { render, cleanup } from '@solidjs/testing-library';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { setState } from '@/stores/studio';
import { ParamControls } from '../ParamControls';

function seedShotDraft(mediaType: 'image' | 'video', genType?: 'image' | 'video') {
  setState('shots', [{
    id: 'g1', title: 'Shot_1',
    drafts: [{
      id: 'd1', label: '分镜表格图', mediaType, genType, prompt: '故事板表格提示词',
    }],
  }] as never);
  setState('selectedType', 'shot');
  setState('selectedDraftId', 'd1');
}

beforeEach(() => {
  setState({ apiProviders: [], shots: [], selectedDraftId: '', selectedType: 'keyElement' });
});
afterEach(() => { cleanup(); });

describe('ParamControls · 分镜图片/视频生成分发', () => {
  it('分镜图片卡走图片参数栏：出现「生成图片」与图片比例，不出现「生成视频」', () => {
    seedShotDraft('image');
    const { container } = render(() => <ParamControls />);
    const actions = container.querySelector('.param-actions')!;
    expect(actions.textContent).toContain('生成图片');
    expect(actions.textContent).not.toContain('生成视频');
    expect(container.querySelector('[aria-label="图片画面比例"]')).toBeTruthy();
  });

  it('分镜视频卡仍走视频参数栏：出现「生成视频」，不出现「生成图片」', () => {
    seedShotDraft('video');
    const { container } = render(() => <ParamControls />);
    const actions = container.querySelector('.param-actions')!;
    expect(actions.textContent).toContain('生成视频');
    expect(actions.textContent).not.toContain('生成图片');
    expect(container.querySelector('[aria-label="视频生成模式"]')).toBeTruthy();
  });

  it('genType 优先于 mediaType：视频卡切到图片生成后出图片参数栏', () => {
    seedShotDraft('video', 'image');
    const { container } = render(() => <ParamControls />);
    expect(container.querySelector('.param-actions')!.textContent).toContain('生成图片');
    expect(container.querySelector('[aria-label="图片画面比例"]')).toBeTruthy();
  });
});
