/**
 * 左侧面板：平台列表 + 新增平台 + CLI 设置——  自 SettingsView 切出。
 */
import { For, Show } from 'solid-js';
import { FiPlus } from 'solid-icons/fi';
import { CLI_ENTRIES, type SettingsApi } from '../settings-meta';

export function SettingsSidePanel(props: { api: SettingsApi }) {
  const api = () => props.api;
  return (
    <aside class="aps-side">
      <div class="aps-side-label">平台列表</div>
      <div class="aps-side-list">
        <For each={api().providers()}>
          {(p, i) => (
            <button
              type="button" class={`aps-item ${i() === api().sel() ? 'active' : ''}`}
              onClick={() => api().switchSel(i())}
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
      <button type="button" class="aps-add" onClick={() => api().addProvider()}>
        <FiPlus size={12} /> 新增平台
      </button>

      <div class="aps-side-label aps-cli-label">CLI 设置</div>
      <For each={CLI_ENTRIES}>
        {(c) => (
          <button
            type="button" class="aps-cli-item" title={api().cliStatus()[c.key]?.message || '点击选择/新建该 CLI 平台'}
            onClick={() => api().selectOrAddCli(c.protocol, c.label)}
          >
            <span class="aps-item-name">{c.label}</span>
            <span class={`aps-cli-badge ${api().cliStatus()[c.key]?.installed ? 'on' : ''}`}>
              {api().cliStatus()[c.key]?.installed ? '已就绪' : '未安装'}
            </span>
          </button>
        )}
      </For>
      <div class="aps-cli-note">CLI 平台无需请求地址；未安装时请先装好对应 CLI 依赖。</div>
    </aside>
  );
}
