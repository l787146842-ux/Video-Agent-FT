import { createSignal, For, Show, onMount } from 'solid-js';
import { A } from '@solidjs/router';
import { FiArrowLeft, FiCheck, FiDownload, FiKey, FiSettings, FiTrash2, FiZap } from 'solid-icons/fi';
import { getProviders } from '@/api/providers';
import { apiPut, apiPost, getGlobalApiKey, setGlobalApiKey } from '@/api/client';
import { showToast } from '@/stores/toast';
import type { ApiProvider } from '@/types';

/**
 * API 配置页（B3b：替代 iframe 嵌入的 static/api-settings.html，SPA 原生实现）。
 * 供应商列表编辑（协议/地址/启用/三类模型/API Key/拉取模型/测试连通），
 * 保存经 PUT /api/providers（后端消毒 + 原子写 + 加锁，与本页无关的安全语义不变）。
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

  function patch(index: number, field: string, value: unknown) {
    setProviders((prev) => prev.map((p, i) => (i === index ? { ...p, [field]: value } : p)));
  }

  function splitModels(v: string): string[] {
    return v.split(/[,\n]/).map((s) => s.trim()).filter(Boolean);
  }

  async function saveAll() {
    const list = providers().map((p) => ({
      id: p.id, name: p.name, protocol: p.protocol, base_url: p.base_url,
      enabled: p.enabled, chat_models: p.chat_models || [], image_models: p.image_models || [],
      video_models: p.video_models || [], api_key: p.api_key || undefined,
    }));
    try {
      const saved = await apiPut<{ providers: ApiProvider[] }>('/api/providers', { providers: list });
      setProviders(saved.providers.map((p) => ({ ...p, api_key: '' })));
      showToast('供应商配置已保存', 'success');
    } catch (e) {
      showToast(`保存失败：${(e as Error).message}`, 'error');
    }
  }

  async function fetchModels(index: number) {
    const p = providers()[index];
    try {
      const data = await apiPost<{ chat_models: string[]; image_models: string[]; video_models: string[] }>(
        '/api/providers/fetch-models',
        { base_url: p.base_url, api_key: p.api_key || '', provider_id: p.id, protocol: p.protocol },
      );
      patch(index, 'chat_models', data.chat_models || []);
      patch(index, 'image_models', data.image_models || []);
      patch(index, 'video_models', data.video_models || []);
      showToast('已拉取并分类模型列表', 'success');
    } catch (e) {
      showToast(`拉取模型失败：${(e as Error).message}`, 'error');
    }
  }

  async function testConnection(index: number) {
    const p = providers()[index];
    try {
      await apiPost('/api/providers/test-connection',
        { base_url: p.base_url, api_key: p.api_key || '', provider_id: p.id, protocol: p.protocol });
      showToast('连接测试通过', 'success');
    } catch (e) {
      showToast(`连接失败：${(e as Error).message}`, 'error');
    }
  }

  return (
    <div class="global-settings-view">
      <div class="gs-panel">
        <div class="gs-header">
          <A href="/" class="gs-back" title="返回影视工作台"><FiArrowLeft size={14} /></A>
          <FiSettings size={15} class="gs-icon" />
          <span class="gs-title">API 配置</span>
          <span class="gs-sub">供应商与 API Key 管理（保存即时生效；Key 写入 API/.env，不回显）</span>
        </div>

        <Show when={!loading()} fallback={<div class="gs-loading">加载供应商…</div>}>
          <section class="gs-section">
            <div class="gs-row">
              <button type="button" class="btn-secondary" onClick={() => setProviders((prev) => [...prev, newProvider()])}>
                添加供应商
              </button>
              <button type="button" class="btn-primary" onClick={() => void saveAll()}>
                <FiCheck size={13} /> 保存全部
              </button>
            </div>
            <For each={providers()}>
              {(p, idx) => (
                <div class="provider-edit-card">
                  <div class="gs-row">
                    <label class="provider-field">
                      <span>名称</span>
                      <input
                        class="custom-ratio-input" value={p.name || ''}
                        onInput={(e) => patch(idx(), 'name', e.currentTarget.value)}
                      />
                    </label>
                    <label class="provider-field">
                      <span>标识(id)</span>
                      <input
                        class="custom-ratio-input" value={p.id || ''} placeholder="如 openai"
                        onInput={(e) => patch(idx(), 'id', e.currentTarget.value.trim())}
                      />
                    </label>
                    <label class="provider-field">
                      <span>协议</span>
                      <select
                        class="custom-ratio-input" value={p.protocol || 'openai'}
                        onChange={(e) => patch(idx(), 'protocol', e.currentTarget.value)}
                      >
                        <For each={PROTOCOL_OPTIONS}>
                          {(o) => <option value={o.value}>{o.label}</option>}
                        </For>
                      </select>
                    </label>
                    <label class="provider-field provider-field-wide">
                      <span>Base URL</span>
                      <input
                        class="custom-ratio-input" value={p.base_url || ''}
                        onInput={(e) => patch(idx(), 'base_url', e.currentTarget.value.trim())}
                      />
                    </label>
                    <label class="provider-toggle">
                      <input
                        type="checkbox" checked={!!p.enabled}
                        onChange={(e) => patch(idx(), 'enabled', e.currentTarget.checked)}
                      />
                      <span>启用</span>
                    </label>
                  </div>
                  <div class="gs-row">
                    <label class="provider-field provider-field-wide">
                      <span>聊天模型（逗号分隔）</span>
                      <input
                        class="custom-ratio-input" value={(p.chat_models || []).join(', ')}
                        onInput={(e) => patch(idx(), 'chat_models', splitModels(e.currentTarget.value))}
                      />
                    </label>
                  </div>
                  <div class="gs-row">
                    <label class="provider-field">
                      <span>图片模型</span>
                      <input
                        class="custom-ratio-input" value={(p.image_models || []).join(', ')}
                        onInput={(e) => patch(idx(), 'image_models', splitModels(e.currentTarget.value))}
                      />
                    </label>
                    <label class="provider-field">
                      <span>视频模型</span>
                      <input
                        class="custom-ratio-input" value={(p.video_models || []).join(', ')}
                        onInput={(e) => patch(idx(), 'video_models', splitModels(e.currentTarget.value))}
                      />
                    </label>
                    <label class="provider-field">
                      <span>API Key（留空保持现状）</span>
                      <input
                        type="password" class="custom-ratio-input" value={p.api_key || ''}
                        placeholder={p.has_key ? '已配置（不回显）' : '未配置'}
                        onInput={(e) => patch(idx(), 'api_key', e.currentTarget.value)}
                      />
                    </label>
                  </div>
                  <div class="gs-row">
                    <button type="button" class="btn-secondary" onClick={() => void fetchModels(idx())}>
                      <FiDownload size={12} /> 拉取模型
                    </button>
                    <button type="button" class="btn-secondary" onClick={() => void testConnection(idx())}>
                      <FiZap size={12} /> 测试连接
                    </button>
                    <button
                      type="button" class="btn-secondary"
                      onClick={() => setProviders((prev) => prev.filter((_, i) => i !== idx()))}
                    >
                      <FiTrash2 size={12} /> 删除
                    </button>
                  </div>
                </div>
              )}
            </For>
          </section>
        </Show>

        <section class="gs-section">
          <h3>安全说明（生产环境）</h3>
          <div class="gs-row">
            <label class="provider-field">
              <span>全局 X-API-Key（生产环境访问密钥；留空=不携带）</span>
              <input
                type="password" class="custom-ratio-input"
                value={getGlobalApiKey()}
                placeholder="与后端 API_KEY 环境变量一致"
                onInput={(e) => setGlobalApiKey(e.currentTarget.value)}
              />
            </label>
          </div>
          <p class="gs-hint">
            <FiKey size={12} /> API Key 统一写入项目 API/.env（不入库、不回显）；
            生产环境（ENVIRONMENT=production）下 /api/ 请求需携带 X-API-Key 头——本页填写的
            全局密钥会被前端所有 /api 请求自动携带（存于浏览器 localStorage）。
          </p>
        </section>
      </div>
    </div>
  );
}
