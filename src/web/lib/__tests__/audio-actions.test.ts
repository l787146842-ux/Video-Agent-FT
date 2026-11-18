/**
 * 音频生成入口（2026-10-28 M1-M3）：
 * ① 卡片 prompt 为空时回落音频组 desc（设计期唯一事实源）；
 * ② 音频页签无卡时按 overrides 建承接卡并烙通道/供应商/模型；
 * ③ 音色设计缺试听文本 → 本地拦截，不发请求；
 * ④ 提交成功后登记手动任务并进入轮询写回。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

vi.mock('@/api/generate', () => ({ submitAudioTask: vi.fn() }));
vi.mock('@/lib/generation-events', () => ({ registerManualTask: vi.fn() }));
vi.mock('@/lib/generate-polling', () => ({
  patchDraft: vi.fn(),
  pollAndPreviewAudio: vi.fn(async () => undefined),
}));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { submitAudioTask } from '@/api/generate';
import { registerManualTask } from '@/lib/generation-events';
import { pollAndPreviewAudio } from '@/lib/generate-polling';
import { showToast } from '@/stores/toast';
import { state, setState } from '@/stores/studio';
import { generateAudio } from '../audio-actions';
import type { Draft } from '@/types';

const MUSIC_PARAMS = [
  { key: 'lyrics', type: 'text', label: '歌词', channels: ['music'] },
  { key: 'instrumental', type: 'bool', label: '纯音乐', default: true, channels: ['music'] },
  {
    key: 'gender', type: 'enum', label: '演唱性别', values: ['female', 'male'],
    default: 'female', when: 'instrumental=false', channels: ['music'],
  },
  { key: 'format', type: 'enum', label: '输出格式', values: ['mp3', 'wav'], default: 'mp3', channels: ['music'] },
];

// 同一模型跨通道：真实响应是一条 meta（能力并集 + params 各自带 channels）
const VOICE_PARAMS = [
  { key: 'prompt', type: 'text', source: 'prompt', required: true, max_len: 500, channels: ['voice_design'] },
  { key: 'preview_text', type: 'text', label: '试听文本', required: true, min_len: 15, max_len: 200, channels: ['voice_design'] },
  { key: 'format', type: 'enum', label: '输出格式', values: ['wav', 'mp3'], default: 'wav', channels: ['voice_design'] },
  { key: 'prompt', type: 'text', source: 'prompt', required: true, channels: ['tts'] },
  { key: 'voice_id', type: 'text', label: '音色 ID', required: true, channels: ['tts'] },
  { key: 'format', type: 'enum', label: '输出格式', values: ['wav', 'mp3'], default: 'wav', channels: ['tts'] },
];

const PROVIDER = {
  id: 'custom-api-8',
  name: '阿里百炼',
  audio_models: ['fun-music-v1', 'cosyvoice-v3.5-plus'],
  audio_models_meta: [
    { model: 'fun-music-v1', capabilities: ['music'], params: MUSIC_PARAMS },
    { model: 'cosyvoice-v3.5-plus', capabilities: ['voice_design', 'tts'], params: VOICE_PARAMS },
  ],
};

function baseDraft(overrides: Partial<Draft> = {}): Draft {
  return {
    id: 'd1', label: 'BGM', mediaType: 'audio', audioType: 'bgm',
    prompt: '', audioProviderId: 'custom-api-8', audioModel: 'fun-music-v1',
    ...overrides,
  };
}

function seed(drafts: Draft[], desc = '末日科幻，低频脉冲 + 弦乐泛音') {
  setState('apiProviders', [PROVIDER] as never);
  setState('audioItems', [{ id: 'g1', title: 'Audio_BGM', desc, drafts }] as never);
  setState('selectedType', 'audio');
  setState('subTab', 'audio');
  setState('selectedDraftId', drafts[0]?.id || '');
}

beforeEach(() => {
  vi.mocked(submitAudioTask).mockReset();
  vi.mocked(submitAudioTask).mockResolvedValue({ task_id: 'aud-1', status: 'processing' });
  vi.mocked(registerManualTask).mockClear();
  vi.mocked(pollAndPreviewAudio).mockClear();
  vi.mocked(showToast).mockClear();
  setState({
    apiProviders: [], audioItems: [], selectedDraftId: '', selectedType: 'keyElement', subTab: 'keyElements',
  });
});
afterEach(() => { vi.useRealTimers(); });

describe('generateAudio', () => {
  it('卡片 prompt 为空 → 用音频组 desc 作为音乐提示词提交', async () => {
    seed([baseDraft()]);
    await generateAudio();
    const body = vi.mocked(submitAudioTask).mock.calls[0][0];
    expect(body.channel).toBe('music');
    expect(body.prompt).toContain('末日科幻');
    expect(body.provider_id).toBe('custom-api-8');
    expect(body.model).toBe('fun-music-v1');
    expect(body.instrumental).toBe(true);
    expect(body.gender).toBe('');
    expect(body.audio_format).toBe('mp3');
    expect(registerManualTask).toHaveBeenCalledWith('aud-1');
    expect(pollAndPreviewAudio).toHaveBeenCalledWith('aud-1', 'd1');
  });

  it('音频组无卡 → 建承接卡并烙 overrides 的通道/供应商/模型', async () => {
    seed([]);
    await generateAudio({ channel: 'voice_design', providerId: 'custom-api-8', model: 'cosyvoice-v3.5-plus' });
    const group = state.audioItems[0] as { drafts: Draft[] };
    expect(group.drafts).toHaveLength(1);
    expect(group.drafts[0]).toMatchObject({
      mediaType: 'audio',
      audioChannel: 'voice_design',
      audioProviderId: 'custom-api-8',
      audioModel: 'cosyvoice-v3.5-plus',
    });
    // 音色设计缺试听文本 → 本地拦截（不把必填缺失发到上游）
    expect(submitAudioTask).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('试听文本'), 'warning');
  });

  it('音色设计带试听文本 → 提交 voice_design 通道', async () => {
    seed([baseDraft({
      audioType: 'voice', audioChannel: 'voice_design',
      audioModel: 'cosyvoice-v3.5-plus',
      prompt: '沉稳的中年男性，音色低沉浑厚',
      previewText: '各位听众朋友们大家好，欢迎收听本期节目',
    })]);
    await generateAudio();
    const body = vi.mocked(submitAudioTask).mock.calls[0][0];
    expect(body.channel).toBe('voice_design');
    expect(body.preview_text).toContain('各位听众');
    expect(body.audio_format).toBe('wav');
  });

  it('语音合成缺 voice_id → 本地拦截', async () => {
    seed([baseDraft({
      audioType: 'narration', audioChannel: 'tts',
      audioModel: 'cosyvoice-v3.5-plus', prompt: '旁白台词',
    })]);
    await generateAudio();
    expect(submitAudioTask).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('音色'), 'warning');
  });
});
