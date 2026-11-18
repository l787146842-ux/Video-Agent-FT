/**
 * 音频通道词表（前端口径）。
 *
 * 与后端 `core/audio_channels.py` 同词表；本文件只做「卡片 audioType → 通道」
 * 的默认推导与通道默认参数，不做模型能力推导（那是后端 audio_models_meta 的事）。
 *
 * 用户裁决 2026-10-28：音频只保留四条通道 —— 音色设计 / 语音合成 /
 * 背景音乐 / 音效。Skill 里的 `text_to_instrumental` / `text_to_narration`
 * 两个通道词在平台层映射到本词表，Skill 正文不改（冻结 #16）。
 */
import type { AudioCapability, Draft } from '@/types';

export const AUDIO_CHANNELS: AudioCapability[] = [
  'voice_design', 'tts', 'music', 'sfx',
];

export const AUDIO_CHANNEL_LABELS: Record<AudioCapability, string> = {
  voice_design: '音色设计',
  tts: '语音合成',
  music: '背景音乐',
  sfx: '音效',
};

/** audioType（故事板领域词）→ 音频通道的默认映射（显式 audioChannel 优先） */
const AUDIO_TYPE_CHANNEL: Record<string, AudioCapability> = {
  voice: 'voice_design',
  bgm: 'music',
  sfx: 'sfx',
  foley: 'sfx',
  narration: 'tts',
  dialogue: 'tts',
};

/** 通道默认输出格式（百炼各接口的推荐值） */
export const AUDIO_DEFAULT_FORMAT: Record<AudioCapability, string> = {
  voice_design: 'wav',
  tts: 'wav',
  music: 'mp3',
  sfx: 'wav',
};

/** 通道默认采样率（Hz，字符串便于下拉存储） */
export const AUDIO_DEFAULT_SAMPLE_RATE: Record<AudioCapability, string> = {
  voice_design: '24000',
  tts: '24000',
  music: '48000',
  sfx: '48000',
};

export function isAudioChannel(value: unknown): value is AudioCapability {
  return AUDIO_CHANNELS.includes(String(value || '') as AudioCapability);
}

/**
 * 卡片当前音频通道：显式 `audioChannel` 优先，其次按 `audioType` 推导。
 * 存量卡（无 audioType）默认「背景音乐」——音频页签最常见的产物。
 */
export function audioChannelFor(draft: Draft | undefined): AudioCapability {
  if (!draft) return 'music';
  if (isAudioChannel(draft.audioChannel)) return draft.audioChannel as AudioCapability;
  const byType = AUDIO_TYPE_CHANNEL[String(draft.audioType || '')];
  return byType || 'music';
}

/** 通道默认格式（卡片空值时用于下拉显示，不写回卡） */
export function audioFormatFor(draft: Draft | undefined, channel: AudioCapability): string {
  return String(draft?.audioFormat || '').trim() || AUDIO_DEFAULT_FORMAT[channel];
}

export function audioSampleRateFor(
  draft: Draft | undefined, channel: AudioCapability,
): string {
  return String(draft?.audioSampleRate || '').trim() || AUDIO_DEFAULT_SAMPLE_RATE[channel];
}
