/**
 * 音频生成入口（音色设计 / 语音合成 / 背景音乐 / 音效）。
 *
 * 与图片/视频同构：提交 /api/generate/audio → registerManualTask（全局事件总线
 * 跳过，自行轮询写回）→ pollAndPreviewAudio 写回 audioUrl（音色设计额外写 voiceId）。
 *
 * 提示词来源：卡片 prompt 优先；为空时回落组级 desc（设计阶段音频组只有 desc、
 * 没有卡时的唯一事实源），音色卡额外允许回落自身 desc（声音特征）。
 *
 * 设计期音频组只有 desc 没有卡（2026-09-25 裁决）：参数栏用代理 draft 承载选择，
 * 点「生成」时才建承接卡；代理上选的通道/供应商/模型经 overrides 传入并烙进新卡。
 */
import { state, findDraftRecord, studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { submitAudioTask } from '@/api/generate';
import { registerManualTask } from '@/lib/generation-events';
import { patchDraft, pollAndPreviewAudio } from '@/lib/generate-polling';
import {
  audioChannelFor, audioFormatFor, audioSampleRateFor,
} from '@/lib/audio-channel';
import {
  audioParamsFor, effectiveAudioParam, validateAudioParams,
} from '@/lib/audio-params';
import { audioModelsFor, audioProvidersFor } from '@/lib/providers';
import { normalizeDisplayTitle } from '@/lib/desc-ref-utils';
import type { AnyGroup, AudioCapability, Draft, DraftType } from '@/types';

/** 参数栏代理 draft 上的选择（生成时烙进新建的承接卡） */
export interface AudioGenOverrides {
  channel?: AudioCapability;
  providerId?: string;
  model?: string;
}

interface AudioTarget {
  draft: Draft;
  draftType: DraftType;
  groupDesc: string;
}

function groupDescOf(group: AnyGroup | undefined): string {
  const g = group as { desc?: string; prompt?: string } | undefined;
  return String(g?.desc || g?.prompt || '').trim();
}

/** 通道下第一个可用的 (provider, model)；无则 ("", "")（不臆造）。
 *  只在已接适配器的厂商里选：未接的厂商建卡也只会在提交时报错。 */
function firstAvailableFor(channel: AudioCapability): { pid: string; model: string } {
  const p = audioProvidersFor(channel)[0];
  if (!p) return { pid: '', model: '' };
  return { pid: p.id, model: audioModelsFor(p.id, channel)[0] || '' };
}

/** 当前选中卡；音频页签下组内无卡时按 overrides 建承接卡（先校验再建，避免空卡） */
function resolveTarget(overrides?: AudioGenOverrides): AudioTarget | null {
  const rec = findDraftRecord(state.selectedDraftId, state.selectedType);
  if (rec?.type === 'audio') {
    return { draft: rec.draft, draftType: 'audio', groupDesc: groupDescOf(rec.group) };
  }
  if (rec?.draft?.mediaType === 'audio') {
    return { draft: rec.draft, draftType: rec.type, groupDesc: groupDescOf(rec.group) };
  }
  if (state.selectedType !== 'audio' && state.subTab !== 'audio') return null;
  const group = (state.audioItems || [])[0] as AnyGroup | undefined;
  if (!group) return null;

  const channel = overrides?.channel || 'music';
  const fallback = firstAvailableFor(channel);
  const pid = String(overrides?.providerId || '').trim() || fallback.pid;
  const model = String(overrides?.model || '').trim() || fallback.model;
  if (!pid || !model) {
    showToast(`没有可用的${channel === 'music' ? '背景音乐' : '音频'}模型，请先到「设置 → API 配置 → 音频模型」添加`, 'warning');
    return null;
  }
  const label = normalizeDisplayTitle(String(group.title || '音频'));
  const newId = studioActions.addDraftLocalWith('audio', group.id, {
    label, tag: '', mediaType: 'audio', audioType: 'bgm',
    audioChannel: channel, audioProviderId: pid, audioModel: model,
  });
  const created = findDraftRecord(newId, 'audio');
  if (!created) return null;
  showToast(`已新建音频卡（${pid} / ${model}），可在参数栏调整后重试`, 'info');
  return { draft: created.draft, draftType: 'audio', groupDesc: groupDescOf(group) };
}

/** 提示词来源：卡 prompt → 音色卡自身 desc → 组级 desc（按通道优先级） */
function promptFor(draft: Draft, channel: AudioCapability, groupDesc: string): string {
  const own = String(draft.prompt || '').trim();
  if (own) return own;
  if (channel === 'voice_design') {
    return String(draft.desc || '').trim() || groupDesc;
  }
  return groupDesc || String(draft.desc || '').trim();
}

/** 生成前的本地校验：schema 声明优先，旧响应（无 params）回落原硬校验 */
function validate(draft: Draft, channel: AudioCapability, prompt: string): boolean {
  if (!draft.audioProviderId || !draft.audioModel) {
    showToast('请先选择音频 API 和对应模型', 'warning');
    return false;
  }
  const params = audioParamsFor(
    state.apiProviders, draft.audioProviderId, draft.audioModel, channel);
  // prompt 的“生效值”含组 desc 回落（promptFor），校验用同一口径
  const schemaError = validateAudioParams(params, { ...draft, prompt });
  if (schemaError) {
    showToast(schemaError, 'warning');
    return false;
  }
  if (!params.length) {
    // 旧响应兜底（新版本后端总会下发 params，此处只防缓存/第三方数据）
    if (!prompt) {
      showToast('提示词为空：请在提示词框写音频描述，或在音频组 desc 写层设计', 'warning');
      return false;
    }
    if (channel === 'voice_design') {
      const preview = String(draft.previewText || '').trim();
      if (preview.length < 15 || preview.length > 200) {
        showToast('试听文本需 15-200 字（音色设计的必填参数）', 'warning');
        return false;
      }
    }
    if (channel === 'tts' && !String(draft.voiceId || '').trim()) {
      showToast('语音合成需要音色：请先完成音色设计，或在参数栏填写 voice_id', 'warning');
      return false;
    }
  }
  if (channel === 'music' && !prompt && !String(draft.lyrics || '').trim()) {
    showToast('背景音乐需要音乐描述或歌词（至少一项）', 'warning');
    return false;
  }
  return true;
}

export async function generateAudio(overrides?: AudioGenOverrides): Promise<void> {
  const target = resolveTarget(overrides);
  if (!target) {
    if (state.selectedType !== 'audio' && state.subTab !== 'audio') {
      showToast('请在左侧「音频」页签选中一个音频组或音频卡', 'warning');
    }
    return;
  }
  const { draft, draftType, groupDesc } = target;
  const channel = audioChannelFor(draft);
  const prompt = promptFor(draft, channel, groupDesc);
  if (!validate(draft, channel, prompt)) return;

  const pid = draft.audioProviderId || '';
  const model = draft.audioModel || '';
  /** 界面当前生效值：schema 默认值优先，无声明才回落通道默认 */
  const eff = (key: string) => effectiveAudioParam(
    state.apiProviders, pid, model, channel, draft, key);
  const fmt = String(eff('format') || audioFormatFor(draft, channel));
  const sampleRate = Number(eff('sample_rate') || audioSampleRateFor(draft, channel)) || 24000;
  const instrumental = eff('instrumental') !== false;
  const lyrics = String(eff('lyrics') ?? '');
  showToast('正在提交音频生成任务...', 'info');
  try {
    const data = await submitAudioTask({
      channel,
      prompt,
      provider_id: pid,
      model,
      preview_text: String(eff('preview_text') ?? draft.previewText ?? ''),
      language: String(eff('language') || draft.audioLanguage
        || (channel === 'tts' ? 'Auto' : 'zh')),
      sample_rate: sampleRate,
      audio_format: fmt,
      voice_id: String(eff('voice_id') || draft.voiceId || ''),
      lyrics,
      instrumental,
      gender: instrumental ? '' : String(eff('gender') || ''),
      watermark: Boolean(eff('watermark')),
      references: (draft.refAssets || []).map((url) => ({ url })),
      channels: Number(eff('channels') || draft.audioChannels || 2),
      volume: Number(eff('volume') || draft.audioVolume || 50),
      rate: Number(eff('rate') || draft.audioRate || 1),
      draft_id: draft.id,
      draft_type: draftType,
    });
    if (data.task_id) {
      registerManualTask(data.task_id);
      studioActions.startGeneration(draft.id, 'audio');
      patchDraft(draft.id, draftType, { genType: 'audio', mediaType: 'audio', tag: '生成中' });
      void pollAndPreviewAudio(data.task_id, draft.id);
    } else if (data.audio_url) {
      patchDraft(draft.id, draftType, {
        mediaType: 'audio', genType: 'audio', audioUrl: data.audio_url,
        imgUrl: '', videoUrl: '', tag: '已生成',
      });
      showToast('音频已生成！', 'success');
    } else {
      showToast('音频任务已提交', 'info');
    }
  } catch (err) {
    showToast((err as Error).message || '音频生成失败，请检查音频 API 配置', 'error');
  }
}
