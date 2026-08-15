import { createSignal, For, Show, onMount } from 'solid-js';
import { A } from '@solidjs/router';
import { FiArrowLeft, FiCheck, FiDownload, FiKey, FiPlus, FiTrash2, FiX, FiZap } from 'solid-icons/fi';
import { getProviders } from '@/api/providers';
import { apiFetch, apiPut, apiPost, getGlobalApiKey, setGlobalApiKey } from '@/api/client';
import { showToast } from '@/stores/toast';
import type { ApiProvider } from '@/types';

/**
 * API 配置页（SPA 原生实现，画布 API 设置风格，用户裁决 2026-08-16）。
 * 左「平台列表」+「CLI 设置」侧栏（滚轮滑动）；右侧分区卡片。
 * 平台 ID 自动分配只读（custom-api-N，照画布）；验证地址/验证协议照搬画布；
 * 拉取模型 → 弹窗自动分类勾选 → 应用到模型列表（照画布流程）。
 * 后端：PUT /api/providers、fetch-models（自动分类）、test-connection（协议识别）、
 * /api/{gemini-cli,codex,jimeng}/status（CLI 检测）。
 */

interface EditableProvider extends ApiProvider {
  api_key?: string;
  has_key?: boolean;
}

const PROTOCOL_OPTIONS = [
  { value: 'openai', label: 'OpenAI 兼容 / 直连' },
  { value: 'gemini-cli', label: 'Antigravity CLI (agy)' },
  { value: 'codex', label: 'OpenAI Codex CLI' },
  { value: 'jimeng', label: '即梦 CLI (dreamina)' },
  { value: 'mock', label: 'Mock（本地演示）' },
];

const CLI_ENTRIES = [
  { key: 'jimeng', label: '即梦 CLI', protocol: 'jimeng', statusPath: '/api/jimeng/status' },
  { key: 'codex', label: 'GPT CLI (Codex)', protocol: 'codex', statusPath: '/api/codex/status' },
  { key: 'agy', label: 'Antigravity CLI', protocol: 'gemini-cli', statusPath: '/api/gemini-cli/status' },
];

type ModelKind = 'chat_models' | 'image_models' | 'video_models';
type ModelCat = 'image' | 'chat' | 'video';

interface FetchedModels {
  all: string[];
  image_models: string[];
  chat_models: string[];
  video_models: string[];
  total: number;
  protocol: string;
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

  // 拉取模型弹窗状态
  const [fetched, setFetched] = createSignal<FetchedModels | null>(null);
  const [checked, setChecked] = createSignal<Set<string>>(new Set());
  const [mSearch, setMSearch] = createSignal('');
  const [mTab, setMTab] = createSignal<'all' | ModelCat>('all');

  onMount(async () => {
    try {
      const data = await getProviders();
      setProviders(data.providers.map((p) => ({ ...p, api_key: '' })));
    } catch {
      showToast('加载供应商配置失败', 'error');
    } finally {
      setLoading(false);
    }
    // CLI 安装状态（侧栏「CLI 设置」，失败静默为未安装）
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

  const current = () => providers()[sel()];

  /** 平台 ID 自动分配（照画布 custom-api-N），不手动输入 */
  function nextCustomId(): string {
    let max = 0;
    for (const p of providers()) {
      const m = /^custom-api-(\d+)$/.exec(p.id || '');
      if (m) max = Math.max(max, parseInt(m[1], 10));
    }
    return `custom-api-${max + 1}`;
  }

  function patch(field: string, value: unknown) {
    setProviders((prev) => prev.map((p, i) => (i === sel() ? { ...p, [field]: value } : p)));
  }

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

  function addProvider() {
    setProviders((prev) => [...prev, newProvider(nextCustomId())]);
    setSel(providers().length - 1);
  }

  /** CLI 条目点击：已有同协议平台则选中，否则新建一个 CLI 平台 */
  function selectOrAddCli(protocol: string, label: string) {
    const idx = providers().findIndex((p) => p.protocol === protocol);
    if (idx >= 0) {
      setSel(idx);
      return;
    }
    setProviders((prev) => [...prev, { ...newProvider(nextCustomId()), name: label, protocol }]);
    setSel(providers().length - 1);
  }

  function removeCurrent() {
    setProviders((prev) => prev.filter((_, i) => i !== sel()));
    setSel(Math.max(0, Math.min(sel(), providers().length - 2)));
  }

  async function saveAll() {
    const list = providers().map((p) => ({
      id: p.id, name: p.name, protocol: p.protocol, base_url: p.base_url,
      enabled: p.enabled,
      chat_models: (p.chat_models || []).map((s) => s.trim()).filter(Boolean),
      image_models: (p.image_models || []).map((s) => s.trim()).filter(Boolean),
      video_models: (p.video_models || []).map((s) => s.trim()).filter(Boolean),
      api_key: p.api_key || undefined,
    }));
    try {
      const saved = await apiPut<{ providers: ApiProvider[] }>('/api/providers', { providers: list });
      const keepSel = sel();
      setProviders(saved.providers.map((p) => ({ ...p, api_key: '' })));
      setSel(Math.max(0, Math.min(keepSel, saved.providers.length - 1)));
      showToast('供应商配置已保存', 'success');
    } catch (e) {
      showToast(`保存失败：${(e as Error).message}`, 'error');
    }
  }

  /** 验证地址（画布同款）：HTTP 可达性 + 模型数 */
  async function verifyAddress() {
    const p = current();
    if (!p) return;
    try {
      const r = await apiPost<{ ok: boolean; status: number; message: string; model_count: number }>(
        '/api/providers/test-connection',
        { base_url: p.base_url, api_key: p.api_key || '', provider_id: p.id, protocol: p.protocol },
      );
      if (r.ok) showToast(`地址验证通过：HTTP ${r.status}，发现 ${r.model_count} 个模型`, 'success');
      else showToast(`地址验证失败：${r.message}`, 'error');
    } catch (e) {
      showToast(`地址验证失败：${(e as Error).message}`, 'error');
    }
  }

  /** 验证协议（画布同款）：协议识别结果与当前选择比对 */
  async function verifyProtocol() {
    const p = current();
    if (!p) return;
    try {
      const r = await apiPost<{ ok: boolean; protocol: string; message: string }>(
        '/api/providers/test-connection',
        { base_url: p.base_url, api_key: p.api_key || '', provider_id: p.id, protocol: p.protocol },
      );
      if (!r.ok) {
        showToast(`协议验证失败：${r.message}`, 'error');
        return;
      }
      const cur = (p.protocol || 'openai').toLowerCase();
      const same = r.protocol === cur || (cur === 'openai' && !['runninghub', 'volcengine'].includes(r.protocol));
      showToast(
        same
          ? `协议验证通过：识别为 ${r.protocol}`
          : `协议识别为 ${r.protocol}，与当前选择 ${cur} 不一致，请调整协议`,
        same ? 'success' : 'warning',
      );
    } catch (e) {
      showToast(`协议验证失败：${(e as Error).message}`, 'error');
    }
  }

  /** 拉取模型 → 弹窗（自动分类，勾选后应用，照画布流程） */
  async function fetchModels() {
    const p = current();
    if (!p) return;
    try {
      const data = await apiPost<FetchedModels & { error?: string }>(
        '/api/providers/fetch-models',
        { base_url: p.base_url, api_key: p.api_key || '', provider_id: p.id, protocol: p.protocol },
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
    return f.all.filter((m) => (!q || m.toLowerCase().includes(q))
      && (mTab() === 'all' || catOf(m) === mTab()));
  };

  const catCount = (cat: ModelCat | 'all') => {
    const f = fetched();
    if (!f) return { on: 0, total: 0 };
    const list = cat === 'all' ? f.all : f.all.filter((m) => catOf(m) === cat);
    const on = list.filter((m) => checked().has(m)).length;
    return { on, total: list.length };
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
    // 先算好三类清单再落盘/关弹窗（catOf 依赖 fetched，清空后不能再算）
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

  /** 模型分区卡片（生图/聊天/视频共用） */
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
        <Show
          when={(current()?.[props.kind] || []).length > 0}
          fallback={<div class="aps-empty">暂无模型</div>}
        >
          <For each={current()?.[props.kind] || []}>
            {(m, idx) => (
              <div class="aps-model-row">
                <input
                  class="aps-input mono" value={m} placeholder="模型名，如 qwen3-vl-plus"
                  onInput={(e) => patchModel(props.kind, idx(), e.currentTarget.value)}
                />
                <button
                  type="button" class="aps-icon-btn" title="删除该模型"
                  onClick={() => removeModel(props.kind, idx())}
                >
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
                      type="button"
                      class={`aps-item ${i() === sel() ? 'active' : ''}`}
                      onClick={() => setSel(i())}
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
              <button type="button" class="aps-add" onClick={addProvider}>
                <FiPlus size={12} /> 新增平台
              </button>

              <div class="aps-side-label aps-cli-label">CLI 设置</div>
              <For each={CLI_ENTRIES}>
                {(c) => (
                  <button
                    type="button" class="aps-cli-item"
                    title={cliStatus()[c.key]?.message || '点击选择/新建该 CLI 平台'}
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

            {/* 右：选中平台详情 */}
            <Show when={current()}>
              <section class="aps-detail">
                <div class="aps-card aps-head-card">
                  <div>
                    <div class="aps-title">{current()!.name || '未命名平台'}</div>
                    <div class="aps-sub">配置基础信息、API Key 和可用模型</div>
                  </div>
                  <div class="aps-head-actions">
                    <button type="button" class="aps-btn danger" onClick={removeCurrent}>
                      <FiTrash2 size={12} /> 删除
                    </button>
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
                  <label class="aps-field">
                    <span>请求地址</span>
                    <input
                      class="aps-input mono" value={current()!.base_url || ''} placeholder="https://…（CLI 协议无需填写）"
                      onInput={(e) => patch('base_url', e.currentTarget.value.trim())}
                    />
                  </label>
                  <div class="aps-row2">
                    <label class="aps-field">
                      <span>协议</span>
                      <select
                        class="aps-input" value={current()!.protocol || 'openai'}
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
                    </label>
                    <label class="aps-field aps-toggle-field">
                      <span>启用状态</span>
                      <label class="aps-toggle">
                        <input
                          type="checkbox" checked={!!current()!.enabled}
                          onChange={(e) => patch('enabled', e.currentTarget.checked)}
                        />
                        {current()!.enabled ? '已启用（参与生成渠道候选）' : '已停用'}
                      </label>
                    </label>
                  </div>
                  <label class="aps-field">
                    <span>API Key</span>
                    <input
                      type="password" class="aps-input mono" value={current()!.api_key || ''}
                      placeholder={current()!.has_key ? '保持当前 Key ••••••••' : '未配置'}
                      onInput={(e) => patch('api_key', e.currentTarget.value)}
                    />
                  </label>
                  <div class="aps-keynote">
                    点「保存」后 Key 写入项目 API/.env（不入库、不回显）；留空 = 保持现状。
                  </div>
                  <div class="aps-verify-row">
                    <button type="button" class="aps-btn" onClick={() => void verifyAddress()}>
                      <FiZap size={12} /> 验证地址
                    </button>
                    <button type="button" class="aps-btn" onClick={() => void verifyProtocol()}>
                      <FiCheck size={12} /> 验证协议
                    </button>
                  </div>
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

                <ModelCard title="生图模型" desc="图片生成节点使用。" kind="image_models" />
                <ModelCard title="聊天模型" desc="对话与规划 LLM 使用。" kind="chat_models" />
                <ModelCard title="视频模型" desc="分镜视频生成节点使用。" kind="video_models" />

                <div class="aps-card">
                  <div class="aps-sec-title"><FiKey size={12} /> 安全说明（生产环境）</div>
                  <div class="aps-sec-desc">
                    生产环境（ENVIRONMENT=production）下 /api/ 请求需携带 X-API-Key 头；
                    此处填写的全局密钥会被前端所有 /api 请求自动携带（存于浏览器 localStorage）。
                  </div>
                  <label class="aps-field">
                    <span>全局 X-API-Key（留空 = 不携带）</span>
                    <input
                      type="password" class="aps-input mono"
                      value={getGlobalApiKey()}
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

      {/* 拉取模型弹窗：自动分类 + 勾选 + 应用到模型列表（照画布流程） */}
      <Show when={fetched()}>
        <div class="aps-modal-mask" onClick={() => setFetched(null)}>
          <div class="aps-modal" onClick={(e) => e.stopPropagation()}>
            <div class="aps-modal-head">
              <div>
                <div class="aps-sec-title">从上游拉取的模型清单</div>
                <div class="aps-sec-desc">
                  共 {fetched()!.total} 个模型 · 协议 {fetched()!.protocol} · 勾选后应用到模型列表
                </div>
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
              <button
                type="button" class={`aps-tab ${mTab() === 'all' ? 'active' : ''}`}
                onClick={() => setMTab('all')}
              >
                全部 {catCount('all').on}/{catCount('all').total}
              </button>
              <button
                type="button" class={`aps-tab ${mTab() === 'image' ? 'active' : ''}`}
                onClick={() => setMTab('image')}
              >
                生图 {catCount('image').on}/{catCount('image').total}
              </button>
              <button
                type="button" class={`aps-tab ${mTab() === 'chat' ? 'active' : ''}`}
                onClick={() => setMTab('chat')}
              >
                LLM {catCount('chat').on}/{catCount('chat').total}
              </button>
              <button
                type="button" class={`aps-tab ${mTab() === 'video' ? 'active' : ''}`}
                onClick={() => setMTab('video')}
              >
                视频 {catCount('video').on}/{catCount('video').total}
              </button>
            </div>
            <div class="aps-modal-list">
              <Show when={modalRows().length > 0} fallback={<div class="aps-empty">无匹配模型</div>}>
                <For each={modalRows()}>
                  {(m) => (
                    <label class="aps-mrow">
                      <input
                        type="checkbox" checked={checked().has(m)}
                        onChange={() => toggleChecked(m)}
                      />
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
