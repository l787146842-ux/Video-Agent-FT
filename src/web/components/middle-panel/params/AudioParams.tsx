import { FiMusic } from 'solid-icons/fi';
import { generateAudio } from '@/lib/generate-actions';
import { studioActions } from '@/stores/studio';
import {
  ParamGroup, ParamSelect, ProviderModelSelects, btnPrimary,
} from './ParamBase';
import type { Draft, DraftType } from '@/types';

/** 音频参数：模式/规划 API/模型/音色 + 生成规划 */
export function AudioParams(props: { draft: Draft; type?: DraftType }) {
  const d = () => props.draft;
  // 草稿所属类型：音频层默认 audio，关键元素下生成音频时为 keyElement
  const draftType = () => props.type || 'audio';

  function updateField(patch: Partial<Draft>) {
    studioActions.updateDraftLocal(draftType(), d().id, patch);
  }

  return (
    <>
      <ParamGroup label="生成模式:">
        <ParamSelect
          ariaLabel="音频生成模式"
          value={d().audioMode || d().mode || '多模态音频生成'}
          options={['多模态音频生成', '旁白语音合成'].map((v) => ({ value: v, label: v }))}
          onChange={(v) => updateField({ audioMode: v })}
        />
      </ParamGroup>
      <ProviderModelSelects
        kind="chat"
        bucket="audio"
        providerLabel="规划 API:"
        modelLabel="规划模型:"
        draft={d()}
      />
      <ParamGroup label="音色选择:">
        <ParamSelect
          ariaLabel="音频音色"
          value={d().timbre || '深邃男声 (Deep Narrator)'}
          options={['深邃男声 (Deep Narrator)', '冷酷女声 (AI Core Voice)']
            .map((v) => ({ value: v, label: v }))}
          onChange={(v) => updateField({ timbre: v })}
        />
      </ParamGroup>
      <button
        type="button"
        class={`${btnPrimary} btn-emerald`}
        onClick={() => void generateAudio()}
      >
        <FiMusic size={13} /> 生成音频规划
      </button>
    </>
  );
}
