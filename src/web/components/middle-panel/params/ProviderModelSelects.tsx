/**
 * 供应商 + 模型联动下拉（切供应商时模型重置为该供应商首项）
 * ——自 ParamBase 切出，行为零变更。
 * kind 决定供应商/模型列表来源；bucket 决定读写字段归属
 * （音频面板 kind='chat'、bucket='audio'）。
 */
import { state, studioActions } from '@/stores/studio';
import { apiProvidersFor, providerModels } from '@/lib/providers';
import type { Draft, DraftType } from '@/types';
import { ParamGroup, ParamSelect } from './ParamBase';

/** 按种类参数字段名映射（2026-08-15 参数隔离）：三个生成器各自读写本种类 provider/model */
const BUCKET_PROVIDER_FIELD = {
  image: 'imageProviderId', video: 'videoProviderId', audio: 'audioProviderId',
} as const;
const BUCKET_MODEL_FIELD = {
  image: 'imageModel', video: 'videoModel', audio: 'audioModel',
} as const;

export function ProviderModelSelects(props: {
  kind: 'image' | 'video' | 'chat';
  bucket: 'image' | 'video' | 'audio';
  providerLabel: string;
  modelLabel: string;
  draft: Draft;
}) {
  const providers = () => apiProvidersFor(props.kind);
  const bucketProvider = () => props.draft[BUCKET_PROVIDER_FIELD[props.bucket]] || '';
  const bucketModel = () => props.draft[BUCKET_MODEL_FIELD[props.bucket]] || '';
  const models = () => providerModels(bucketProvider(), props.kind);

  const draftType = (): DraftType =>
    state.selectedType === 'shot' ? 'shot' : state.selectedType === 'audio' ? 'audio' : 'keyElement';

  /** 按 bucket 构造 patch（显式分支赋值，保证 Partial<Draft> 类型安全） */
  function providerModelPatch(provider?: string, model?: string): Partial<Draft> {
    const p: Partial<Draft> = {};
    if (provider !== undefined) {
      if (props.bucket === 'image') p.imageProviderId = provider;
      else if (props.bucket === 'video') p.videoProviderId = provider;
      else p.audioProviderId = provider;
    }
    if (model !== undefined) {
      if (props.bucket === 'image') p.imageModel = model;
      else if (props.bucket === 'video') p.videoModel = model;
      else p.audioModel = model;
    }
    return p;
  }

  function changeProvider(id: string) {
    const firstModel = providerModels(id, props.kind)[0] || '';
    studioActions.updateDraftLocal(draftType(), props.draft.id, providerModelPatch(id, firstModel));
  }

  function changeModel(v: string) {
    studioActions.updateDraftLocal(draftType(), props.draft.id, providerModelPatch(undefined, v));
  }

  return (
    <>
      <ParamGroup label={props.providerLabel}>
        <ParamSelect
          ariaLabel={props.providerLabel}
          value={bucketProvider()}
          options={providers().map((p) => ({ value: p.id, label: p.name || p.id }))}
          onChange={changeProvider}
        />
      </ParamGroup>
      <ParamGroup label={props.modelLabel}>
        <ParamSelect
          ariaLabel={props.modelLabel}
          value={bucketModel()}
          options={models().map((m) => ({ value: m, label: m }))}
          onChange={changeModel}
        />
      </ParamGroup>
    </>
  );
}
