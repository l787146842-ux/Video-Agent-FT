import { Show, onMount } from 'solid-js';
import { A } from '@solidjs/router';
import { FiArrowLeft, FiSettings } from 'solid-icons/fi';
import { ensureGlobalSettings, globalSettings, updateGlobalSettings } from '@/stores/global-settings';
import { apiProvidersFor, providerModels } from '@/lib/providers';
import { ParamGroup, ParamSelect } from '@/components/middle-panel/params/ParamBase';
import type { RuntimeSettings } from '@/api/agent';

/**
 * 全局模型选择设置页（路由 /global-settings，替代旧顶栏自动切换按钮）：
 * 出图默认（API/模型/分辨率）、出视频默认（API/模型/分辨率/分镜最大时长）、
 * 聊天框出图开关、自动切换开关。改动即时热生效并持久化；
 * 工作台自动出图/出视频与 Agent 任务参数自动填入均按此设置。
 */
export default function GlobalSettingsView() {
  onMount(() => { void ensureGlobalSettings(); });
  const gs = globalSettings;

  const imageProviderOpts = () => [
    { value: '', label: '未设置（跟随草稿/规格）' },
    ...apiProvidersFor('image').map((p) => ({ value: p.id, label: p.name || p.id })),
  ];
  const videoProviderOpts = () => [
    { value: '', label: '未设置（跟随草稿/规格）' },
    ...apiProvidersFor('video').map((p) => ({ value: p.id, label: p.name || p.id })),
  ];
  const imageModelOpts = () => [
    { value: '', label: '未设置' },
    ...providerModels(gs()?.default_image_provider_id || '', 'image').map((m) => ({ value: m, label: m })),
  ];
  const videoModelOpts = () => [
    { value: '', label: '未设置' },
    ...providerModels(gs()?.default_video_provider_id || '', 'video').map((m) => ({ value: m, label: m })),
  ];
  /** 814H7 推理档位四档：默认=模型原生 */
  const thinkingOpts = () => [
    { value: '', label: '默认（原生）' },
    { value: 'high', label: '高' },
    { value: 'medium', label: '中' },
    { value: 'low', label: '低' },
  ];

  function set(patch: Partial<RuntimeSettings>) {
    void updateGlobalSettings(patch);
  }

  /** 分镜最大时长（秒）：与模型单镜头上限对齐夹取 1-15 */
  function setMaxDuration(v: string) {
    const n = Math.max(1, Math.min(15, parseInt(v, 10) || 5));
    set({ max_shot_duration: n });
  }

  return (
    <div class="global-settings-view">
      <div class="gs-panel">
        <div class="gs-header">
          <A href="/" class="gs-back" title="返回影视工作台"><FiArrowLeft size={14} /></A>
          <FiSettings size={15} class="gs-icon" />
          <span class="gs-title">全局模型设置</span>
          <span class="gs-sub">改动即时生效，工作台自动出图/出视频与 Agent 任务参数均按此执行</span>
        </div>

        <Show when={gs()} fallback={<div class="gs-loading">加载设置…</div>}>
          {/* 出图默认 */}
          <section class="gs-section">
            <h3>出图默认</h3>
            <div class="gs-row">
              <ParamGroup label="图片 API:">
                <ParamSelect
                  ariaLabel="全局默认出图 API"
                  value={gs()!.default_image_provider_id}
                  options={imageProviderOpts()}
                  onChange={(v) => set({ default_image_provider_id: v, default_image_model: '' })}
                />
              </ParamGroup>
              <ParamGroup label="出图模型:">
                <ParamSelect
                  ariaLabel="全局默认出图模型"
                  value={gs()!.default_image_model}
                  options={imageModelOpts()}
                  onChange={(v) => set({ default_image_model: v })}
                />
              </ParamGroup>
              <ParamGroup label="图片分辨率:">
                <ParamSelect
                  ariaLabel="全局默认图片分辨率"
                  value={gs()!.default_image_resolution}
                  options={['1K', '2K', '4K'].map((v) => ({ value: v, label: v }))}
                  onChange={(v) => set({ default_image_resolution: v })}
                />
              </ParamGroup>
            </div>
          </section>

          {/* 出视频默认 */}
          <section class="gs-section">
            <h3>出视频默认</h3>
            <div class="gs-row">
              <ParamGroup label="视频 API:">
                <ParamSelect
                  ariaLabel="全局默认出视频 API"
                  value={gs()!.default_video_provider_id}
                  options={videoProviderOpts()}
                  onChange={(v) => set({ default_video_provider_id: v, default_video_model: '' })}
                />
              </ParamGroup>
              <ParamGroup label="视频模型:">
                <ParamSelect
                  ariaLabel="全局默认视频模型"
                  value={gs()!.default_video_model}
                  options={videoModelOpts()}
                  onChange={(v) => set({ default_video_model: v })}
                />
              </ParamGroup>
              <ParamGroup label="视频分辨率:">
                <ParamSelect
                  ariaLabel="全局默认视频分辨率"
                  value={gs()!.default_video_resolution}
                  options={['480p', '720p', '1080p'].map((v) => ({ value: v, label: v }))}
                  onChange={(v) => set({ default_video_resolution: v })}
                />
              </ParamGroup>
              <ParamGroup label="分镜最大时长:">
                <input
                  class="custom-ratio-input"
                  type="number"
                  min="1"
                  max="15"
                  aria-label="分镜最大时长（秒）"
                  value={String(gs()!.max_shot_duration)}
                  onChange={(e) => setMaxDuration(e.currentTarget.value)}
                />
                <span class="param-unit">秒</span>
              </ParamGroup>
            </div>
            <p class="gs-hint">Agent 自己拆分镜时单个分镜时长不超过该值；新建分镜草稿默认按该时长填写。</p>
          </section>

          {/* 聊天框出图开关 */}
          <section class="gs-section">
            <h3>聊天框出图</h3>
            <button
              type="button"
              class="toggle-switch"
              aria-pressed={gs()!.chat_image_enabled}
              onClick={() => set({ chat_image_enabled: !gs()!.chat_image_enabled })}
            >
              <span>关</span>
              <span class={`switch-track ${gs()!.chat_image_enabled ? 'active' : ''}`}>
                <span class="switch-thumb" />
              </span>
              <span>开</span>
            </button>
            <p class="gs-hint">开启时 Agent 可在对话中自动出图（使用上方出图默认渠道）；关闭后 Agent 不主动触发生图。</p>
          </section>

          {/* 自动切换（原顶栏开关移入） */}
          <section class="gs-section">
            <h3>自动切换</h3>
            <button
              type="button"
              class="toggle-switch"
              aria-pressed={gs()!.model_fallback_enabled}
              onClick={() => set({ model_fallback_enabled: !gs()!.model_fallback_enabled })}
            >
              <span>关</span>
              <span class={`switch-track ${gs()!.model_fallback_enabled ? 'active' : ''}`}>
                <span class="switch-thumb" />
              </span>
              <span>开</span>
            </button>
            <p class="gs-hint">开启时模型联不通/出不了图视频自动换同模型其他 API 厂商；关闭则直接按上游报错。</p>
          </section>

          {/* 814H7：推理档位（执行器/辅助摘要；主模型档位在对话栏模型胶囊里按会话选） */}
          <section class="gs-section">
            <h3>推理档位</h3>
            <div class="gs-row">
              <ParamGroup label="执行器机械调用:">
                <ParamSelect
                  ariaLabel="执行器推理档位"
                  value={gs()!.executor_thinking_level || ''}
                  options={thinkingOpts()}
                  onChange={(v) => set({ executor_thinking_level: v })}
                />
              </ParamGroup>
              <ParamGroup label="辅助摘要:">
                <ParamSelect
                  ariaLabel="辅助摘要推理档位"
                  value={gs()!.aux_thinking_level || ''}
                  options={thinkingOpts()}
                  onChange={(v) => set({ aux_thinking_level: v })}
                />
              </ParamGroup>
            </div>
            <p class="gs-hint">
              执行器机械调用 = 拆关键元素/分镜/写提示词/出题等批量产出；辅助摘要 = 记忆摘要与会话压缩。
              默认 = 模型原生能力；高/中/低按 reasoning_effort 透传，端点不认时自动忽略或降级重试。
              主模型（对话规划）的档位在对话栏「模型」胶囊里按会话选择。
            </p>
          </section>
        </Show>
      </div>
    </div>
  );
}
