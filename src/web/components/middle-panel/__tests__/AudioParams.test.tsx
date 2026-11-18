/**
 * 音频参数栏 schema 驱动（2026-10-28 参数自适应批）：
 * ① 通道按 audioType 推导；
 * ② 参数来自模型声明的 params（没声明就不渲染）；
 * ③ `when` 条件参数随依赖值显隐；
 * ④ 未知参数类型（number）也能渲染；
 * ⑤ 切通道把模型收敛到该通道可选集；
 * ⑥ 主按钮把通道/供应商/模型作为 overrides 交给生成入口。
 * ⑦ 厂商列表与 API 设置同口径（未接音频的不列出）；切厂商后选模型不回跳。
 */
import { render, cleanup, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { findDraftRecord, setState } from '@/stores/studio';

vi.mock('@/lib/audio-actions', () => ({ generateAudio: vi.fn() }));
vi.mock('@/api/upload', () => ({ uploadFiles: vi.fn() }));
vi.mock('@/api/generate', () => ({ cloneVoice: vi.fn(), listVoices: vi.fn() }));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { generateAudio } from '@/lib/audio-actions';
import { uploadFiles } from '@/api/upload';
import { cloneVoice, listVoices } from '@/api/generate';
import { AudioParams } from '../params/AudioParams';
import type { AudioParamSpec, Draft } from '@/types';

const MUSIC_PARAMS: AudioParamSpec[] = [
  { key: 'lyrics', type: 'text', label: '歌词', channels: ['music'] },
  { key: 'instrumental', type: 'bool', label: '纯音乐', default: true, channels: ['music'] },
  {
    key: 'gender', type: 'enum', label: '演唱性别', values: ['female', 'male'],
    default: 'female', when: 'instrumental=false', channels: ['music'],
  },
  { key: 'format', type: 'enum', label: '输出格式', values: ['mp3', 'wav'], default: 'mp3', channels: ['music'] },
];

const DESIGN_PARAMS: AudioParamSpec[] = [
  {
    key: 'preview_text', type: 'text', label: '试听文本', required: true,
    min_len: 15, max_len: 200, channels: ['voice_design'],
  },
  { key: 'language', type: 'enum', label: '语言', values: ['zh', 'en'], default: 'zh', channels: ['voice_design'] },
  { key: 'format', type: 'enum', label: '输出格式', values: ['wav', 'mp3'], default: 'wav', channels: ['voice_design'] },
];

const PROVIDER = {
  id: 'custom-api-8',
  name: '阿里百炼',
  audio_adapter: 'dashscope',
  audio_models: ['fun-music-v1', 'cosyvoice-v3.5-plus'],
  audio_models_meta: [
    { model: 'fun-music-v1', capabilities: ['music'], params: MUSIC_PARAMS },
    { model: 'cosyvoice-v3.5-plus', capabilities: ['voice_design', 'tts'], params: DESIGN_PARAMS },
  ],
};

const ELEVEN = {
  id: 'custom-api-11',
  name: 'elevenlabs',
  audio_adapter: 'elevenlabs',
  audio_models: ['eleven_flash_v2', 'eleven_v3'],
  audio_models_meta: [
    { model: 'eleven_flash_v2', capabilities: ['tts'], params: [] },
    { model: 'eleven_v3', capabilities: ['tts'], params: [] },
  ],
};

/** 未接音频适配器（腾讯 TokenHub 现状）：音频模型存在，但提交时报「尚未接入」 */
const TENCENT = {
  id: 'custom-api-9',
  name: '腾讯云',
  audio_adapter: '',
  audio_models: ['minimax-speech-2.8-hd'],
  audio_models_meta: [
    { model: 'minimax-speech-2.8-hd', capabilities: ['tts'], params: [] },
  ],
};

function draft(overrides: Partial<Draft>): Draft {
  return {
    id: 'd1', label: '音频', mediaType: 'audio',
    prompt: '末日科幻氛围，低频脉冲 + 弦乐泛音',
    audioProviderId: 'custom-api-8', audioModel: 'fun-music-v1',
    ...overrides,
  };
}

function seed(d: Draft, provider: typeof PROVIDER = PROVIDER) {
  setState('apiProviders', [provider] as never);
  setState('audioItems', [{ id: 'g1', title: 'Audio_BGM', drafts: [d] }] as never);
  setState('selectedType', 'audio');
  setState('selectedDraftId', d.id);
}

function renderPanel(d: Draft) {
  return render(() => <AudioParams draft={d} type="audio" />);
}

beforeEach(() => {
  vi.mocked(generateAudio).mockClear();
  setState({ apiProviders: [], audioItems: [], selectedDraftId: '', selectedType: 'keyElement' });
});
afterEach(() => { cleanup(); });

describe('AudioParams · schema 驱动', () => {
  it('BGM 卡默认「背景音乐」：渲染模型声明的歌词/纯音乐/格式，不渲染试听文本', () => {
    const d = draft({ audioType: 'bgm' });
    seed(d);
    const { container } = renderPanel(d);
    expect((container.querySelector('[aria-label="音频通道"]') as HTMLSelectElement).value)
      .toBe('music');
    expect(container.querySelector('[aria-label="歌词"]')).toBeTruthy();
    expect(container.querySelector('[aria-label="纯音乐"]')).toBeTruthy();
    expect(container.querySelector('[aria-label="输出格式"]')).toBeTruthy();
    expect(container.querySelector('[aria-label="试听文本"]')).toBeNull();
    expect(container.querySelector('.param-actions')!.textContent).toContain('生成背景音乐');
  });

  it('音色卡默认「音色设计」：渲染试听文本，不渲染歌词', () => {
    const d = draft({ audioType: 'voice', audioModel: 'cosyvoice-v3.5-plus' });
    seed(d);
    const { container } = renderPanel(d);
    expect((container.querySelector('[aria-label="音频通道"]') as HTMLSelectElement).value)
      .toBe('voice_design');
    expect(container.querySelector('[aria-label="试听文本"]')).toBeTruthy();
    expect(container.querySelector('[aria-label="歌词"]')).toBeNull();
    expect(container.querySelector('.param-actions')!.textContent).toContain('生成音色');
  });

  it('when 条件参数：纯音乐默认开 → 演唱性别隐藏；草稿为歌曲时 → 出现', () => {
    const bgm = draft({ audioType: 'bgm' });
    seed(bgm);
    const first = renderPanel(bgm);
    expect(first.container.querySelector('[aria-label="演唱性别"]')).toBeNull();
    cleanup();

    const song = draft({ audioType: 'bgm', instrumental: false });
    seed(song);
    const second = renderPanel(song);
    expect(second.container.querySelector('[aria-label="演唱性别"]')).toBeTruthy();
  });

  it('长文本参数（歌词）渲染为多行 textarea 并独占整行', () => {
    const d = draft({ audioType: 'bgm' });
    const provider = {
      ...PROVIDER,
      audio_models_meta: [{
        model: 'fun-music-v1', capabilities: ['music'],
        params: [
          { key: 'lyrics', type: 'text' as const, label: '歌词', multiline: true, max_len: 350 },
          { key: 'format', type: 'enum' as const, label: '输出格式', values: ['mp3'], default: 'mp3' },
        ],
      }],
    };
    seed(d, provider);
    const { container } = renderPanel(d);
    const area = container.querySelector('[aria-label="歌词"]') as HTMLTextAreaElement;
    expect(area.tagName).toBe('TEXTAREA');
    expect(area.closest('.param-group-block')).toBeTruthy();
    expect(container.textContent).toContain('≤350 字');
  });

  it('参考音频参数可上传音频并追加到草稿（声音复刻入口）', async () => {
    vi.mocked(uploadFiles).mockResolvedValue(
      [{ name: 'voice.mp3', kind: 'audio', url: '/workspace/assets/voice.mp3' }] as never,
    );
    const d = draft({ audioType: 'voice', audioModel: 'cosyvoice-v3.5-plus' });
    const provider = {
      ...PROVIDER,
      audio_models_meta: [{
        model: 'cosyvoice-v3.5-plus', capabilities: ['voice_design'],
        params: [
          { key: 'preview_text', type: 'text' as const, label: '试听文本', multiline: true },
          { key: 'refs', type: 'refs' as const, source: 'refs' as const, label: '参考音频' },
        ],
      }],
    };
    seed(d, provider);
    const { container } = render(() => (
      <AudioParams draft={findDraftRecord('d1', 'audio')!.draft} type="audio" />
    ));
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeTruthy();
    const file = new File(['x'], 'voice.mp3', { type: 'audio/mpeg' });
    fireEvent.change(fileInput, { target: { files: [file] } });
    await vi.waitFor(() => {
      expect(findDraftRecord('d1', 'audio')?.draft.refAssets).toContain('/workspace/assets/voice.mp3');
    });
    expect(uploadFiles).toHaveBeenCalledTimes(1);
  });

  it('语音合成音色栏可上传音频生成音色并回填 voice_id', async () => {
    vi.mocked(uploadFiles).mockResolvedValue(
      [{ name: 'voice.mp3', kind: 'audio', url: '/workspace/assets/voice.mp3' }] as never,
    );
    vi.mocked(cloneVoice).mockResolvedValue({
      voice_id: 'cosyvoice-v3.5-plus-vd-clone-1',
      preview_url: '/workspace/assets/clone-preview.wav',
    });
    const d = draft({ audioType: 'narration', audioModel: 'cosyvoice-v3.5-plus' });
    const provider = {
      ...PROVIDER,
      audio_models_meta: [{
        model: 'cosyvoice-v3.5-plus', capabilities: ['tts'],
        params: [{
          key: 'voice_id', type: 'text' as const, label: '音色 ID', required: true, clone: true,
        }],
      }],
    };
    seed(d, provider);
    const { container } = render(() => (
      <AudioParams draft={findDraftRecord('d1', 'audio')!.draft} type="audio" />
    ));
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeTruthy();
    fireEvent.change(fileInput, {
      target: { files: [new File(['x'], 'voice.mp3', { type: 'audio/mpeg' })] },
    });
    await vi.waitFor(() => {
      expect(findDraftRecord('d1', 'audio')?.draft.voiceId)
        .toBe('cosyvoice-v3.5-plus-vd-clone-1');
    });
    expect(cloneVoice).toHaveBeenCalledWith({
      provider_id: 'custom-api-8',
      target_model: 'cosyvoice-v3.5-plus',
      audio_url: '/workspace/assets/voice.mp3',
    });
    const audio = container.querySelector('audio[aria-label="音色试听"]') as HTMLAudioElement;
    expect(audio).toBeTruthy();
    expect(audio.getAttribute('src')).toBe('/workspace/assets/clone-preview.wav');
  });

  it('拉取平台音色：下拉选择回填 voice_id 并试听', async () => {
    vi.mocked(listVoices).mockResolvedValue({
      voices: [
        { voice_id: 'v-1', name: 'Rachel', preview_url: 'https://cdn.example/p.mp3' },
        { voice_id: 'v-2', name: 'Bella' },
      ],
    });
    const d = draft({
      audioType: 'narration', audioProviderId: 'custom-api-11', audioModel: 'eleven_v3',
    });
    const provider = {
      ...ELEVEN,
      audio_models_meta: [{
        model: 'eleven_v3', capabilities: ['tts'],
        params: [{
          key: 'voice_id', type: 'text' as const, label: '音色 ID',
          required: true, list_voices: true,
        }],
      }],
    };
    seed(d, provider);
    const { container } = render(() => (
      <AudioParams draft={findDraftRecord('d1', 'audio')!.draft} type="audio" />
    ));
    const pull = Array.from(container.querySelectorAll('button'))
      .find((b) => (b.textContent || '').includes('拉取音色')) as HTMLButtonElement;
    expect(pull).toBeTruthy();
    fireEvent.click(pull);
    await vi.waitFor(() => {
      expect(listVoices).toHaveBeenCalledWith({
        provider_id: 'custom-api-11', model: 'eleven_v3',
      });
    });
    const select = (await vi.waitFor(() => {
      const el = container.querySelector('[aria-label="平台音色"]');
      expect(el).toBeTruthy();
      return el;
    })) as HTMLSelectElement;
    expect(select.options.length).toBe(3); // 占位 + 2 个音色

    fireEvent.change(select, { target: { value: 'v-1' } });
    expect(findDraftRecord('d1', 'audio')?.draft.voiceId).toBe('v-1');
    const audio = container.querySelector('audio[aria-label="音色试听"]') as HTMLAudioElement;
    expect(audio.getAttribute('src')).toBe('https://cdn.example/p.mp3');

    // 没有 preview_url 的音色：回填 ID，但不留旧试听音频
    fireEvent.change(select, { target: { value: 'v-2' } });
    expect(findDraftRecord('d1', 'audio')?.draft.voiceId).toBe('v-2');
    expect(container.querySelector('audio[aria-label="音色试听"]')).toBeNull();
  });

  it('参数 note 作为说明渲染（音色 ID 怎么填）', () => {
    const d = draft({ audioType: 'narration', audioModel: 'cosyvoice-v3.5-plus' });
    const provider = {
      ...PROVIDER,
      audio_models_meta: [{
        model: 'cosyvoice-v3.5-plus', capabilities: ['tts'],
        params: [{
          key: 'voice_id', type: 'text' as const, label: '音色 ID', required: true,
          note: '百炼：音色设计返回的 voice_id 或系统音色',
        }],
      }],
    };
    seed(d, provider);
    const { container } = renderPanel(d);
    expect(container.querySelector('.param-note')?.textContent).toContain('系统音色');
  });

  it('模型声明了非内置参数（number）也能渲染', () => {
    const d = draft({ audioType: 'bgm' });
    const extra: AudioParamSpec[] = [
      { key: 'steps', type: 'number', label: '步数', min: 1, max: 100, step: 1, default: '30' },
      { key: 'format', type: 'enum', label: '输出格式', values: ['mp3'], default: 'mp3' },
    ];
    const provider = {
      ...PROVIDER,
      audio_models_meta: [{
        model: 'fun-music-v1',
        capabilities: ['music'],
        params: extra,
      }],
    };
    seed(d, provider);
    const { container } = renderPanel(d);
    const input = container.querySelector('[aria-label="步数"]') as HTMLInputElement;
    expect(input).toBeTruthy();
    expect(input.type).toBe('number');
    expect(input.value).toBe('30');
  });

  it('切通道把模型收敛到该通道可选集（music → voice_design）', () => {
    const d = draft({ audioType: 'bgm' });
    seed(d);
    const { container } = renderPanel(d);
    fireEvent.change(container.querySelector('[aria-label="音频通道"]')!, {
      target: { value: 'voice_design' },
    });
    const rec = findDraftRecord('d1', 'audio');
    expect(rec?.draft.audioChannel).toBe('voice_design');
    expect(rec?.draft.audioModel).toBe('cosyvoice-v3.5-plus');
  });

  it('主按钮把通道/供应商/模型作为 overrides 传给生成入口', () => {
    const d = draft({ audioType: 'bgm' });
    seed(d);
    const { container } = renderPanel(d);
    fireEvent.click(container.querySelector('.param-actions button')!);
    expect(generateAudio).toHaveBeenCalledWith({
      channel: 'music', providerId: 'custom-api-8', model: 'fun-music-v1',
    });
  });

  it('参数栏只有生成按钮（「只出规划」已按用户裁决移除）', () => {
    const d = draft({ audioType: 'bgm' });
    seed(d);
    const { container } = renderPanel(d);
    const actions = container.querySelector('.param-actions')!;
    expect(actions.querySelectorAll('button')).toHaveLength(1);
    expect(actions.textContent).not.toContain('只出规划');
  });
});

describe('AudioParams · 供应商口径与联动', () => {
  it('未接音频适配器的厂商不进下拉（与 API 设置同口径）', () => {
    const d = draft({ audioType: 'voice', audioModel: 'cosyvoice-v3.5-plus' });
    setState('apiProviders', [PROVIDER, TENCENT] as never);
    setState('audioItems', [{ id: 'g1', title: 'Audio', drafts: [d] }] as never);
    setState('selectedType', 'audio');
    setState('selectedDraftId', d.id);
    const { container } = render(() => (
      <AudioParams draft={findDraftRecord('d1', 'audio')!.draft} type="audio" />
    ));
    const sel = container.querySelector('[aria-label="音频 API:"]') as HTMLSelectElement;
    expect(Array.from(sel.options).map((o) => o.value)).toEqual(['custom-api-8']);
    expect(sel.textContent).not.toContain('未接音频');
  });

  it('选好厂商后再选模型，厂商下拉与状态都不回跳', () => {
    const d = draft({ audioType: 'narration', audioModel: 'eleven_flash_v2' });
    setState('apiProviders', [PROVIDER, ELEVEN] as never);
    setState('audioItems', [{ id: 'g1', title: 'Audio', drafts: [d] }] as never);
    setState('selectedType', 'audio');
    setState('selectedDraftId', d.id);
    const { container } = render(() => (
      <AudioParams draft={findDraftRecord('d1', 'audio')!.draft} type="audio" />
    ));
    const providerSel = container.querySelector('[aria-label="音频 API:"]') as HTMLSelectElement;
    const modelSel = container.querySelector('[aria-label="音频模型:"]') as HTMLSelectElement;
    fireEvent.change(providerSel, { target: { value: 'custom-api-11' } });
    expect(findDraftRecord('d1', 'audio')?.draft.audioProviderId).toBe('custom-api-11');
    expect(findDraftRecord('d1', 'audio')?.draft.audioModel).toBe('eleven_flash_v2');

    fireEvent.change(modelSel, { target: { value: 'eleven_v3' } });
    expect(providerSel.value).toBe('custom-api-11');
    expect(findDraftRecord('d1', 'audio')?.draft.audioProviderId).toBe('custom-api-11');
    expect(findDraftRecord('d1', 'audio')?.draft.audioModel).toBe('eleven_v3');
  });
});
