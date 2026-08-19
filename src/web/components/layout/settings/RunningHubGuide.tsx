/**
 * RunningHub 新手引导（画布同款双 Key）——  自 SettingsView 切出。
 */
import { FiCheck, FiKey } from 'solid-icons/fi';
import { RH_GUIDE, type SettingsApi } from '../settings-meta';

export function RunningHubGuide(props: { api: SettingsApi }) {
  const api = () => props.api;
  return (
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
            type="password" class="aps-input mono" value={api().rhCoin()}
            placeholder={api().current()!.has_key ? `保持当前 Key ${api().current()!.key_preview || ''}` : '粘贴 RH币 API Key'}
            onInput={(e) => api().setRhCoin(e.currentTarget.value)}
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
            type="password" class="aps-input mono" value={api().rhWallet()}
            placeholder={api().current()!.has_wallet_key ? `保持当前 Key ${api().current()!.wallet_key_preview || ''}` : '标准模型/视频模型请粘贴这个 Key'}
            onInput={(e) => api().setRhWallet(e.currentTarget.value)}
          />
        </div>
      </div>
      <div class="aps-guide-save">
        <button
          type="button" class="aps-btn light"
          onClick={() => void api().saveAll({
            ...(api().rhCoin().trim() ? { api_key: api().rhCoin().trim() } : {}),
            ...(api().rhWallet().trim() ? { wallet_api_key: api().rhWallet().trim() } : {}),
          }).then((ok) => { if (ok) { api().setRhCoin(''); api().setRhWallet(''); } })}
        >
          <FiCheck size={12} /> 保存
        </button>
      </div>
      <div class="aps-keynote">
        {api().current()!.has_wallet_key
          ? `余额 Key 已保存：${api().current()!.wallet_key_env}`
          : '还没有保存方舟/RH 余额 API Key。'}
      </div>
    </div>
  );
}
