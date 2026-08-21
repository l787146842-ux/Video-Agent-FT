import { For, createSignal } from 'solid-js';
import { state } from '@/stores/studio';
import { apiProvidersFor, providerModels, type ProviderKind } from '@/lib/providers';
import { t } from '@/lib/locale';

export interface ConfirmOptionItem {
  label: string;
  /** ：卡片展示文字（缺省用 label）；label 保留「键：值」回传格式 */
  display?: string;
  description?: string;
  group?: string;
  /** ：点击发送的机械值（后端确定性消费）；缺省发送 label */
  value?: string;
}

/** 引导交互可识别的选择维度 */
export type PickDim = 'provider' | 'model' | 'image-channel' | 'video-channel' | '';

/**
 * 识别「选 API 厂商 / 选模型」类维度（888 反馈：选项卡一张张点太笨重，
 * 希望和底部输入框的厂商/模型选择一样用下拉框，且选项拉取 API 配置全量）：
 * 优先看问题标题关键词（出图/出视频渠道、供应商、模型），
 * 再用已配置供应商/模型名客观匹配选项兜底。
 */
export function pickDimension(title: string, opts: ConfirmOptionItem[]): PickDim {
  const titleText = String(title || '');
  //分辨率/时长类维度是固定档位选项卡；标题常含「图片/视频」
  // 方向词，先精确判死防被下方渠道正则误判成厂商/模型下拉
  if (/分辨率/.test(titleText)) return '';
  if (/最大时长|单镜头|分镜时长/.test(titleText)) return '';
  // 规格向导的出图/出视频渠道维度（一次要选厂商+模型）
  if (/(出图|生图|图像|图片)/.test(titleText) && /(渠道|API|厂商|供应商|模型)/.test(titleText)) {
    return 'image-channel';
  }
  if (/(出视频|生视频|视频)/.test(titleText) && /(渠道|API|厂商|供应商|模型)/.test(titleText)) {
    return 'video-channel';
  }
  if (/供应商|厂商/.test(titleText)) return 'provider';
  if (/模型/.test(titleText)) return 'model';
  if (!opts.length) return '';
  // 兜底：选项与已配置供应商/模型名客观匹配
  const provNames = (state.apiProviders || [])
    .flatMap((p) => [p.id, p.name].filter(Boolean).map((s) => String(s).toLowerCase()));
  const modelNames = [
    ...(state.availableChatModels || []),
    ...(state.availableImageModels || []),
    ...(state.availableVideoModels || []),
  ].map((m) => String(m).toLowerCase());
  const labels = opts.map((o) => (o.label || '').toLowerCase());
  const provHits = labels.filter((l) => provNames.some((n) => l.includes(n) || n.includes(l))).length;
  const modelHits = labels.filter((l) => modelNames.some((n) => n && l.includes(n))).length;
  const half = Math.ceil(labels.length / 2);
  if (provHits >= half && provHits >= modelHits) return 'provider';
  if (modelHits >= half) return 'model';
  return '';
}

/** 维度 → 供应商类别（决定下拉框拉哪类厂商与模型） */
export function kindForDim(dim: PickDim, title: string): ProviderKind {
  if (dim === 'image-channel') return 'image';
  if (dim === 'video-channel') return 'video';
  // 变量名避开 i18n 惯用名 t（批6：遮蔽隐患清偿）
  const titleStr = String(title || '');
  if (/视频/.test(titleStr)) return 'video';
  if (/图|图片|图像/.test(titleStr)) return 'image';
  return 'chat';
}

/**
 * 厂商+模型级联下拉（与底部输入框的 PillDropdown 同交互逻辑）：
 * 选项实时拉取 API 配置（apiProvidersFor/providerModels），不再依赖
 * 模型给出的候选清单；选中值格式「厂商名 / 模型名」随引导回复发送。
 */
export function ConfigProviderModelSelect(props: {
  kind: ProviderKind;
  value: string;
  onPick: (value: string) => void;
}) {
  const [provId, setProvId] = createSignal('');
  const [model, setModel] = createSignal('');
  const providers = () => apiProvidersFor(props.kind);
  const models = () => (provId() ? providerModels(provId(), props.kind) : []);
  const provLabel = (id: string) => {
    const p = providers().find((x) => x.id === id);
    return p?.name || p?.id || id;
  };
  return (
    <div class="confirm-select-row">
      <select
        class="confirm-select"
        value={provId()}
        onChange={(e) => {
          const v = e.currentTarget.value;
          setProvId(v);
          setModel('');
          props.onPick(v ? provLabel(v) : '');
        }}
      >
        <option value="" disabled>{t('rp.confirm.pickProvider')}</option>
        <For each={providers()}>
          {(p) => <option value={p.id}>{p.name || p.id}</option>}
        </For>
      </select>
      <select
        class="confirm-select"
        disabled={!provId() || !models().length}
        value={model()}
        onChange={(e) => {
          const v = e.currentTarget.value;
          setModel(v);
          props.onPick(v ? `${provLabel(provId())} / ${v}` : provLabel(provId()));
        }}
      >
        <option value="" disabled>{models().length ? '请选择模型…' : '该厂商暂无可选模型'}</option>
        <For each={models()}>
          {(m) => <option value={m}>{m}</option>}
        </For>
      </select>
    </div>
  );
}
