import { FiFilm } from 'solid-icons/fi';
import { generateVideo } from '@/lib/generate-actions';
import { studioActions } from '@/stores/studio';
import {
  ParamGroup, ParamSelect, ProviderModelSelects,
  btnPrimary, ExportButton,
} from './ParamBase';
import type { Draft, DraftType } from '@/types';

/** 视频参数：模式/API/模型/分辨率/时长/画幅 + 保存/生成 */
export function VideoParams(props: { draft: Draft; type?: DraftType }) {
  const d = () => props.draft;
  // 草稿所属类型：分镜默认 shot，关键元素下生成视频时为 keyElement
  const draftType = () => props.type || 'shot';

  function update(patch: Partial<Draft>) {
    studioActions.updateDraftLocal(draftType(), d().id, patch);
  }

  return (
    <>
      <ParamGroup label="模式拉框:">
        <ParamSelect
          ariaLabel="视频生成模式"
          value={d().mode || '全能参考'}
          options={[
            { value: '全能参考', label: '全能参考' },
            { value: '图生视频', label: '图生视频', disabled: true },
            { value: '首尾帧生视频', label: '首尾帧生视频', disabled: true },
            { value: '对口型数字人', label: '对口型数字人', disabled: true },
          ]}
          onChange={(v) => update({ mode: v })}
        />
      </ParamGroup>
      <ProviderModelSelects
        kind="video"
        providerLabel="视频 API:"
        modelLabel="视频模型:"
        draft={d()}
      />
      <ParamGroup label="分辨率:">
        <ParamSelect
          ariaLabel="视频分辨率"
          value={d().resolution || '1080p'}
          options={['480p', '720p', '1080p'].map((v) => ({ value: v, label: v }))}
          onChange={(v) => update({ resolution: v })}
        />
      </ParamGroup>
      <ParamGroup label="时长:">
        <input
          class="param-select custom-ratio-input"
          type="number"
          min="1"
          max="300"
          aria-label="视频时长（秒）"
          value={d().duration?.replace(/s$/i, '') || '5'}
          onChange={(e) => update({ duration: e.currentTarget.value })}
        />
        <span class="param-unit">秒</span>
      </ParamGroup>
      <ParamGroup label="画幅比例:">
        <ParamSelect
          ariaLabel="视频画幅比例"
          value={d().aspectRatio || '16:9'}
          options={['16:9', '9:16', '1:1', '21:9'].map((v) => ({ value: v, label: v }))}
          onChange={(v) => update({ aspectRatio: v })}
        />
      </ParamGroup>
      <div class="param-actions">
        <ExportButton />
        <button
          type="button"
          class={`${btnPrimary} btn-purple`}
          onClick={() => void generateVideo()}
        >
          <FiFilm size={13} /> 生成视频
        </button>
      </div>
    </>
  );
}
