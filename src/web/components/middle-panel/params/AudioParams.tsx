import { For, Show, createSignal } from 'solid-js';
import { FiMusic } from 'solid-icons/fi';
import { generateAudio } from '@/lib/audio-actions';
import { uploadFiles } from '@/api/upload';
import { cloneVoice, listVoices, type VoiceOption } from '@/api/generate';
import { showToast } from '@/stores/toast';
import { audioModelsFor, audioProvidersFor } from '@/lib/providers';
import {
  AUDIO_CHANNELS, AUDIO_CHANNEL_LABELS, audioChannelFor,
} from '@/lib/audio-channel';
import {
  audioParamsFor, isParamVisible, paramPatch, resolveParamValue,
} from '@/lib/audio-params';
import { state, studioActions } from '@/stores/studio';
import {
  ParamGroup, ParamSelect, btnPrimary, btnSecondary,
} from './ParamBase';
import { ProviderModelSelects } from './ProviderModelSelects';
import type {
  AudioCapability, AudioParamSpec, Draft, DraftType,
} from '@/types';

const GENERATE_LABEL: Record<AudioCapability, string> = {
  voice_design: '生成音色',
  tts: '合成语音',
  music: '生成背景音乐',
  sfx: '生成音效',
};

/** 通道选项用模块级常量：内联 map 每次渲染都新建对象，会让 <For> 重建 option */
const CHANNEL_OPTIONS = AUDIO_CHANNELS.map(
  (c) => ({ value: c, label: AUDIO_CHANNEL_LABELS[c] }),
);

/** 单个参数控件：按 schema 的 type 渲染（text/enum/bool/number/refs） */
function ParamField(props: {
  spec: AudioParamSpec;
  draft: Draft;
  /** 当前音频通道（语音合成才有「上传音频创建音色」入口） */
  channel: AudioCapability;
  onChange: (patch: Partial<Draft>) => void;
}) {
  // spec 在挂载期不变（<For> 按 spec 对象身份键控），静态读取避免无谓的响应式追踪
  // eslint-disable-next-line solid/reactivity -- 有意静态快照，换模型时由 <For> 重挂载
  const spec = props.spec;
  const label = spec.label || spec.key;
  const value = () => resolveParamValue(props.draft, spec);

  // 语音合成的音色输入：「上传音频 → 后端复刻 → 回填 voice_id」
  const [cloning, setCloning] = createSignal(false);
  const canClone = () => !!spec.clone && props.channel === 'tts';
  let cloneInput: HTMLInputElement | undefined;

  // 试听：复刻返回的 preview_url / 平台音色列表自带的 preview_url 共用同一个播放器
  const [previewUrl, setPreviewUrl] = createSignal('');
  const [voices, setVoices] = createSignal<VoiceOption[]>([]);
  const [listing, setListing] = createSignal(false);
  const [pickedVoice, setPickedVoice] = createSignal('');
  const canList = () => !!spec.list_voices && props.channel === 'tts';

  async function cloneFromAudio(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = ''; // 允许再次选择同一个文件
    if (!file) return;
    if (!String(file.type || '').startsWith('audio/')) {
      showToast('请上传音频文件（mp3 / wav / m4a 等）', 'warning');
      return;
    }
    setCloning(true);
    try {
      showToast(`正在上传并复刻音色：${file.name}`, 'info');
      const uploaded = await uploadFiles([file]);
      const url = uploaded.find((u) => u.kind === 'audio')?.url || '';
      if (!url) throw new Error('上传接口没有返回音频地址');
      const res = await cloneVoice({
        provider_id: props.draft.audioProviderId || '',
        target_model: props.draft.audioModel || '',
        audio_url: url,
      });
      if (!res.voice_id) throw new Error('复刻接口没有返回音色 ID');
      props.onChange({ voiceId: res.voice_id });
      setPreviewUrl(res.preview_url || '');
      showToast(`音色已创建并填入：${res.voice_id}`, 'success');
    } catch (err) {
      showToast((err as Error).message || '音色创建失败', 'error');
    } finally {
      setCloning(false);
    }
  }

  /** 拉取平台账号下的音色（仅后端声明 list_voices 的适配器有入口） */
  async function fetchVoices() {
    setListing(true);
    try {
      const res = await listVoices({
        provider_id: props.draft.audioProviderId || '',
        model: props.draft.audioModel || '',
      });
      const items = res.voices || [];
      setVoices(items);
      setPickedVoice('');
      showToast(
        items.length ? `已拉取 ${items.length} 个音色，可下拉选择并试听` : '平台没有返回音色',
        items.length ? 'success' : 'warning');
    } catch (err) {
      showToast((err as Error).message || '拉取音色失败', 'error');
    } finally {
      setListing(false);
    }
  }

  /** 选中平台音色：回填 voice_id，有预览就换播放器源 */
  function pickVoice(voiceId: string) {
    setPickedVoice(voiceId);
    if (!voiceId) {
      setPreviewUrl('');
      return;
    }
    const voice = voices().find((v) => v.voice_id === voiceId);
    props.onChange({ voiceId });
    setPreviewUrl(voice?.preview_url || '');
    if (!voice?.preview_url) showToast('该音色没有试听音频，直接用 ID 合成即可', 'info');
  }

  if (spec.type === 'refs') {
    const count = () => (props.draft.refAssets || []).length;
    let fileRef: HTMLInputElement | undefined;
    /** 参数栏直接上传参考音频（音色设计=声音复刻源） */
    async function upload(e: Event) {
      const input = e.currentTarget as HTMLInputElement;
      const file = input.files?.[0];
      input.value = ''; // 允许再次选择同一个文件
      if (!file) return;
      if (!String(file.type || '').startsWith('audio/')) {
        showToast('请上传音频文件（mp3 / wav / m4a 等）', 'warning');
        return;
      }
      try {
        showToast(`正在上传：${file.name}`, 'info');
        const uploaded = await uploadFiles([file]);
        const url = uploaded.find((u) => u.kind === 'audio')?.url || '';
        if (!url) throw new Error('上传接口没有返回音频地址');
        props.onChange({ refAssets: [...(props.draft.refAssets || []), url] });
        showToast('参考音频已加入，生成时会使用它', 'success');
      } catch (err) {
        showToast((err as Error).message || '音频上传失败', 'error');
      }
    }
    return (
      <ParamGroup label={`${label}:`}>
        <span class="param-unit">
          {count() ? `${count()} 条（生成时使用）` : '无（上传或引用参考栏音频）'}
        </span>
        <button type="button" class={btnSecondary} onClick={() => fileRef?.click()}>
          上传音频
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="audio/*"
          hidden
          onChange={(e) => void upload(e)}
        />
      </ParamGroup>
    );
  }

  if (spec.type === 'bool' || spec.type === 'enum') {
    const options = spec.type === 'bool'
      ? [{ value: 'true', label: '开' }, { value: 'false', label: '关' }]
      : (spec.values || []).map((v) => ({ value: v, label: v }));
    return (
      <ParamGroup label={`${label}:`}>
        <ParamSelect
          ariaLabel={label}
          value={String(value() ?? '')}
          options={options}
          onChange={(v) => props.onChange(paramPatch(spec, v))}
        />
      </ParamGroup>
    );
  }

  if (spec.type === 'number') {
    return (
      <ParamGroup label={`${label}:`}>
        <input
          class="param-select custom-ratio-input"
          type="number"
          aria-label={label}
          min={spec.min}
          max={spec.max}
          step={spec.step ?? 1}
          value={String(value() ?? '')}
          onChange={(e) => props.onChange(paramPatch(spec, e.currentTarget.value))}
        />
      </ParamGroup>
    );
  }

  // 长文本参数（试听文本 / 歌词）：多行宽输入框，独占一整行
  // ——单行 48px 小格子写不下完整台词，用户在参数栏没法看全文
  if (spec.multiline) {
    return (
      <div class="param-group param-group-block">
        <span class="param-label">{label}:</span>
        <textarea
          class="param-textarea"
          aria-label={label}
          rows={2}
          placeholder={spec.placeholder || ''}
          value={String(value() ?? '')}
          onChange={(e) => props.onChange(paramPatch(spec, e.currentTarget.value))}
        />
        <Show when={spec.max_len}>
          <span class="param-unit">
            {spec.min_len ? `${spec.min_len}-${spec.max_len} 字` : `≤${spec.max_len} 字`}
          </span>
        </Show>
      </div>
    );
  }

  return (
    <div class={spec.note || canList() ? 'param-group param-group-block' : 'param-group'}>
      <span class="param-label">{label}:</span>
      <input
        class="param-select param-text-input"
        aria-label={label}
        placeholder={spec.placeholder || ''}
        value={String(value() ?? '')}
        onChange={(e) => props.onChange(paramPatch(spec, e.currentTarget.value))}
      />
      <Show when={canClone()}>
        <button
          type="button"
          class={btnSecondary}
          disabled={cloning()}
          title="上传一段 10-60 秒的干净人声，自动复刻为音色并填入音色 ID"
          onClick={() => cloneInput?.click()}
        >
          {cloning() ? '复刻中…' : '上传音色'}
        </button>
        <input
          ref={cloneInput}
          type="file"
          accept="audio/*"
          hidden
          onChange={(e) => void cloneFromAudio(e)}
        />
      </Show>
      <Show when={canList()}>
        <button
          type="button"
          class={btnSecondary}
          disabled={listing()}
          title="从平台账号拉取音色清单，选中后可试听"
          onClick={() => void fetchVoices()}
        >
          {listing() ? '拉取中…' : '拉取音色'}
        </button>
        <Show when={voices().length}>
          <select
            class="param-select param-voice-select"
            aria-label="平台音色"
            value={pickedVoice()}
            onChange={(e) => pickVoice(e.currentTarget.value)}
          >
            <option value="">选择音色（{voices().length}）</option>
            <For each={voices()}>
              {(v) => (
                <option value={v.voice_id}>
                  {v.name ? `${v.name}（${v.voice_id}）` : v.voice_id}
                </option>
              )}
            </For>
          </select>
        </Show>
      </Show>
      <Show when={previewUrl()}>
        <audio
          class="param-audio-preview"
          src={previewUrl()}
          controls
          preload="none"
          aria-label="音色试听"
        />
      </Show>
      {spec.note ? <div class="param-note">{spec.note}</div> : null}
    </div>
  );
}

/**
 * 音频参数栏（2026-10-28 参数自适应批）。
 *
 * 提示词框承载描述/台词；本栏按「当前模型自己声明的 params」动态渲染，
 * 模型没声明的参数不出现、声明了但条件不成立的隐藏（如纯音乐时的演唱性别）。
 * 换模型 = 换一组控件，前端不需要为新厂商改代码。
 */
export function AudioParams(props: { draft: Draft; type?: DraftType }) {
  const d = () => props.draft;
  const draftType = () => props.type || 'audio';
  const channel = () => audioChannelFor(d());
  /** 当前通道下真正可用的供应商（已接适配器 + 有模型）——与 API 设置页同口径，
   *  未接音频的厂商不再列出（原先标“未接音频”仍可选，选了只会在提交时报错）。 */
  const providers = () => audioProvidersFor(channel());
  const params = () => audioParamsFor(
    state.apiProviders, d().audioProviderId || '', d().audioModel || '', channel(),
  );
  const visible = () => params().filter(
    (spec) => spec.source !== 'prompt' && isParamVisible(spec, params(), d()),
  );

  function update(patch: Partial<Draft>) {
    studioActions.updateDraftLocal(draftType(), d().id, patch);
  }

  /** 切换通道：当前供应商在新通道仍可用就保留，否则收敛到该通道首个可用项 */
  function changeChannel(next: AudioCapability) {
    const pool = audioProvidersFor(next);
    const keep = pool.find((p) => p.id === (d().audioProviderId || ''));
    const pid = keep?.id || pool[0]?.id || '';
    const patch: Partial<Draft> = { audioChannel: next };
    if (pid) {
      patch.audioProviderId = pid;
      patch.audioModel = audioModelsFor(pid, next)[0] || '';
    }
    update(patch);
  }

  return (
    <>
      <ParamGroup label="音频通道:">
        <ParamSelect
          ariaLabel="音频通道"
          value={channel()}
          options={CHANNEL_OPTIONS}
          onChange={(v) => changeChannel(v as AudioCapability)}
        />
      </ParamGroup>
      <ProviderModelSelects
        kind="audio"
        bucket="audio"
        providerLabel="音频 API:"
        modelLabel="音频模型:"
        draft={d()}
        modelsFor={(pid) => audioModelsFor(pid, channel())}
        providers={providers()}
      />

      <For each={visible()}>
        {(spec) => (
          <ParamField
            spec={spec}
            draft={d()}
            channel={channel()}
            onChange={(patch) => update(patch)}
          />
        )}
      </For>

      <Show when={!params().length}>
        <ParamGroup label="参数:">
          <span class="param-unit">该模型未声明参数（可在 API 配置的 audio_models_meta 声明）</span>
        </ParamGroup>
      </Show>

      <div class="param-actions">
        <button
          type="button"
          class={`${btnPrimary} btn-emerald`}
          onClick={() => void generateAudio({
            channel: channel(),
            providerId: d().audioProviderId || '',
            model: d().audioModel || '',
          })}
        >
          <FiMusic size={13} /> {GENERATE_LABEL[channel()]}
        </button>
      </div>
    </>
  );
}
