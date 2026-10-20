/**
 * 拉取模型弹窗：音频分类（新增第四类）。
 * 钉死三件事：上游 audio_models 进「音频」页签、历史存于 chat_models 的语音模型
 * 按上游类型归位（否则存量配置永远挪不进音频表）、应用时写回 audio_models。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi } from 'vitest';
import { FetchModelsModal } from '../settings/FetchModelsModal';
import type { FetchedModels } from '../settings-meta';

const FETCHED: FetchedModels = {
  all: ['MiniMax/speech-02-hd', 'chat-a', 'flux-image', 'veo-video', 'audio-x'],
  image_models: ['flux-image'],
  chat_models: ['chat-a'],
  video_models: ['veo-video'],
  audio_models: ['MiniMax/speech-02-hd', 'audio-x'],
  total: 5,
  protocol: 'openai',
};

const emptyCats = () => ({
  image: new Set<string>(), chat: new Set<string>(), video: new Set<string>(), audio: new Set<string>(),
});

function renderModal(
  savedCats: ReturnType<typeof emptyCats>,
  onApply = vi.fn(),
  data: FetchedModels = FETCHED,
) {
  const onClose = vi.fn();
  const result = render(() => (
    <FetchModelsModal
      fetched={() => data}
      savedCats={() => savedCats}
      onApply={onApply}
      onClose={onClose}
    />
  ));
  return { ...result, onApply, onClose };
}

function tab(container: HTMLElement, label: string): HTMLButtonElement {
  const el = Array.from(container.querySelectorAll<HTMLButtonElement>('.aps-tab'))
    .find((b) => (b.textContent || '').startsWith(label));
  expect(el, `应渲染「${label}」页签`).toBeTruthy();
  return el!;
}

function rows(container: HTMLElement) {
  return Array.from(container.querySelectorAll('.aps-mrow')).map((row) => ({
    cat: row.querySelector('.aps-mcat')?.textContent || '',
    name: row.querySelector('.aps-mname')?.textContent || '',
    box: row.querySelector<HTMLInputElement>('input[type="checkbox"]')!,
  }));
}

describe('FetchModelsModal 音频分类', () => {
  it('上游 audio_models 归入「音频」页签，计数为 0/2', () => {
    const { container } = renderModal(emptyCats());
    expect(tab(container, '音频').textContent).toContain('0/2');

    fireEvent.click(tab(container, '音频'));
    expect(rows(container).map((r) => r.name)).toEqual(['MiniMax/speech-02-hd', 'audio-x']);
    expect(rows(container).every((r) => r.cat === '音频')).toBe(true);
  });

  it('历史存于 chat_models 的语音模型按上游类型归位到音频页签', () => {
    const saved = emptyCats();
    saved.chat.add('MiniMax/speech-02-hd');
    const { container } = renderModal(saved);
    // 已配置 = 默认勾选，故音频页签计数为 1/2
    expect(tab(container, '音频').textContent).toContain('1/2');
    expect(tab(container, 'LLM').textContent).toContain('0/1');

    fireEvent.click(tab(container, '音频'));
    expect(rows(container).map((r) => r.name)).toContain('MiniMax/speech-02-hd');
    fireEvent.click(tab(container, 'LLM'));
    expect(rows(container).map((r) => r.name)).toEqual(['chat-a']);
  });

  it('应用时把勾选的音频模型写回 audio_models，聊天表不再收语音模型', () => {
    const saved = emptyCats();
    saved.chat.add('MiniMax/speech-02-hd');
    const { container, onApply, onClose } = renderModal(saved);

    fireEvent.click(tab(container, '音频'));
    fireEvent.click(rows(container)[1].box); // 追加勾选 audio-x
    fireEvent.click(Array.from(container.querySelectorAll<HTMLButtonElement>('.aps-btn'))
      .find((b) => b.textContent!.includes('应用到模型列表'))!);

    expect(onApply).toHaveBeenCalledWith({
      image: [], chat: [], video: [],
      audio: ['MiniMax/speech-02-hd', 'audio-x'],
    });
    expect(onClose).not.toHaveBeenCalled();
  });
});
