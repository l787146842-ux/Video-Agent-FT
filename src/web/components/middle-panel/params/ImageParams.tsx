import { Show } from 'solid-js';
import { FiZap } from 'solid-icons/fi';
import { generateImage } from '@/lib/generate-actions';
import {
  ParamGroup, ParamSelect, ProviderModelSelects,
  btnPrimary, ExportButton, persistParams,
} from './ParamBase';
import { state, studioActions } from '@/stores/studio';
import type { Draft } from '@/types';

const ASPECT_OPTIONS = ['1:1', '16:9', '9:16', '3:4', '4:3', '2:3', '3:2', '21:9', '9:21']
  .map((v) => ({ value: v, label: v }));

/** 图片参数：API/模型/比例（含自定义宽高）+ 保存/生成 */
export function ImageParams(props: { draft: Draft }) {
  const d = () => props.draft;

  function updateField(patch: Partial<Draft>) {
    studioActions.updateDraftLocal('keyElement', d().id, patch);
  }

  return (
    <>
      <ProviderModelSelects
        kind="image"
        providerLabel="图片 API:"
        modelLabel="生成模型:"
        draft={d()}
      />
      <ParamGroup label="图片比例:">
        <ParamSelect
          ariaLabel="图片画面比例"
          value={d().aspectRatio || '1:1'}
          options={[...ASPECT_OPTIONS, { value: 'custom', label: '自定义' }]}
          onChange={(v) => updateField({ aspectRatio: v })}
        />
      </ParamGroup>
      <Show when={d().aspectRatio === 'custom'}>
        <ParamGroup label="自定义:">
          <input
            class="custom-ratio-input"
            type="number" min="1" step="1"
            aria-label="自定义比例宽"
            value={d().customRatioWidth || '4'}
            onInput={(e) => updateField({ customRatioWidth: e.currentTarget.value })}
          />
          <span class="param-sep">:</span>
          <input
            class="custom-ratio-input"
            type="number" min="1" step="1"
            aria-label="自定义比例高"
            value={d().customRatioHeight || '3'}
            onInput={(e) => updateField({ customRatioHeight: e.currentTarget.value })}
          />
        </ParamGroup>
      </Show>
      <div class="param-actions">
        <ExportButton />
        <button
          type="button"
          class={btnPrimary}
          onClick={() => void generateImage()}
        >
          <FiZap size={13} /> 生成图片
        </button>
      </div>
    </>
  );
}
