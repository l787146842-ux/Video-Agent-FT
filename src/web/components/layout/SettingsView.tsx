import { createSignal, For, Show, onMount } from 'solid-js';
import { A } from '@solidjs/router';
import { FiArrowLeft, FiCheck, FiDownload, FiKey, FiPlus, FiTrash2, FiZap } from 'solid-icons/fi';
import { getProviders } from '@/api/providers';
import { apiPut, apiPost, getGlobalApiKey, setGlobalApiKey } from '@/api/client';
import { showToast } from '@/stores/toast';
import type { ApiProvider } from '@/types';

/**
 * API 配置页（SPA 原生实现）。
 * 外观照画布 API 设置风格（用户裁决 2026-08-16）：左「平台列表」侧栏 +
 * 右侧「基本信息 / 模型列表 / 生图·聊天·视频模型」分区卡片；去掉「推荐API」；
 * CLI 设置区不照搬（本项目 workflows/CLI 已下线）。
 * 功能仍走本项目后端：PUT /api/providers（保存即时生效、Key 写入 API/.env 不回显）、
 * POST /api/providers/fetch-models、POST /api/providers/test-connection。
 */

interface EditableProvider extends ApiProvider {
  api_key?: string;
  has_key?: boolean;
}

const PROTOCOL_OPTIONS = [
  { value: 'openai', label: 'OpenAI 兼容' },
  { value: 'gemini-cli', label: 'Gemini CLI (agy)' },
  { value: 'mock', label: 'Mock（本地演示）' },
];

type ModelKind = 'chat_models' | 'image_models' | 'video_models';

function newProvider(): EditableProvider {
  return {
    id: '', name: '', protocol: 'openai', base_url: '',
    enabled: true, chat_models: [], image_models: [], video_models: [],
    api_key: '', has_key: false,
  };
}

export default function SettingsView() {
  const [providers, setProviders] = createSignal<EditableProvider[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [sel, setSel] = createSignal(0);

  onMount(async () => {
    try {
      const data = await getProviders();
      setProviders(data.providers.map((p) => ({ ...p, api_key: '' })));
    } catch {
      showToast('加载供应商配置失败', 'error');
    } finally {
      setLoading(false);
    }
  });

  const current = () => providers()[sel()];

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
    setProviders((prev) => [...prev, newProvider()]);
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

  async function fetchModels() {
    const p = current();
    if (!p) return;
    try {
      const data = await apiPost<{ chat_models: string[]; image_models: string[]; video_models: string[] }>(
        '/api/providers/fetch-models',
        { base_url: p.base_url, api_key: p.api_key || '', provider_id: p.id, protocol: p.protocol },
      );
      patch('chat_models', data.chat_models || []);
      patch('image_models', data.image_models || []);
      patch('video_models', data.video_models || []);
      showToast('已拉取并分类模型列表', 'success');
    } catch (e) {
      showToast(`拉取模型失败：${(e as Error).message}`, 'error');
    }
  }

  async function testConnection() {
    const p = current();
    if (!p) return;
    try {
      await apiPost('/api/providers/test-connection',
        { base_url: p.base_url, api_key: p.api_key || '', provider_id: p.id, protocol: p.protocol });
      showToast('连接测试通过', 'success');
    } catch (e) {
      showToast(`连接失败：${(e as Error).message}`, 'error');
    }
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
            {/* 左：平台列表（画布风格；无「推荐API」，CLI 区不照搬） */}
            <aside class="aps-side">
              <div class="aps-side-label">平台列表</div>
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
              <button type="button" class="aps-add" onClick={addProvider}>
                <FiPlus size={12} /> 新增平台
              </button>
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
                  <label class="aps-field">
                    <span>平台 ID</span>
                    <input
                      class="aps-input mono" value={current()!.id || ''} placeholder="如 openai（保存后作为唯一标识）"
                      onInput={(e) => patch('id', e.currentTarget.value.trim())}
                    />
                  </label>
                  <label class="aps-field">
                    <span>请求地址</span>
                    <input
                      class="aps-input mono" value={current()!.base_url || ''} placeholder="https://…"
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
                    <button type="button" class="aps-btn" onClick={() => void testConnection()}>
                      <FiZap size={12} /> 验证地址
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
    </div>
  );
}
