/* eslint-disable max-lines */ // 全局设置页多设置卡聚合，拆分另行立项
import { Show, onMount, For, createSignal } from 'solid-js';
import { A } from '@solidjs/router';
import { FiArrowLeft, FiSettings } from 'solid-icons/fi';
import { ensureGlobalSettings, globalSettings, updateGlobalSettings } from '@/stores/global-settings';
import { apiProvidersFor, providerModels } from '@/lib/providers';
import { ParamGroup, ParamSelect } from '@/components/middle-panel/params/ParamBase';
import { getAgentMetrics, type AgentMetrics, type RuntimeSettings } from '@/api/agent';

/** ：模型分层策略表四角色（编排/生成/摘要/执行器） */
const MODEL_POLICY_ROLES = [
  { key: 'orchestration', label: '编排规划' },
  { key: 'generation_strong', label: '生成' },
  { key: 'summary', label: '摘要' },
  { key: 'executor', label: '执行器机械' },
] as const;

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
  /**  推理档位四档：默认=模型原生 */
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

  /** ：单角色策略局部更新（保留其他角色与其他键） */
  function setPolicyRole(roleKey: string, patch: { provider?: string; model?: string; thinking_level?: string }) {
    const policy = { ...(gs()?.model_policy || {}) };
    const cur = { ...(policy[roleKey] || { provider: '', model: '', thinking_level: '' }) };
    policy[roleKey] = { ...cur, ...patch };
    set({ model_policy: policy });
  }

  /** ：运行指标（成本看板） */
  const [metrics, setMetrics] = createSignal<AgentMetrics | null>(null);
  function refreshMetrics() {
    return getAgentMetrics().then(setMetrics).catch(() => { /* 后端未就绪静默 */ });
  }
  onMount(() => { void refreshMetrics(); });

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

          {/* 「推理档位」卡退役——执行器/摘要档位归入下方模型分层策略
              表的「推理」列（通用搭配默认：摘要/执行器机械 = 低，防思考吃预算） */}
          {/* 模型分层策略表（四角色自动路由；空 = 跟随主模型） */}
          <section class="gs-section">
            <h3>模型分层策略</h3>
            <div class="gs-role-list">
              <For each={MODEL_POLICY_ROLES}>
                {(role) => (
                  <div class="gs-row">
                    <ParamGroup label={role.label + ':'}>
                      <ParamSelect
                        ariaLabel={`${role.label}供应商`}
                        value={gs()!.model_policy?.[role.key]?.provider || ''}
                        options={[
                          { value: '', label: '跟随主模型' },
                          ...apiProvidersFor('chat').map((p) => ({ value: p.id, label: p.name || p.id })),
                        ]}
                        onChange={(v) => setPolicyRole(role.key, { provider: v, model: '' })}
                      />
                    </ParamGroup>
                    <ParamGroup label="模型:">
                      <ParamSelect
                        ariaLabel={`${role.label}模型`}
                        value={gs()!.model_policy?.[role.key]?.model || ''}
                        options={[
                          { value: '', label: '默认' },
                          ...providerModels(gs()!.model_policy?.[role.key]?.provider || '', 'chat')
                            .map((m) => ({ value: m, label: m })),
                        ]}
                        onChange={(v) => setPolicyRole(role.key, { model: v })}
                      />
                    </ParamGroup>
                    <ParamGroup label="推理:">
                      <ParamSelect
                        ariaLabel={`${role.label}推理档位`}
                        value={gs()!.model_policy?.[role.key]?.thinking_level || ''}
                        options={thinkingOpts()}
                        onChange={(v) => setPolicyRole(role.key, { thinking_level: v })}
                      />
                    </ParamGroup>
                  </div>
                )}
              </For>
            </div>
            <p class="gs-hint">
              编排规划 = 主对话/规划轮；生成 = 执行器长文生成与纠正重试；摘要 = 记忆摘要与会话压缩；
              执行器机械 = 拆解/提示词批量誊写（快模型先试，零进展自动升级）。
              「跟随主模型」= 不覆盖（沿用对话栏所选模型与既有回落链）；
              推理档通用搭配默认：摘要/执行器机械 = 低（照章办事不需深推理，防思考吃光输出预算），编排/生成 = 原生；改动即时生效。
            </p>
          </section>
          {/* B10：成本看板（轮次/耗时/闸机拦截率/降级频率） */}
          <section class="gs-section">
            <h3>运行成本</h3>
            <Show when={metrics()} fallback={<div class="gs-loading">加载指标…</div>}>
              <div class="gs-row">
                <ParamGroup label="轨迹数:"><span class="gs-metric-value">{metrics()!.traces_count}</span></ParamGroup>
                <ParamGroup label="平均耗时(模型轮):"><span class="gs-metric-value">{(metrics()!.avg_turn_ms / 1000).toFixed(1)}s</span></ParamGroup>
                <ParamGroup label="总轮次:"><span class="gs-metric-value">{metrics()!.total_steps}</span></ParamGroup>
                <ParamGroup label="闸机拦截率:">
                  <span class="gs-metric-value">
                    {metrics()!.gate_intercepts} / {metrics()!.gate_total}（{(metrics()!.gate_intercept_rate * 100).toFixed(1)}%）
                  </span>
                </ParamGroup>
                <ParamGroup label="降级切换:"><span class="gs-metric-value">{metrics()!.fallback_count} 次</span></ParamGroup>
              </div>
              <button type="button" class="btn-secondary" onClick={() => void refreshMetrics()}>刷新指标</button>
            </Show>
            <p class="gs-hint">
              基于最近 200 条执行轨迹聚合（agent_traces.jsonl）：轮次/操作数/闸机拦截率/模型降级频率。
              用于成本与质量跟踪；明细见生成日志面板与 /api/agent/traces。
            </p>
          </section>
        </Show>
      </div>
    </div>
  );
}
