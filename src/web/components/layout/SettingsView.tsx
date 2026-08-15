import { createSignal, For, Show, onMount, onCleanup } from 'solid-js';
import { A } from '@solidjs/router';
import {
  FiArrowLeft, FiCheck, FiDownload, FiExternalLink, FiKey, FiPlus, FiTrash2, FiX, FiZap,
} from 'solid-icons/fi';
import { getProviders } from '@/api/providers';
import { apiFetch, apiPost, apiPut, getGlobalApiKey, setGlobalApiKey } from '@/api/client';
import { showToast } from '@/stores/toast';
import type { ApiProvider } from '@/types';

/**
 * API 配置页（画布同款功能与布局，用户裁决 2026-08-16：modelscope/runninghub/
 * 火山引擎/CLI 的内容块与画布一模一样；去「推荐API」）。
 * 后端：PUT /api/providers（api_key/clear_key/wallet_api_key/clear_wallet_key → API/.env）、
 * fetch-models（自动分类）、test-connection（验证地址）、probe-async（验证协议）、
 * /api/{gemini-cli,codex,jimeng}/status|help、/api/jimeng/login/*|logout|credit。
 */

interface EditableProvider extends ApiProvider {
  api_key?: string;
  has_key?: boolean;
  key_preview?: string;
  key_env?: string;
  has_wallet_key?: boolean;
  wallet_key_preview?: string;
  wallet_key_env?: string;
}

const PROTOCOL_OPTIONS = [
  { value: 'openai', label: 'OpenAI 兼容 / 直连' },
  { value: 'apimart', label: '异步协议 (APIMart)' },
  { value: 'gemini', label: 'Gemini 协议' },
  { value: 'volcengine', label: '方舟/Ark 任务协议' },
  { value: 'runninghub', label: 'RunningHub OpenAPI' },
  { value: 'jimeng', label: '即梦 CLI' },
  { value: 'codex', label: 'OpenAI Codex CLI' },
  { value: 'gemini-cli', label: 'Antigravity CLI' },
  { value: 'mock', label: 'Mock（本地演示）' },
];

const CLI_PROTOCOLS = new Set(['jimeng', 'codex', 'gemini-cli']);
/** 图片接口模式（画布同款五档，持久化在 provider.image_request_mode） */
const IMAGE_MODE_OPTIONS = [
  { value: 'openai', label: '图片: OpenAI 标准' },
  { value: 'openai-json', label: '图片: OpenAI JSON' },
  { value: 'openai-video-proxy', label: '图片: OpenAI 中转' },
  { value: 'openai-responses', label: '图片: OpenAI RS' },
  { value: 'tudou-async', label: '图片: 土豆 GPT-Image-2 异步' },
];
const imageModeLabel = (v: string) => IMAGE_MODE_OPTIONS.find((o) => o.value === v)?.label || v;
/** 内置平台（画布不显示删除按钮） */
const BUILTIN_IDS = new Set(['modelscope', 'runninghub', 'volcengine', 'mock']);

const CLI_ENTRIES = [
  { key: 'jimeng', label: '即梦 CLI', protocol: 'jimeng', statusPath: '/api/jimeng/status', helpPath: '/api/jimeng/help' },
  { key: 'codex', label: 'GPT CLI (Codex)', protocol: 'codex', statusPath: '/api/codex/status', helpPath: '/api/codex/help' },
  { key: 'agy', label: 'Antigravity CLI', protocol: 'gemini-cli', statusPath: '/api/gemini-cli/status', helpPath: '/api/gemini-cli/help' },
];

const CLI_META: Record<string, { title: string; desc: string }> = {
  'gemini-cli': { title: 'Antigravity CLI 账户', desc: '使用本机 agy 登录态，无需在本项目保存 API Key。需要先安装 CLI 文件夹中的依赖。' },
  codex: { title: 'OpenAI CLI 账户', desc: '使用本机 codex 登录态，无需在本项目保存 API Key。' },
  jimeng: { title: '即梦 CLI 账户', desc: '使用本机 dreamina 登录态，无需 API Key。' },
};

/** 画布同款平台定制内容 */
const PLATFORM_META: Record<string, {
  defaultUrls?: Array<[string, string]>;
  tokenLinks?: Array<[string, string]>;
  note?: string;
}> = {
  modelscope: {
    defaultUrls: [
      ['国内默认请求地址', 'https://api-inference.modelscope.cn/v1'],
      ['国外使用请求地址', 'https://api-inference.modelscope.ai/v1'],
    ],
    tokenLinks: [
      ['获取 Token · 国内', 'https://www.modelscope.cn/my/access/token'],
      ['获取 Token · 国外', 'https://www.modelscope.ai/my/access/token'],
    ],
  },
  volcengine: {
    defaultUrls: [['方舟默认请求地址', 'https://ark.cn-beijing.volces.com/api/v3']],
    note: 'Seedance 视频生成使用方舟 API Key，验证会请求 /api/v3/models。',
  },
};

const RH_GUIDE = {
  title: 'RunningHub 新手引导',
  desc: 'RH 有 RH币和账户余额两种 Key：应用/工作流可用 RH币，标准模型只能走账户余额。',
  coinUrl: 'https://www.runninghub.ai/enterprise-api/consumerApi?inviteCode=rh-v1331',
  walletUrl: 'https://www.runninghub.ai/enterprise-api/sharedApi?inviteCode=rh-v1331',
};

type ModelKind = 'chat_models' | 'image_models' | 'video_models';
type ModelCat = 'image' | 'chat' | 'video';

interface FetchedModels {
  all: string[]; image_models: string[]; chat_models: string[]; video_models: string[];
  total: number; protocol: string;
}

function newProvider(id: string): EditableProvider {
  return {
    id, name: '', protocol: 'openai', base_url: '',
    enabled: true, chat_models: [], image_models: [], video_models: [],
    api_key: '', has_key: false,
  };
}

export default function SettingsView() {
  const [providers, setProviders] = createSignal<EditableProvider[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [sel, setSel] = createSignal(0);
  const [cliStatus, setCliStatus] = createSignal<Record<string, { installed: boolean; message: string }>>({});

  // Key 输入（每平台独立缓冲，切换平台重置）
  const [keyInput, setKeyInput] = createSignal('');
  const [rhCoin, setRhCoin] = createSignal('');
  const [rhWallet, setRhWallet] = createSignal('');
  // 验证结果内联显示（画布同款：点击验证后直接在卡片底部展示，不用 toast）
  const [verifyResult, setVerifyResult] = createSignal<{ ok: boolean; text: string } | null>(null);

  // CLI 弹窗（帮助/积分/登录输出）
  const [cliModal, setCliModal] = createSignal<{ title: string; text: string; qr_url?: string } | null>(null);
  let loginTimer: ReturnType<typeof setInterval> | undefined;

  // 拉取模型弹窗
  const [fetched, setFetched] = createSignal<FetchedModels | null>(null);
  const [checked, setChecked] = createSignal<Set<string>>(new Set());
  const [mSearch, setMSearch] = createSignal('');
  const [mTab, setMTab] = createSignal<'all' | ModelCat>('all');

  onMount(async () => {
    await reload();
    const statuses: Record<string, { installed: boolean; message: string }> = {};
    await Promise.all(CLI_ENTRIES.map(async (c) => {
      try {
        const s = await apiFetch<{ installed?: boolean; message?: string }>(c.statusPath);
        statuses[c.key] = { installed: !!s.installed, message: s.message || '' };
      } catch {
        statuses[c.key] = { installed: false, message: '检测失败' };
      }
    }));
    setCliStatus(statuses);
  });

  onCleanup(() => { if (loginTimer) clearInterval(loginTimer); });

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
    setVerifyResult(null);
  }

  function patch(field: string, value: unknown) {
    setProviders((prev) => prev.map((p, i) => (i === sel() ? { ...p, [field]: value } : p)));
  }

  /** 保存全部（可给当前平台附加覆盖字段，如 api_key/clear_key/wallet_api_key） */
  async function saveAll(overrides?: Record<string, unknown>) {
    const list = providers().map((p, i) => {
      const base: Record<string, unknown> = {
        id: p.id, name: p.name, protocol: p.protocol, base_url: p.base_url, enabled: p.enabled,
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

  async function addProvider() {
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

  // ---------- 验证地址 / 验证协议（画布同款：结果内联在卡片底部） ----------
  async function verifyAddress() {
    const p = current();
    if (!p) return;
    try {
      const r = await apiPost<{ ok: boolean; status: number; message: string; model_count: number; image_request_mode?: string }>(
        '/api/providers/test-connection',
        { base_url: p.base_url, api_key: keyInput() || '', provider_id: p.id, protocol: p.protocol, image_request_mode: imageMode() },
      );
      if (r.ok) {
        setVerifyResult({
          ok: true,
          text: `地址验证通过 - 找到 ${r.model_count} 个模型 - 图片接口: ${imageModeLabel(r.image_request_mode || imageMode())}`,
        });
      } else {
        setVerifyResult({ ok: false, text: `地址验证失败: ${r.message}` });
      }
    } catch (e) {
      setVerifyResult({ ok: false, text: `地址验证失败: ${(e as Error).message}` });
    }
  }

  async function verifyProtocol() {
    const p = current();
    if (!p) return;
    try {
      const r = await apiPost<{ ok: boolean | null; protocol: string; message: string }>(
        '/api/providers/probe-async',
        { base_url: p.base_url, api_key: keyInput() || '', provider_id: p.id, protocol: p.protocol, image_request_mode: imageMode() },
      );
      setVerifyResult({ ok: r.ok !== false, text: r.message || `协议识别：${r.protocol}` });
      if (r.ok && r.protocol && r.protocol !== p.protocol) patch('protocol', r.protocol);
    } catch (e) {
      setVerifyResult({ ok: false, text: `协议验证失败: ${(e as Error).message}` });
    }
  }

  // ---------- CLI 操作 ----------
  async function refreshCliStatus(key: string, statusPath: string) {
    try {
      const s = await apiFetch<{ installed?: boolean; message?: string }>(statusPath);
      setCliStatus((prev) => ({ ...prev, [key]: { installed: !!s.installed, message: s.message || '' } }));
      return !!s.installed;
    } catch {
      return false;
    }
  }

  async function cliHelp(title: string, helpPath: string) {
    try {
      const r = await apiPost<{ ok?: boolean; output?: string }>(helpPath, { command: '' });
      setCliModal({ title: `${title} · 帮助`, text: r.output || '(无输出)' });
    } catch (e) {
      showToast(`帮助获取失败：${(e as Error).message}`, 'error');
    }
  }

  async function jimengCredit() {
    try {
      const r = await apiFetch<{ ok: boolean; text?: string; message?: string }>('/api/jimeng/credit');
      if (r.ok) setCliModal({ title: '即梦账户积分', text: r.text || '(无输出)' });
      else showToast(r.message || '查询失败', 'error');
    } catch (e) {
      showToast(`查询积分失败：${(e as Error).message}`, 'error');
    }
  }

  async function jimengLogout() {
    try {
      const r = await apiPost<{ ok: boolean; message: string }>('/api/jimeng/logout', {});
      showToast(r.message, r.ok ? 'success' : 'error');
      await refreshCliStatus('jimeng', '/api/jimeng/status');
    } catch (e) {
      showToast(`登出失败：${(e as Error).message}`, 'error');
    }
  }

  async function jimengLogin() {
    try {
      const r = await apiPost<{ ok: boolean; message: string }>('/api/jimeng/login/start', {});
      if (!r.ok) {
        showToast(r.message, 'error');
        return;
      }
      setCliModal({ title: '即梦扫码登录', text: '正在启动 dreamina login…' });
      if (loginTimer) clearInterval(loginTimer);
      loginTimer = setInterval(async () => {
        try {
          const s = await apiFetch<{ running: boolean; text: string; qr_url?: string }>('/api/jimeng/login/status');
          setCliModal({
            title: '即梦扫码登录',
            text: s.text || '等待输出…（按终端提示扫码）',
            qr_url: s.qr_url,
          });
          if (!s.running) {
            clearInterval(loginTimer);
            loginTimer = undefined;
            await refreshCliStatus('jimeng', '/api/jimeng/status');
          }
        } catch { /* 轮询静默 */ }
      }, 1500);
    } catch (e) {
      showToast(`启动登录失败：${(e as Error).message}`, 'error');
    }
  }

  // ---------- 拉取模型弹窗 ----------
  async function fetchModels() {
    const p = current();
    if (!p) return;
    try {
      const data = await apiPost<FetchedModels & { error?: string }>(
        '/api/providers/fetch-models',
        { base_url: p.base_url, api_key: keyInput() || '', provider_id: p.id, protocol: p.protocol },
      );
      if (data.error || !(data.all || []).length) {
        showToast(`拉取模型失败：${data.error || '上游未返回模型'}`, 'error');
        return;
      }
      setFetched(data);
      setChecked(new Set(data.all));
      setMSearch('');
      setMTab('all');
    } catch (e) {
      showToast(`拉取模型失败：${(e as Error).message}`, 'error');
    }
  }

  const catOf = (m: string): ModelCat => {
    const f = fetched();
    if (!f) return 'chat';
    if (f.image_models.includes(m)) return 'image';
    if (f.video_models.includes(m)) return 'video';
    return 'chat';
  };
  const catLabel: Record<ModelCat, string> = { image: '生图', chat: 'LLM', video: '视频' };
  const modalRows = () => {
    const f = fetched();
    if (!f) return [] as string[];
    const q = mSearch().trim().toLowerCase();
    return f.all.filter((m) => (!q || m.toLowerCase().includes(q)) && (mTab() === 'all' || catOf(m) === mTab()));
  };
  const catCount = (cat: ModelCat | 'all') => {
    const f = fetched();
    if (!f) return { on: 0, total: 0 };
    const list = cat === 'all' ? f.all : f.all.filter((m) => catOf(m) === cat);
    return { on: list.filter((m) => checked().has(m)).length, total: list.length };
  };
  function toggleChecked(m: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(m)) next.delete(m); else next.add(m);
      return next;
    });
  }
  function applyFetched() {
    const f = fetched();
    if (!f) return;
    const picked = {
      image: f.all.filter((m) => catOf(m) === 'image' && checked().has(m)),
      chat: f.all.filter((m) => catOf(m) === 'chat' && checked().has(m)),
      video: f.all.filter((m) => catOf(m) === 'video' && checked().has(m)),
    };
    patch('image_models', picked.image);
    patch('chat_models', picked.chat);
    patch('video_models', picked.video);
    setFetched(null);
    showToast(`已应用到模型列表（生图 ${picked.image.length} / LLM ${picked.chat.length} / 视频 ${picked.video.length}）`, 'success');
  }

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

  /** API Key 行（画布同款：输入 + ✓ 提交 + 🗑 清除 + env 名提示） */
  function KeyRow() {
    const p = () => current();
    return (
      <>
        <div class="aps-field">
          <span>API Key</span>
          <div class="aps-keyrow">
            <input
              type="password" class="aps-input mono" value={keyInput()}
              placeholder={p()!.has_key ? `保持当前 Key ${p()!.key_preview || '••••••••'}` : `输入${p()!.name || '平台'} API Key`}
              onInput={(e) => setKeyInput(e.currentTarget.value)}
            />
            <button type="button" class="aps-icon-btn" title="保存 Key 到 API/.env" onClick={() => void commitKey()}>
              <FiCheck size={14} />
            </button>
            <button type="button" class="aps-icon-btn" title="清除已保存的 Key" onClick={() => void clearKey()}>
              <FiTrash2 size={13} />
            </button>
          </div>
        </div>
        <div class="aps-keynote">
          {p()!.has_key
            ? `当前 Key 已保存：${p()!.key_env || 'API/.env'}`
            : `还没有保存 ${p()!.name || '该平台'} API Key。`}
        </div>
      </>
    );
  }

  /** 模型分区卡片 */
  function ModelCard(props: { title: string; desc: string; kind: ModelKind }) {
    return (
      <div class="aps-card">
        <div class="aps-card-head">
          <div>
            <div class="aps-sec-title">{props.title}</div>
            <div class="aps-sec-desc">{props.desc}</div>
          </div>
          <button type="button" class="aps-btn" onClick={() => addModel(props.kind)}>
            <FiPlus size={12} /> 模型
          </button>
        </div>
        <Show when={(current()?.[props.kind] || []).length > 0} fallback={<div class="aps-empty">暂无模型</div>}>
          <For each={current()?.[props.kind] || []}>
            {(m, idx) => (
              <div class="aps-model-row">
                <input
                  class="aps-input mono" value={m} placeholder="模型名"
                  onInput={(e) => patchModel(props.kind, idx(), e.currentTarget.value)}
                />
                <button type="button" class="aps-icon-btn" title="删除该模型" onClick={() => removeModel(props.kind, idx())}>
                  <FiTrash2 size={13} />
                </button>
              </div>
            )}
          </For>
        </Show>
      </div>
    );
  }

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
            <aside class="aps-side">
              <div class="aps-side-label">平台列表</div>
              <div class="aps-side-list">
                <For each={providers()}>
                  {(p, i) => (
                    <button
                      type="button" class={`aps-item ${i() === sel() ? 'active' : ''}`}
                      onClick={() => switchSel(i())}
                    >
                      <div class="aps-item-main">
                        <span class="aps-item-name">{p.name || '未命名平台'}</span>
                        <span class="aps-item-sub">{p.base_url || '未配置地址'}</span>
                      </div>
                      <Show when={p.protocol}>
                        <span class="aps-badge">{String(p.protocol).toUpperCase()}</span>
                      </Show>
                    </button>
                  )}
                </For>
              </div>
              <button type="button" class="aps-add" onClick={() => void addProvider()}>
                <FiPlus size={12} /> 新增平台
              </button>

              <div class="aps-side-label aps-cli-label">CLI 设置</div>
              <For each={CLI_ENTRIES}>
                {(c) => (
                  <button
                    type="button" class="aps-cli-item" title={cliStatus()[c.key]?.message || '点击选择/新建该 CLI 平台'}
                    onClick={() => selectOrAddCli(c.protocol, c.label)}
                  >
                    <span class="aps-item-name">{c.label}</span>
                    <span class={`aps-cli-badge ${cliStatus()[c.key]?.installed ? 'on' : ''}`}>
                      {cliStatus()[c.key]?.installed ? '已就绪' : '未安装'}
                    </span>
                  </button>
                )}
              </For>
              <div class="aps-cli-note">CLI 平台无需请求地址；未安装时请先装好对应 CLI 依赖。</div>
            </aside>

            {/* 右：选中平台详情（画布同款按平台定制内容） */}
            <Show when={current()}>
              <section class="aps-detail">
                <div class="aps-card aps-head-card">
                  <div>
                    <div class="aps-title">{current()!.name || '未命名平台'}</div>
                    <div class="aps-sub">配置基础信息、API Key 和可用模型</div>
                  </div>
                  <div class="aps-head-actions">
                    <Show when={!BUILTIN_IDS.has(current()!.id)}>
                      <button type="button" class="aps-btn danger" onClick={removeCurrent}>
                        <FiTrash2 size={12} /> 删除
                      </button>
                    </Show>
                    <button type="button" class="aps-btn light" onClick={() => void saveAll()}>
                      <FiCheck size={12} /> 保存
                    </button>
                  </div>
                </div>

                <div class="aps-card">
                  <div class="aps-sec-title">基本信息</div>
                  <div class="aps-sec-desc">平台显示名、唯一 ID 和请求地址</div>
                  <label class="aps-field">
                    <span>平台名称</span>
                    <input
                      class="aps-input" value={current()!.name || ''} placeholder="供应商显示名"
                      onInput={(e) => patch('name', e.currentTarget.value)}
                    />
                  </label>
                  <div class="aps-idline">平台 ID: <code>{current()!.id}</code>（自动分配，不可编辑）</div>

                  {/* RunningHub 新手引导（画布同款双 Key） */}
                  <Show when={current()!.id === 'runninghub'}>
                    <div class="aps-guide">
                      <div class="aps-guide-head">
                        <div>
                          <div class="aps-sec-title">{RH_GUIDE.title}</div>
                          <div class="aps-sec-desc">{RH_GUIDE.desc}</div>
                        </div>
                        <span class="aps-badge">NEW</span>
                      </div>
                      <div class="aps-guide-row">
                        <div class="aps-guide-box">
                          <span class="aps-guide-label">RH币 Key</span>
                          <a class="aps-btn" href={RH_GUIDE.coinUrl} target="_blank" rel="noopener noreferrer">
                            <FiKey size={12} /> 获取 Key
                          </a>
                        </div>
                        <div class="aps-guide-arrow">----</div>
                        <div class="aps-guide-box">
                          <span class="aps-guide-label">RH币 API Key · 必填</span>
                          <input
                            type="password" class="aps-input mono" value={rhCoin()}
                            placeholder={current()!.has_key ? `保持当前 Key ${current()!.key_preview || ''}` : '粘贴 RH币 API Key'}
                            onInput={(e) => setRhCoin(e.currentTarget.value)}
                          />
                        </div>
                      </div>
                      <div class="aps-guide-row">
                        <div class="aps-guide-box">
                          <span class="aps-guide-label">账户余额 Key</span>
                          <a class="aps-btn" href={RH_GUIDE.walletUrl} target="_blank" rel="noopener noreferrer">
                            <FiKey size={12} /> 获取余额 Key
                          </a>
                        </div>
                        <div class="aps-guide-arrow">----</div>
                        <div class="aps-guide-box">
                          <span class="aps-guide-label">账户余额 API Key · 标准模型必填</span>
                          <input
                            type="password" class="aps-input mono" value={rhWallet()}
                            placeholder={current()!.has_wallet_key ? `保持当前 Key ${current()!.wallet_key_preview || ''}` : '标准模型/视频模型请粘贴这个 Key'}
                            onInput={(e) => setRhWallet(e.currentTarget.value)}
                          />
                        </div>
                      </div>
                      <div class="aps-guide-save">
                        <button
                          type="button" class="aps-btn light"
                          onClick={() => void saveAll({
                            ...(rhCoin().trim() ? { api_key: rhCoin().trim() } : {}),
                            ...(rhWallet().trim() ? { wallet_api_key: rhWallet().trim() } : {}),
                          }).then((ok) => { if (ok) { setRhCoin(''); setRhWallet(''); } })}
                        >
                          <FiCheck size={12} /> 保存
                        </button>
                      </div>
                      <div class="aps-keynote">
                        {current()!.has_wallet_key
                          ? `余额 Key 已保存：${current()!.wallet_key_env}`
                          : '还没有保存方舟/RH 余额 API Key。'}
                      </div>
                    </div>
                  </Show>

                  {/* CLI 账户卡（画布同款） */}
                  <Show when={isCli()}>
                    <div class="aps-cli-account">
                      <div class="aps-guide-head">
                        <div>
                          <div class="aps-sec-title">{CLI_META[proto()]?.title || 'CLI 账户'}</div>
                          <div class="aps-sec-desc">{CLI_META[proto()]?.desc || ''}</div>
                        </div>
                        <span class={`aps-cli-badge ${cliStatus()[proto() === 'gemini-cli' ? 'agy' : proto()]?.installed ? 'on' : 'warn'}`}>
                          {cliStatus()[proto() === 'gemini-cli' ? 'agy' : proto()]?.installed ? '已安装' : '未安装'}
                        </span>
                      </div>
                      <div class="aps-verify-row">
                        <Show when={proto() === 'jimeng'}>
                          <button type="button" class="aps-btn" onClick={() => void jimengLogin()}>扫码登录</button>
                          <button type="button" class="aps-btn" onClick={() => void jimengCredit()}>查询积分</button>
                        </Show>
                        <button
                          type="button" class="aps-btn"
                          onClick={() => void (async () => {
                            const entry = CLI_ENTRIES.find((c) => c.protocol === proto());
                            if (!entry) return;
                            const ok = await refreshCliStatus(entry.key, entry.statusPath);
                            showToast(ok ? 'CLI 已就绪' : 'CLI 未安装', ok ? 'success' : 'error');
                          })()}
                        >
                          检测 CLI
                        </button>
                        <button
                          type="button" class="aps-btn"
                          onClick={() => void (async () => {
                            const entry = CLI_ENTRIES.find((c) => c.protocol === proto());
                            if (entry) await cliHelp(entry.label, entry.helpPath);
                          })()}
                        >
                          帮助
                        </button>
                        <Show when={proto() === 'jimeng'}>
                          <button type="button" class="aps-btn danger" onClick={() => void jimengLogout()}>退出登录</button>
                        </Show>
                      </div>
                    </div>
                  </Show>

                  {/* 非 CLI：请求地址 + 平台定制提示 + Key 行 */}
                  <Show when={!isCli()}>
                    <label class="aps-field">
                      <span>请求地址</span>
                      <input
                        class="aps-input mono" value={current()!.base_url || ''} placeholder="https://…"
                        onInput={(e) => patch('base_url', e.currentTarget.value.trim())}
                      />
                    </label>
                    <Show when={PLATFORM_META[current()!.id]?.defaultUrls}>
                      <For each={PLATFORM_META[current()!.id]?.defaultUrls || []}>
                        {([label, url]) => (
                          <div class="aps-chipline">
                            <span>{label}：</span><code>{url}</code>
                          </div>
                        )}
                      </For>
                    </Show>
                    <Show when={PLATFORM_META[current()!.id]?.note}>
                      <div class="aps-keynote">{PLATFORM_META[current()!.id]?.note}</div>
                    </Show>
                    <Show when={current()!.id !== 'runninghub'}>
                      <KeyRow />
                    </Show>
                    <Show when={PLATFORM_META[current()!.id]?.tokenLinks}>
                      <For each={PLATFORM_META[current()!.id]?.tokenLinks || []}>
                        {([label, url]) => (
                          <div class="aps-chipline">
                            <span>{label}：</span>
                            <a href={url} target="_blank" rel="noopener noreferrer">{url}</a>
                          </div>
                        )}
                      </For>
                    </Show>
                  </Show>

                  <label class="aps-field">
                    <span>启用状态</span>
                    <label class="aps-toggle">
                      <input
                        type="checkbox" checked={!!current()!.enabled}
                        onChange={(e) => patch('enabled', e.currentTarget.checked)}
                      />
                      {current()!.enabled ? '已启用（参与生成渠道候选）' : '已停用'}
                    </label>
                  </label>

                  {/* 验证行（画布同款）：验证地址/验证协议 + 协议下拉 + 图片接口模式下拉 */}
                  <div class="aps-verify-row">
                    <button type="button" class="aps-btn" onClick={() => void verifyAddress()}>
                      <FiZap size={12} /> 验证地址
                    </button>
                    <Show when={!isCli()}>
                      <button type="button" class="aps-btn" onClick={() => void verifyProtocol()}>
                        <FiCheck size={12} /> 验证协议
                      </button>
                    </Show>
                    <select
                      class="aps-input aps-select-inline" value={current()!.protocol || 'openai'}
                      onChange={(e) => patch('protocol', e.currentTarget.value)}
                    >
                      <Show when={!PROTOCOL_OPTIONS.some((o) => o.value === (current()!.protocol || 'openai'))}>
                        <option value={current()!.protocol || ''}>
                          {current()!.protocol ? `其它：${current()!.protocol}` : '请选择协议'}
                        </option>
                      </Show>
                      <For each={PROTOCOL_OPTIONS}>
                        {(o) => <option value={o.value}>{o.label}</option>}
                      </For>
                    </select>
                    <Show when={!isCli()}>
                      <select
                        class="aps-input aps-select-inline" value={imageMode()}
                        onChange={(e) => patch('image_request_mode', e.currentTarget.value)}
                      >
                        <Show when={!IMAGE_MODE_OPTIONS.some((o) => o.value === imageMode())}>
                          <option value={imageMode()}>其它：{imageMode()}</option>
                        </Show>
                        <For each={IMAGE_MODE_OPTIONS}>
                          {(o) => <option value={o.value}>{o.label}</option>}
                        </For>
                      </select>
                    </Show>
                  </div>
                  {/* 验证结果内联（画布同款：直接在底部展示） */}
                  <Show when={verifyResult()}>
                    <div class={`aps-verify-result ${verifyResult()!.ok ? 'ok' : 'err'}`}>
                      {verifyResult()!.ok ? '✓ ' : '✗ '}{verifyResult()!.text}
                    </div>
                  </Show>
                </div>

                <div class="aps-card">
                  <div class="aps-card-head">
                    <div>
                      <div class="aps-sec-title">模型列表</div>
                      <div class="aps-sec-desc">从上游 API 自动拉取所有可用模型并按类型分类（image / chat / video）</div>
                    </div>
                    <button type="button" class="aps-btn light" onClick={() => void fetchModels()}>
                      <FiDownload size={12} /> 拉取模型
                    </button>
                  </div>
                </div>

                <ModelCard title="生图模型" desc="在线生图和无限画布 API 生成使用。" kind="image_models" />
                <ModelCard title="聊天模型" desc="GPT 对话和 LLM 节点使用。" kind="chat_models" />
                <ModelCard title="视频模型" desc="无限画布视频生成节点使用。" kind="video_models" />

                <div class="aps-card">
                  <div class="aps-sec-title"><FiKey size={12} /> 安全说明（生产环境）</div>
                  <div class="aps-sec-desc">
                    生产环境（ENVIRONMENT=production）下 /api/ 请求需携带 X-API-Key 头；
                    此处填写的全局密钥会被前端所有 /api 请求自动携带（存于浏览器 localStorage）。
                  </div>
                  <label class="aps-field">
                    <span>全局 X-API-Key（留空 = 不携带）</span>
                    <input
                      type="password" class="aps-input mono" value={getGlobalApiKey()}
                      placeholder="与后端 API_KEY 环境变量一致"
                      onInput={(e) => setGlobalApiKey(e.currentTarget.value)}
                    />
                  </label>
                </div>
              </section>
            </Show>
          </div>
        </Show>
      </div>

      {/* CLI 输出弹窗（帮助/积分/扫码登录） */}
      <Show when={cliModal()}>
        <div class="aps-modal-mask" onClick={() => setCliModal(null)}>
          <div class="aps-modal" onClick={(e) => e.stopPropagation()}>
            <div class="aps-modal-head">
              <div class="aps-sec-title">{cliModal()!.title}</div>
              <button type="button" class="aps-icon-btn" title="关闭" onClick={() => setCliModal(null)}>
                <FiX size={14} />
              </button>
            </div>
            <div class="aps-cli-output">
              <Show when={cliModal()!.qr_url}>
                <a class="aps-btn light" href={cliModal()!.qr_url} target="_blank" rel="noopener noreferrer">
                  <FiExternalLink size={12} /> 打开登录链接
                </a>
              </Show>
              <pre>{cliModal()!.text}</pre>
            </div>
          </div>
        </div>
      </Show>

      {/* 拉取模型弹窗 */}
      <Show when={fetched()}>
        <div class="aps-modal-mask" onClick={() => setFetched(null)}>
          <div class="aps-modal" onClick={(e) => e.stopPropagation()}>
            <div class="aps-modal-head">
              <div>
                <div class="aps-sec-title">从上游拉取的模型清单</div>
                <div class="aps-sec-desc">共 {fetched()!.total} 个模型 · 协议 {fetched()!.protocol} · 勾选后应用到模型列表</div>
              </div>
              <button type="button" class="aps-icon-btn" title="关闭" onClick={() => setFetched(null)}>
                <FiX size={14} />
              </button>
            </div>
            <div class="aps-modal-tools">
              <input
                class="aps-input aps-modal-search" placeholder="按名称搜索模型…"
                value={mSearch()} onInput={(e) => setMSearch(e.currentTarget.value)}
              />
              <button type="button" class={`aps-tab ${mTab() === 'all' ? 'active' : ''}`} onClick={() => setMTab('all')}>
                全部 {catCount('all').on}/{catCount('all').total}
              </button>
              <button type="button" class={`aps-tab ${mTab() === 'image' ? 'active' : ''}`} onClick={() => setMTab('image')}>
                生图 {catCount('image').on}/{catCount('image').total}
              </button>
              <button type="button" class={`aps-tab ${mTab() === 'chat' ? 'active' : ''}`} onClick={() => setMTab('chat')}>
                LLM {catCount('chat').on}/{catCount('chat').total}
              </button>
              <button type="button" class={`aps-tab ${mTab() === 'video' ? 'active' : ''}`} onClick={() => setMTab('video')}>
                视频 {catCount('video').on}/{catCount('video').total}
              </button>
            </div>
            <div class="aps-modal-list">
              <Show when={modalRows().length > 0} fallback={<div class="aps-empty">无匹配模型</div>}>
                <For each={modalRows()}>
                  {(m) => (
                    <label class="aps-mrow">
                      <input type="checkbox" checked={checked().has(m)} onChange={() => toggleChecked(m)} />
                      <span class="aps-mcat">{catLabel[catOf(m)]}</span>
                      <span class="aps-mname">{m}</span>
                    </label>
                  )}
                </For>
              </Show>
            </div>
            <div class="aps-modal-foot">
              <span class="aps-foot-label">将应用:</span>
              <span class="aps-apply-badge">生图 {catCount('image').on}</span>
              <span class="aps-apply-badge">LLM {catCount('chat').on}</span>
              <span class="aps-apply-badge">视频 {catCount('video').on}</span>
              <span class="aps-foot-unsel">未选 {catCount('all').total - catCount('all').on}</span>
              <span class="aps-foot-spacer" />
              <button type="button" class="aps-btn" onClick={() => setFetched(null)}>取消</button>
              <button type="button" class="aps-btn light" onClick={applyFetched}>应用到模型列表</button>
            </div>
          </div>
        </div>
      </Show>
    </div>
  );
}
