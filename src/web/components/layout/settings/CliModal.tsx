/**
 * CLI 输出弹窗（帮助/积分/扫码登录）——七轮 S1/T23 自 SettingsView 切出，纯展示。
 */
import { Show } from 'solid-js';
import { FiExternalLink, FiX } from 'solid-icons/fi';

export interface CliModalData {
  title: string;
  text: string;
  qr_url?: string;
}

export function CliModal(props: { modal: () => CliModalData; onClose: () => void }) {
  return (
    <div class="aps-modal-mask" onClick={props.onClose}>
      <div class="aps-modal" onClick={(e) => e.stopPropagation()}>
        <div class="aps-modal-head">
          <div class="aps-sec-title">{props.modal().title}</div>
          <button type="button" class="aps-icon-btn" title="关闭" onClick={props.onClose}>
            <FiX size={14} />
          </button>
        </div>
        <div class="aps-cli-output">
          <Show when={props.modal().qr_url}>
            <a class="aps-btn light" href={props.modal().qr_url} target="_blank" rel="noopener noreferrer">
              <FiExternalLink size={12} /> 打开登录链接
            </a>
          </Show>
          <pre>{props.modal().text}</pre>
        </div>
      </div>
    </div>
  );
}
