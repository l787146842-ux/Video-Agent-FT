/**
 * 供应商 + 模型联动下拉（切供应商时模型重置为该供应商首项）
 * ——自 ParamBase 切出，行为零变更。
 * kind 决定供应商/模型列表来源；bucket 决定读写字段归属
 * （音频面板 kind='chat'、bucket='audio'）。
 */
import { createEffect } from 'solid-js';
import { state, studioActions } from '@/stores/studio';
import { apiProvidersFor, providerModels } from '@/lib/providers';
import type { ApiProvider, Draft, DraftType } from '@/types';
import { ParamGroup, ParamSelect } from './ParamBase';

/** 按种类参数字段名映射（2026-08-15 参数隔离）：三个生成器各自读写本种类 provider/model */
const BUCKET_PROVIDER_FIELD = {
  image: 'imageProviderId', video: 'videoProviderId', audio: 'audioProviderId',
} as const;
const BUCKET_MODEL_FIELD = {
  image: 'imageModel', video: 'videoModel', audio: 'audioModel',
} as const;

type Option = { value: string; label: string };

/** 选项对象缓存：同一 value 复用同一对象。`<For>` 按引用做 diff，每次 map 出
 *  新对象会让 option 节点全量重建，原生 select 随之丢掉选中项（界面跳回首项，
 *  实证：选好音频厂商后一动模型，厂商下拉跳回「阿里百炼」）。 */
function optionOf(cache: Map<string, Option>, value: string, label: string): Option {
  const hit = cache.get(value);
  if (hit && hit.label === label) return hit;
  const opt = { value, label };
  cache.set(value, opt);
  return opt;
}

export function ProviderModelSelects(props: {
  kind: 'image' | 'video' | 'chat' | 'audio';
  bucket: 'image' | 'video' | 'audio';
  providerLabel: string;
  modelLabel: string;
  draft: Draft;
  /** 可选：按供应商取当前通道/种类的可用模型（音频通道用；缺省读供应商模型表）。
   *  必须是函数：切供应商的当帧就要取到**目标供应商**的模型；传死列表只能拿到
   *  旧供应商的，会把旧厂商首模型写进新厂商（跨厂商串选的另一半根因）。 */
  modelsFor?: (providerId: string) => string[];
  /** 可选：调用方按通道过滤后的供应商列表（音频通道用；缺省按 kind 取全部） */
  providers?: ApiProvider[];
}) {
  const providers = () => props.providers ?? apiProvidersFor(props.kind);
  const bucketProvider = () => props.draft[BUCKET_PROVIDER_FIELD[props.bucket]] || '';
  const bucketModel = () => props.draft[BUCKET_MODEL_FIELD[props.bucket]] || '';
  const models = (providerId: string): string[] => (props.modelsFor
    ? props.modelsFor(providerId)
    : providerModels(providerId, props.kind));

  // 每个实例独立缓存：provider id 与模型名分表，互不干扰
  const providerOptionCache = new Map<string, Option>();
  const modelOptionCache = new Map<string, Option>();
  const providerOptions = () => providers().map(
    (p) => optionOf(providerOptionCache, p.id, p.name || p.id));
  const modelOptions = () => models(bucketProvider()).map(
    (m) => optionOf(modelOptionCache, m, m));

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
    const firstModel = models(id)[0] || '';
    studioActions.updateDraftLocal(draftType(), props.draft.id, providerModelPatch(id, firstModel));
  }

  function changeModel(v: string) {
    studioActions.updateDraftLocal(draftType(), props.draft.id, providerModelPatch(undefined, v));
  }

  /**
   * 不变式（仅音频）：当前模型必须属于「当前供应商 × 当前通道」的可用列表。
   * 换通道、换供应商、或能力清单丢失时，状态里会残留不匹配的组合
   * （已实证：API=阿里百炼 却选中 eleven_*；通道=合成 却选中 voice-design）。
   * 这里自动收敛到首项并写回，而不是让下拉显示一个不属于它的值。
   */
  createEffect(() => {
    if (props.kind !== 'audio') return;
    const plist = providers();
    if (!plist.length) return;
    const pid = bucketProvider();
    if (!pid || !plist.some((p) => p.id === pid)) {
      const fallback = plist[0];
      const first = models(fallback.id)[0] || '';
      studioActions.updateDraftLocal(
        draftType(), props.draft.id, providerModelPatch(fallback.id, first));
      return;
    }
    const list = models(pid);
    const current = bucketModel();
    if (list.length && (!current || !list.includes(current))) {
      studioActions.updateDraftLocal(
        draftType(), props.draft.id, providerModelPatch(undefined, list[0]));
    }
  });

  return (
    <>
      <ParamGroup label={props.providerLabel}>
        <ParamSelect
          ariaLabel={props.providerLabel}
          value={bucketProvider()}
          options={providerOptions()}
          onChange={changeProvider}
        />
      </ParamGroup>
      <ParamGroup label={props.modelLabel}>
        <ParamSelect
          ariaLabel={props.modelLabel}
          value={bucketModel()}
          options={modelOptions()}
          onChange={changeModel}
        />
      </ParamGroup>
    </>
  );
}
