/**
 * 音频参数 schema 的前端消费层（2026-10-28 参数自适应批）。
 *
 * 单一事实源 = 后端 `core/audio_channels.DEFAULT_AUDIO_PARAMS` +
 * `audio_models_meta[].params`（随 /api/providers 下发）。本文件只做三件事：
 * 1. 通用参数名 → 草稿字段映射（`preview_text` → `previewText` …）；
 * 2. 取值/显隐/必填校验；
 * 3. 取“界面当前生效值”（含 schema 默认值），供生成请求使用。
 *
 * 新增厂商只需在 meta 里声明 params，本文件与参数栏组件都不用改。
 */
import type {
  ApiProvider, AudioCapability, AudioParamSpec, Draft,
} from '@/types';

/** 通用参数名 → 草稿字段（prompt / refs 走特殊来源，不在此表） */
export const AUDIO_PARAM_FIELD: Record<string, keyof Draft> = {
  preview_text: 'previewText',
  language: 'audioLanguage',
  sample_rate: 'audioSampleRate',
  format: 'audioFormat',
  voice_id: 'voiceId',
  lyrics: 'lyrics',
  instrumental: 'instrumental',
  gender: 'audioGender',
  watermark: 'audioWatermark',
  channels: 'audioChannels',
  volume: 'audioVolume',
  rate: 'audioRate',
};

/** 某供应商某模型在某通道下声明的参数（按通道过滤；空 = 未声明） */
export function audioParamsFor(
  providers: ApiProvider[],
  providerId: string,
  model: string,
  channel: AudioCapability,
): AudioParamSpec[] {
  const provider = (providers || []).find((p) => p.id === providerId);
  const entry = (provider?.audio_models_meta || []).find((m) => m.model === model);
  return (entry?.params || []).filter(
    (spec) => !spec.channels?.length || spec.channels.includes(channel),
  );
}

/** 参数当前值：草稿字段 → schema 默认值（空串视为未填，允许默认值补位） */
export function resolveParamValue(draft: Draft, spec: AudioParamSpec): unknown {
  if (spec.source === 'prompt') return String(draft.prompt || '').trim();
  if (spec.source === 'refs' || spec.type === 'refs') return draft.refAssets || [];
  const field = AUDIO_PARAM_FIELD[spec.key];
  const raw = field ? (draft as unknown as Record<string, unknown>)[field as string] : undefined;
  if (raw !== undefined && raw !== null && raw !== '') return raw;
  return spec.default;
}

/** 简单显隐条件：只支持 `key=value`（如 `instrumental=false`），不执行任意表达式 */
export function isParamVisible(
  spec: AudioParamSpec,
  params: AudioParamSpec[],
  draft: Draft,
): boolean {
  const when = String(spec.when || '').trim();
  if (!when) return true;
  const m = /^([A-Za-z0-9_]+)\s*=\s*(.+)$/.exec(when);
  if (!m) return true;
  const dep = params.find((p) => p.key === m[1]);
  if (!dep) return true;
  return String(resolveParamValue(draft, dep)) === m[2].trim();
}

/** 写回草稿的 patch（bool → boolean；其余 → 字符串；未映射参数返回空 patch） */
export function paramPatch(spec: AudioParamSpec, value: unknown): Partial<Draft> {
  const field = AUDIO_PARAM_FIELD[spec.key];
  if (!field) return {};
  if (spec.type === 'bool') {
    // 注意：Boolean('false') === true，必须按字符串真值解析
    const on = value === true || value === 1 || String(value).toLowerCase() === 'true';
    return { [field]: on } as Partial<Draft>;
  }
  return { [field]: String(value ?? '') } as Partial<Draft>;
}

/** 必填/长度/数字范围校验（隐藏参数跳过）。返回错误文案，null = 通过 */
export function validateAudioParams(
  params: AudioParamSpec[],
  draft: Draft,
): string | null {
  for (const spec of params) {
    if (!isParamVisible(spec, params, draft)) continue;
    if (spec.source === 'refs' || spec.type === 'refs') continue;
    const label = spec.label || spec.key;
    const value = resolveParamValue(draft, spec);
    const text = value === undefined || value === null ? '' : String(value).trim();
    if (spec.required && !text) return `请填写${label}`;
    if (!text) continue;
    if (spec.min_len != null && text.length < spec.min_len) {
      return `${label}至少 ${spec.min_len} 字（当前 ${text.length} 字）`;
    }
    if (spec.max_len != null && text.length > spec.max_len) {
      return `${label}最多 ${spec.max_len} 字（当前 ${text.length} 字）`;
    }
    if (spec.type === 'number') {
      const num = Number(text);
      if (Number.isNaN(num)) return `${label}需为数字`;
      if (spec.min != null && num < spec.min) return `${label}不能小于 ${spec.min}`;
      if (spec.max != null && num > spec.max) return `${label}不能大于 ${spec.max}`;
    }
  }
  return null;
}

/** 界面当前生效值（含 schema 默认值）；无声明返回 undefined，调用方回落旧默认 */
export function effectiveAudioParam(
  providers: ApiProvider[],
  providerId: string,
  model: string,
  channel: AudioCapability,
  draft: Draft,
  key: string,
): unknown {
  const spec = audioParamsFor(providers, providerId, model, channel)
    .find((item) => item.key === key);
  return spec ? resolveParamValue(draft, spec) : undefined;
}
