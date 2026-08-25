/**
 * API 配置页（画布同款功能与布局，用户裁决 2026-08-16：modelscope/runninghub/
 * 火山引擎/CLI 的内容块与画布一模一样；去「推荐API」）。
 * 后端：PUT /api/providers（api_key/clear_key/wallet_api_key/clear_wallet_key → API/.env）、
 * fetch-models（自动分类）、test-connection（验证地址）、probe-async（验证协议）、
 * /api/{gemini-cli,codex,jimeng}/status|help、/api/jimeng/login/*|logout|credit。
 *
 * ：视图子域切至 settings/（SidePanel/ProviderDetail/RunningHubGuide/
 * CliAccountCard/FetchModelsModal/CliModal）；CLI/拉取模型/验证域动作切至
 * use-cli-ops/use-model-fetch/use-provider-verify，子组件经 SettingsApi
 * 单对象消费，行为零变更。
 */
import { createSignal, Show, onMount } from 'solid-js';
import { A } from '@solidjs/router';
import { FiArrowLeft } from 'solid-icons/fi';
import { getProviders } from '@/api/providers';
import { apiPut } from '@/api/client';
import { showToast } from '@/stores/toast';
import { studioActions } from '@/stores/studio';
import type { ApiProvider } from '@/types';
import {
  CLI_PROTOCOLS, newProvider,
  type EditableProvider, type ModelKind, type SettingsApi,
} from './settings-meta';
import { useCliOps } from './use-cli-ops';
import { useModelFetch } from './use-model-fetch';
import { useProviderVerify } from './use-provider-verify';
import { SettingsSidePanel } from './settings/SettingsSidePanel';
import { ProviderDetail } from './settings/ProviderDetail';
import { CliModal } from './settings/CliModal';
import { FetchModelsModal } from './settings/FetchModelsModal';

export default function SettingsView() {
  const [providers, setProviders] = createSignal<EditableProvider[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [sel, setSel] = createSignal(0);
  // CLI 域（安装状态/弹窗/即梦登录轮询）收敛在 use-cli-ops
  const cli = useCliOps();

  // Key 输入（每平台独立缓冲，切换平台重置）
  const [keyInput, setKeyInput] = createSignal('');
  const [rhCoin, setRhCoin] = createSignal('');
  const [rhWallet, setRhWallet] = createSignal('');

  onMount(async () => {
    await reload();
    await cli.loadCliStatuses();
  });

  async function reload() {
    try {
      const data = await getProviders();
      setProviders(data.providers.map((p) => ({ ...p, api_key: '' })));
    } catch {
      showToast('加载供应商配置失败', 'error');
    } finally {
      setLoading(false);
    }
  }

  const current = () => providers()[sel()];
  const proto = () => String(current()?.protocol || '');
  const isCli = () => CLI_PROTOCOLS.has(proto());
  const imageMode = () => String(current()?.image_request_mode || 'openai');

  function nextCustomId(): string {
    let max = 0;
    for (const p of providers()) {
      const m = /^custom-api-(\d+)$/.exec(p.id || '');
      if (m) max = Math.max(max, parseInt(m[1], 10));
    }
    return `custom-api-${max + 1}`;
  }

  function switchSel(i: number) {
    setSel(i);
    setKeyInput('');
    setRhCoin('');
    setRhWallet('');
    verify.resetVerify();
  }

  function patch(field: string, value: unknown) {
    setProviders((prev) => prev.map((p, i) => (i === sel() ? { ...p, [field]: value } : p)));
  }

  // 拉取模型域（fetched/savedCats + 拉取/应用动作）收敛在 use-model-fetch
  const mf = useModelFetch(current, keyInput, patch);

  // 验证地址/协议域（verifyResult + test-connection/probe-async）收敛在 use-provider-verify
  const verify = useProviderVerify(current, keyInput, imageMode, patch);

  /** 保存全部（可给当前平台附加覆盖字段，如 api_key/clear_key/wallet_api_key） */
  async function saveAll(overrides?: Record<string, unknown>): Promise<boolean> {
    const list = providers().map((p, i) => {
      const base: Record<string, unknown> = {
        // 用户裁决：去掉「启用」开关——配置并保存即参与生成渠道候选
        id: p.id, name: p.name, protocol: p.protocol, base_url: p.base_url, enabled: true,
        image_request_mode: String(p.image_request_mode || 'openai'),
        chat_models: (p.chat_models || []).map((s) => s.trim()).filter(Boolean),
        image_models: (p.image_models || []).map((s) => s.trim()).filter(Boolean),
        video_models: (p.video_models || []).map((s) => s.trim()).filter(Boolean),
      };
      return i === sel() && overrides ? { ...base, ...overrides } : base;
    });
    try {
      const saved = await apiPut<{ providers: ApiProvider[] }>('/api/providers', { providers: list });
      const keepSel = sel();
      setProviders(saved.providers.map((p) => ({ ...p, api_key: '' })));
      setSel(Math.max(0, Math.min(keepSel, saved.providers.length - 1)));
      showToast('供应商配置已保存', 'success');
      // 实时刷新生成渠道候选（全局设置/参数栏下拉同源 store）
      try {
        const provs = await getProviders();
        studioActions.setApiConfig({ providers: provs.providers.filter((p) => p.enabled !== false) });
      } catch { /* 静默 */ }
      return true;
    } catch (e) {
      showToast(`保存失败：${(e as Error).message}`, 'error');
      return false;
    }
  }

  /** Key 行 ✓：立即写入 env（画布同款） */
  async function commitKey() {
    const v = keyInput().trim();
    if (!v) {
      showToast('请输入 API Key', 'warning');
      return;
    }
    if (await saveAll({ api_key: v })) setKeyInput('');
  }

  /** Key 行 🗑：清除 env 中的 Key */
  async function clearKey() {
    if (await saveAll({ clear_key: true })) setKeyInput('');
  }

  function addProvider() {
    setProviders((prev) => [...prev, newProvider(nextCustomId())]);
    switchSel(providers().length - 1);
  }

  function selectOrAddCli(protocol: string, label: string) {
    const idx = providers().findIndex((p) => p.protocol === protocol);
    if (idx >= 0) {
      switchSel(idx);
      return;
    }
    setProviders((prev) => [...prev, { ...newProvider(nextCustomId()), name: label, protocol }]);
    switchSel(providers().length - 1);
  }

  function removeCurrent() {
    setProviders((prev) => prev.filter((_, i) => i !== sel()));
    switchSel(Math.max(0, Math.min(sel(), providers().length - 2)));
  }

  // ---------- 验证地址 / 验证协议：实现收敛于 use-provider-verify ----------

  // ---------- CLI 操作：实现收敛于 use-cli-ops ----------
  // ---------- 拉取模型：实现收敛于 use-model-fetch ----------

  // ---------- 模型行编辑 ----------
  function patchModel(kind: ModelKind, idx: number, value: string) {
    setProviders((prev) => prev.map((p, i) => {
      if (i !== sel()) return p;
      const list = [...(p[kind] || [])];
      list[idx] = value;
      return { ...p, [kind]: list };
    }));
  }
  function removeModel(kind: ModelKind, idx: number) {
    setProviders((prev) => prev.map((p, i) => {
      if (i !== sel()) return p;
      return { ...p, [kind]: (p[kind] || []).filter((_, j) => j !== idx) };
    }));
  }
  function addModel(kind: ModelKind) {
    setProviders((prev) => prev.map((p, i) => (i === sel() ? { ...p, [kind]: [...(p[kind] || []), ''] } : p)));
  }

  /** 子组件共享 API（状态与动作的唯一出口） */
  const api: SettingsApi = {
    current, providers, sel, proto, isCli, imageMode,
    keyInput, setKeyInput, rhCoin, setRhCoin, rhWallet, setRhWallet,
    verifyResult: verify.verifyResult, cliStatus: cli.cliStatus, patch, saveAll,
    switchSel, addProvider, selectOrAddCli, removeCurrent,
    commitKey: () => void commitKey(), clearKey: () => void clearKey(),
    verifyAddress: () => void verify.verifyAddress(), verifyProtocol: () => void verify.verifyProtocol(),
    patchModel, removeModel, addModel,
    fetchModels: () => void mf.fetchModels(),
    jimengLogin: () => void cli.jimengLogin(), jimengCredit: () => void cli.jimengCredit(),
    jimengLogout: () => void cli.jimengLogout(),
    refreshCliStatus: cli.refreshCliStatus, cliHelp: (t, h) => void cli.cliHelp(t, h),
  };

  return (
    <div class="global-settings-view">
      <div class="aps-wrap">
        <A href="/" class="gs-back" title="返回影视工作台"><FiArrowLeft size={14} /></A>
        <header class="aps-page-head">
          <h1>API 设置</h1>
          <p>管理平台地址、模型列表和 Key。Key 写入后端 env，页面不会回显完整内容。</p>
        </header>

        <Show when={!loading()} fallback={<div class="gs-loading">加载供应商…</div>}>
          <div class="aps-cols">
            {/* 左：平台列表（滚轮滑动）+ CLI 设置 */}
            <SettingsSidePanel api={api} />

            {/* 右：选中平台详情（画布同款按平台定制内容） */}
            <Show when={current()}>
              <ProviderDetail api={api} />
            </Show>
          </div>
        </Show>
      </div>

      {/* CLI 输出弹窗（帮助/积分/扫码登录） */}
      <Show when={cli.cliModal()}>
        <CliModal modal={() => cli.cliModal()!} onClose={() => cli.setCliModal(null)} />
      </Show>

      {/* 拉取模型弹窗 */}
      <Show when={mf.fetched()}>
        <FetchModelsModal
          fetched={() => mf.fetched()!}
          savedCats={mf.savedCats}
          onApply={mf.applyFetched}
          onClose={mf.closeFetched}
        />
      </Show>
    </div>
  );
}
