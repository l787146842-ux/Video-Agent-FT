import { Show } from 'solid-js';
import { FiZap } from 'solid-icons/fi';
import { generateImage } from '@/lib/generate-actions';
import {
  ParamGroup, ParamSelect, btnPrimary,
} from './ParamBase';
import { ProviderModelSelects } from './ProviderModelSelects';
import { ExportButton } from './ExportButton';
import { studioActions } from '@/stores/studio';
import type { Draft, DraftType } from '@/types';

const ASPECT_OPTIONS = ['1:1', '16:9', '9:16', '3:4', '4:3', '2:3', '3:2', '21:9', '9:21']
  .map((v) => ({ value: v, label: v }));

/** 空值档「未设置」= 卡上 `aspectRatio` 为空（画幅尚未确认 / 确认后未回填）。
 *
 *  2026-10-27 用户裁决 A（2222 项目取证）：旧实现 `d().aspectRatio || '1:1'` 把空值
 *  伪装成「已选 1:1」，而执行期后端对同一个空值用 `|| "16:9"` 兜底 —— 同一空值被
 *  两处读成两个不同的比例，用户目测参数栏 1:1、出图却不是 1:1，看板自相矛盾。
 *  本档只改**显示口径**：空值如实显示「未设置」，不再伪装任何具体比例；
 *  真实缺省仍归执行期（执行侧口径收敛见 `docs/未清偿债务清单.md` D-30）。
 *  用户显式选任一具体比例照常写回，人工回填通道不受影响。 */
const UNSET_RATIO_OPTION = { value: '', label: '未设置' };

/** 分辨率档位：1K=基准尺寸，2K/4K 按比例放大（尺寸映射见 image-sizes.ts） */
const RESOLUTION_OPTIONS = ['1K', '2K', '4K'].map((v) => ({ value: v, label: v }));

/** 图片参数：API/模型/比例（含自定义宽高）/分辨率 + 保存/生成。
 *  type 决定写回哪个故事板域：关键元素默认 keyElement，分镜表格图 = shot。 */
export function ImageParams(props: { draft: Draft; type?: DraftType }) {
  const d = () => props.draft;
  const draftType = () => props.type || 'keyElement';

  function updateField(patch: Partial<Draft>) {
    studioActions.updateDraftLocal(draftType(), d().id, patch);
  }

  return (
    <>
      <ProviderModelSelects
        kind="image"
        bucket="image"
        providerLabel="图片 API:"
        modelLabel="生成模型:"
        draft={d()}
      />
      <ParamGroup label="图片比例:">
        <ParamSelect
          ariaLabel="图片画面比例"
          value={d().aspectRatio || ''}
          options={[UNSET_RATIO_OPTION, ...ASPECT_OPTIONS, { value: 'custom', label: '自定义' }]}
          onChange={(v) => updateField({ aspectRatio: v })}
        />
      </ParamGroup>
      <ParamGroup label="分辨率:">
        <ParamSelect
          ariaLabel="图片分辨率"
          value={d().imageResolution || '1K'}
          options={RESOLUTION_OPTIONS}
          onChange={(v) => updateField({ imageResolution: v })}
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
