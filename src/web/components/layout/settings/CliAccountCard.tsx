/**
 * CLI 账户卡（画布同款）——  自 SettingsView 切出。
 * 检测/帮助/即梦登录积分登出按钮；动作经 SettingsApi 回调父组件状态。
 */
import { Show } from 'solid-js';
import { showToast } from '@/stores/toast';
import { CLI_ENTRIES, CLI_META, type SettingsApi } from '../settings-meta';

export function CliAccountCard(props: { api: SettingsApi }) {
  const api = () => props.api;
  /** cliStatus 的 key 映射：gemini-cli 协议在状态表里登记为 agy（与 CLI_ENTRIES 一致） */
  const statusKey = () => (api().proto() === 'gemini-cli' ? 'agy' : api().proto());

  return (
    <div class="aps-cli-account">
      <div class="aps-guide-head">
        <div>
          <div class="aps-sec-title">{CLI_META[api().proto()]?.title || 'CLI 账户'}</div>
          <div class="aps-sec-desc">{CLI_META[api().proto()]?.desc || ''}</div>
        </div>
        <span class={`aps-cli-badge ${api().cliStatus()[statusKey()]?.installed ? 'on' : 'warn'}`}>
          {api().cliStatus()[statusKey()]?.installed ? '已安装' : '未安装'}
        </span>
      </div>
      <div class="aps-verify-row">
        <Show when={api().proto() === 'jimeng'}>
          <button type="button" class="aps-btn" onClick={() => api().jimengLogin()}>扫码登录</button>
          <button type="button" class="aps-btn" onClick={() => api().jimengCredit()}>查询积分</button>
        </Show>
        <button
          type="button" class="aps-btn"
          onClick={() => void (async () => {
            const entry = CLI_ENTRIES.find((c) => c.protocol === api().proto());
            if (!entry) return;
            const ok = await api().refreshCliStatus(entry.key, entry.statusPath);
            showToast(ok ? 'CLI 已就绪' : 'CLI 未安装', ok ? 'success' : 'error');
          })()}
        >
          检测 CLI
        </button>
        <button
          type="button" class="aps-btn"
          onClick={() => void (async () => {
            const entry = CLI_ENTRIES.find((c) => c.protocol === api().proto());
            if (entry) api().cliHelp(entry.label, entry.helpPath);
          })()}
        >
          帮助
        </button>
        <Show when={api().proto() === 'jimeng'}>
          <button type="button" class="aps-btn danger" onClick={() => api().jimengLogout()}>退出登录</button>
        </Show>
      </div>
    </div>
  );
}
