/**
 * B10：成本看板（轮次/耗时/闸机拦截率/降级频率）——自 GlobalSettingsView 切出。
 * 指标信号与刷新动作自包含，行为零变更。
 */
import { Show, onMount, createSignal } from 'solid-js';
import { ParamGroup } from '@/components/middle-panel/params/ParamBase';
import { getAgentMetrics, type AgentMetrics } from '@/api/agent';

export function CostMetricsSection() {
  /** ：运行指标（成本看板） */
  const [metrics, setMetrics] = createSignal<AgentMetrics | null>(null);
  function refreshMetrics() {
    return getAgentMetrics().then(setMetrics).catch(() => { /* 后端未就绪静默 */ });
  }
  onMount(() => { void refreshMetrics(); });

  return (
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
  );
}
