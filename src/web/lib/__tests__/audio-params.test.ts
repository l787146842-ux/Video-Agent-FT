/**
 * 音频参数 schema 消费层单测（2026-10-28 参数自适应批）：
 * 取值优先级（草稿 → schema 默认）、条件显隐、必填/长度/数字校验、
 * 生效值查询、写回 patch 的类型转换。
 */
import { describe, it, expect } from 'vitest';
import {
  audioParamsFor, effectiveAudioParam, isParamVisible,
  paramPatch, resolveParamValue, validateAudioParams,
} from '../audio-params';
import type { AudioParamSpec, Draft } from '@/types';

const DRAFT: Draft = {
  id: 'd1', label: '音频', mediaType: 'audio', prompt: '末日科幻氛围',
  audioProviderId: 'p1', audioModel: 'fun-music-v1', audioType: 'bgm',
};

const SPECS: AudioParamSpec[] = [
  { key: 'lyrics', type: 'text', label: '歌词' },
  { key: 'instrumental', type: 'bool', label: '纯音乐', default: true },
  { key: 'gender', type: 'enum', label: '演唱性别', values: ['female', 'male'], default: 'female', when: 'instrumental=false' },
  { key: 'format', type: 'enum', label: '输出格式', values: ['mp3', 'wav'], default: 'mp3' },
];

describe('resolveParamValue', () => {
  it('草稿字段优先；空值回落 schema 默认', () => {
    expect(resolveParamValue(DRAFT, SPECS[3])).toBe('mp3');
    expect(resolveParamValue({ ...DRAFT, audioFormat: 'wav' }, SPECS[3])).toBe('wav');
  });

  it('bool 的 false 是有效值（不被默认 true 覆盖）', () => {
    expect(resolveParamValue(DRAFT, SPECS[1])).toBe(true);
    expect(resolveParamValue({ ...DRAFT, instrumental: false }, SPECS[1])).toBe(false);
  });

  it('prompt / refs 走特殊来源', () => {
    expect(resolveParamValue(DRAFT, { key: 'prompt', type: 'text', source: 'prompt' }))
      .toBe('末日科幻氛围');
    expect(resolveParamValue({ ...DRAFT, refAssets: ['/a.wav'] },
      { key: 'refs', type: 'refs' })).toEqual(['/a.wav']);
  });
});

describe('isParamVisible', () => {
  it('未声明 when 恒显示；when 不成立时隐藏', () => {
    expect(isParamVisible(SPECS[0], SPECS, DRAFT)).toBe(true);
    expect(isParamVisible(SPECS[2], SPECS, DRAFT)).toBe(false);      // 纯音乐默认开
    expect(isParamVisible(SPECS[2], SPECS, { ...DRAFT, instrumental: false })).toBe(true);
  });
});

describe('validateAudioParams', () => {
  it('必填缺失 / 长度 / 数字范围', () => {
    const required: AudioParamSpec[] = [
      { key: 'preview_text', type: 'text', label: '试听文本', required: true, min_len: 15, max_len: 20 },
    ];
    expect(validateAudioParams(required, DRAFT)).toContain('请填写试听文本');
    expect(validateAudioParams(required, { ...DRAFT, previewText: '太短' })).toContain('至少 15 字');
    expect(validateAudioParams(required, { ...DRAFT, previewText: '字'.repeat(21) })).toContain('最多 20 字');

    const ranged: AudioParamSpec[] = [
      { key: 'volume', type: 'number', label: '音量', min: 0, max: 100 },
    ];
    expect(validateAudioParams(ranged, { ...DRAFT, audioVolume: '120' })).toContain('不能大于 100');
    expect(validateAudioParams(ranged, { ...DRAFT, audioVolume: '50' })).toBeNull();
  });

  it('隐藏参数即使必填也跳过', () => {
    const specs: AudioParamSpec[] = [
      { key: 'instrumental', type: 'bool', default: true },
      { key: 'gender', type: 'enum', label: '演唱性别', values: ['female'], required: true, when: 'instrumental=false' },
    ];
    expect(validateAudioParams(specs, DRAFT)).toBeNull();
    expect(validateAudioParams(specs, { ...DRAFT, instrumental: false })).toContain('请填写演唱性别');
  });
});

describe('audioParamsFor / effectiveAudioParam', () => {
  const providers = [{
    id: 'p1',
    name: 'P1',
    audio_models_meta: [{
      model: 'fun-music-v1',
      capabilities: ['music' as const],
      params: SPECS.map((spec) => ({ ...spec, channels: ['music' as const] })),
    }],
  }];

  it('按通道过滤参数', () => {
    expect(audioParamsFor(providers, 'p1', 'fun-music-v1', 'music')).toHaveLength(4);
    expect(audioParamsFor(providers, 'p1', 'fun-music-v1', 'sfx')).toHaveLength(0);
  });

  it('生效值含 schema 默认', () => {
    expect(effectiveAudioParam(providers, 'p1', 'fun-music-v1', 'music', DRAFT, 'format')).toBe('mp3');
    expect(effectiveAudioParam(providers, 'p1', 'fun-music-v1', 'music', DRAFT, 'unknown')).toBeUndefined();
  });
});

describe('paramPatch', () => {
  it('bool → boolean，其余 → 字符串；未映射参数返回空 patch', () => {
    expect(paramPatch(SPECS[1], 'false')).toEqual({ instrumental: false });
    expect(paramPatch(SPECS[3], 'wav')).toEqual({ audioFormat: 'wav' });
    expect(paramPatch({ key: 'steps', type: 'number' }, '30')).toEqual({});
  });
});
