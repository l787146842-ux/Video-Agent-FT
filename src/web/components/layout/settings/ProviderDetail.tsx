/**
 * 右侧详情区：选中平台的头部卡/基本信息卡/模型列表/安全说明——
 *  自 SettingsView 切出（KeyRow/ModelCard 随之内化）。
 */
import { For, Show } from 'solid-js';
import {
  FiCheck, FiDownload, FiKey, FiPlus, FiTrash2, FiZap,
} from 'solid-icons/fi';
import { getGlobalApiKey, setGlobalApiKey } from '@/api/client';
import {
  BUILTIN_IDS, IMAGE_MODE_OPTIONS, PLATFORM_META, PROTOCOL_OPTIONS,
  type ModelKind, type SettingsApi,
} from '../settings-meta';
import { RunningHubGuide } from './RunningHubGuide';
import { CliAccountCard } from './CliAccountCard';

export function ProviderDetail(props: { api: SettingsApi }) {
  const api = () => props.api;

  /** API Key 行（画布同款：输入 + ✓ 提交 + 🗑 清除 + env 名提示） */
  function KeyRow() {
    return (
      <>
        <div class="aps-field">
          <span>API Key</span>
          <div class="aps-keyrow">
            <input
              type="password" class="aps-input mono" value={api().keyInput()}
              placeholder={api().current()!.has_key ? `保持当前 Key ${api().current()!.key_preview || '••••••••'}` : `输入${api().current()!.name || '平台'} API Key`}
              onInput={(e) => api().setKeyInput(e.currentTarget.value)}
            />
            <button type="button" class="aps-icon-btn" title="保存 Key 到 API/.env" onClick={() => api().commitKey()}>
              <FiCheck size={14} />
            </button>
            <button type="button" class="aps-icon-btn" title="清除已保存的 Key" onClick={() => api().clearKey()}>
              <FiTrash2 size={13} />
            </button>
          </div>
        </div>
        <div class="aps-keynote">
          {api().current()!.has_key
            ? `当前 Key 已保存：${api().current()!.key_env || 'API/.env'}`
            : `还没有保存 ${api().current()!.name || '该平台'} API Key。`}
        </div>
      </>
    );
  }

  /** 模型分区卡片 */
  function ModelCard(cardProps: { title: string; desc: string; kind: ModelKind }) {
    return (
      <div class="aps-card">
        <div class="aps-card-head">
          <div>
            <div class="aps-sec-title">{cardProps.title}</div>
            <div class="aps-sec-desc">{cardProps.desc}</div>
          </div>
          <button type="button" class="aps-btn" onClick={() => api().addModel(cardProps.kind)}>
            <FiPlus size={12} /> 模型
          </button>
        </div>
        <Show when={(api().current()?.[cardProps.kind] || []).length > 0} fallback={<div class="aps-empty">暂无模型</div>}>
          <For each={api().current()?.[cardProps.kind] || []}>
            {(m, idx) => (
              <div class="aps-model-row">
                <input
                  class="aps-input mono" value={m} placeholder="模型名"
                  onInput={(e) => api().patchModel(cardProps.kind, idx(), e.currentTarget.value)}
                />
                <button type="button" class="aps-icon-btn" title="删除该模型" onClick={() => api().removeModel(cardProps.kind, idx())}>
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
    <section class="aps-detail">
      <div class="aps-card aps-head-card">
        <div>
          <div class="aps-title">{api().current()!.name || '未命名平台'}</div>
          <div class="aps-sub">配置基础信息、API Key 和可用模型</div>
        </div>
        <div class="aps-head-actions">
          <Show when={!BUILTIN_IDS.has(api().current()!.id)}>
            <button type="button" class="aps-btn danger" onClick={() => api().removeCurrent()}>
              <FiTrash2 size={12} /> 删除
            </button>
          </Show>
          <button type="button" class="aps-btn light" onClick={() => void api().saveAll()}>
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
            class="aps-input" value={api().current()!.name || ''} placeholder="供应商显示名"
            onInput={(e) => api().patch('name', e.currentTarget.value)}
          />
        </label>
        <div class="aps-idline">平台 ID: <code>{api().current()!.id}</code>（自动分配，不可编辑）</div>

        {/* RunningHub 新手引导（画布同款双 Key） */}
        <Show when={api().current()!.id === 'runninghub'}>
          <RunningHubGuide api={api()} />
        </Show>

        {/* CLI 账户卡（画布同款） */}
        <Show when={api().isCli()}>
          <CliAccountCard api={api()} />
        </Show>

        {/* 非 CLI：请求地址 + 平台定制提示 + Key 行 */}
        <Show when={!api().isCli()}>
          <label class="aps-field">
            <span>请求地址</span>
            <input
              class="aps-input mono" value={api().current()!.base_url || ''} placeholder="https://…"
              onInput={(e) => api().patch('base_url', e.currentTarget.value.trim())}
            />
          </label>
          <Show when={PLATFORM_META[api().current()!.id]?.defaultUrls}>
            <For each={PLATFORM_META[api().current()!.id]?.defaultUrls || []}>
              {([label, url]) => (
                <div class="aps-chipline">
                  <span>{label}：</span><code>{url}</code>
                </div>
              )}
            </For>
          </Show>
          <Show when={PLATFORM_META[api().current()!.id]?.note}>
            <div class="aps-keynote">{PLATFORM_META[api().current()!.id]?.note}</div>
          </Show>
          <Show when={api().current()!.id !== 'runninghub'}>
            <KeyRow />
          </Show>
          <Show when={PLATFORM_META[api().current()!.id]?.tokenLinks}>
            <For each={PLATFORM_META[api().current()!.id]?.tokenLinks || []}>
              {([label, url]) => (
                <div class="aps-chipline">
                  <span>{label}：</span>
                  <a href={url} target="_blank" rel="noopener noreferrer">{url}</a>
                </div>
              )}
            </For>
          </Show>
        </Show>

        {/* 验证行（画布同款）：验证地址/验证协议 + 协议下拉 + 图片接口模式下拉 */}
        <div class="aps-verify-row">
          <button type="button" class="aps-btn" onClick={() => api().verifyAddress()}>
            <FiZap size={12} /> 验证地址
          </button>
          <Show when={!api().isCli()}>
            <button type="button" class="aps-btn" onClick={() => api().verifyProtocol()}>
              <FiCheck size={12} /> 验证协议
            </button>
          </Show>
          <select
            class="aps-input aps-select-inline" value={api().current()!.protocol || 'openai'}
            onChange={(e) => api().patch('protocol', e.currentTarget.value)}
          >
            <Show when={!PROTOCOL_OPTIONS.some((o) => o.value === (api().current()!.protocol || 'openai'))}>
              <option value={api().current()!.protocol || ''}>
                {api().current()!.protocol ? `其它：${api().current()!.protocol}` : '请选择协议'}
              </option>
            </Show>
            <For each={PROTOCOL_OPTIONS}>
              {(o) => <option value={o.value}>{o.label}</option>}
            </For>
          </select>
          <Show when={!api().isCli()}>
            <select
              class="aps-input aps-select-inline" value={api().imageMode()}
              onChange={(e) => api().patch('image_request_mode', e.currentTarget.value)}
            >
              <Show when={!IMAGE_MODE_OPTIONS.some((o) => o.value === api().imageMode())}>
                <option value={api().imageMode()}>其它：{api().imageMode()}</option>
              </Show>
              <For each={IMAGE_MODE_OPTIONS}>
                {(o) => <option value={o.value}>{o.label}</option>}
              </For>
            </select>
          </Show>
        </div>
        {/* 验证结果内联（画布同款：直接在底部展示） */}
        <Show when={api().verifyResult()}>
          <div class={`aps-verify-result ${api().verifyResult()!.ok ? 'ok' : 'err'}`}>
            {api().verifyResult()!.ok ? '✓ ' : '✗ '}{api().verifyResult()!.text}
          </div>
        </Show>
      </div>

      <div class="aps-card">
        <div class="aps-card-head">
          <div>
            <div class="aps-sec-title">模型列表</div>
            <div class="aps-sec-desc">从上游 API 自动拉取所有可用模型并按类型分类（image / chat / video）</div>
          </div>
          <button type="button" class="aps-btn light" onClick={() => api().fetchModels()}>
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
  );
}
