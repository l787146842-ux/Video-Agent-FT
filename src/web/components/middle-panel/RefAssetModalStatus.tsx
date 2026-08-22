import type { JSXElement } from 'solid-js';

/** 弹窗主体状态区：图标 + 提示文案（+ 可选动作按钮） */
export function ModalStatus(props: { icon: JSXElement; text: string; action?: JSXElement }) {
  return (
    <div class="asset-modal-status">
      {props.icon}
      <p>{props.text}</p>
      {props.action}
    </div>
  );
}
