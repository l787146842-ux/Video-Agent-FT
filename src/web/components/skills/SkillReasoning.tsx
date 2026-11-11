/**
 * 助手思考面板（右栏紧凑版，对齐主对话深度思考语义）：
 * 流式中展开跟随（live，标题行兼作阶段状态），完成后折叠回看（details）。
 */
import { createEffect, Show } from 'solid-js';

/** 流式中的思考块：定高视窗内滚动，新文字从底部出现、旧文字向上滑出 */
export function SkillReasoningLive(props: { reasoning: string; status: string }) {
  let bodyEl: HTMLDivElement | undefined;
  // 默认跟随底部；用户手动上翻（离开底部阈值）后暂停跟随，回到底部再恢复
  let followed = true;
  function onScroll() {
    if (!bodyEl) return;
    followed =
      bodyEl.scrollHeight - bodyEl.scrollTop - bodyEl.clientHeight < 60;
  }
  createEffect(() => {
    void props.reasoning;
    if (!bodyEl || !followed) return;
    requestAnimationFrame(() => {
      if (bodyEl && followed) bodyEl.scrollTop = bodyEl.scrollHeight;
    });
  });
  return (
    <div class="skst-reasoning live">
      <div class="skst-reasoning-title">
        {props.status || (props.reasoning ? '深度思考中…' : '思考中…')}
      </div>
      <Show when={props.reasoning}>
        <div
          ref={bodyEl}
          class="skst-reasoning-body live"
          onScroll={onScroll}
        >{props.reasoning}</div>
      </Show>
    </div>
  );
}

/** 已完成回合的思考全文：默认折叠，点击展开回看 */
export function SkillReasoningDone(props: { reasoning: string }) {
  return (
    <details class="skst-reasoning">
      <summary class="skst-reasoning-title">深度思考</summary>
      <div class="skst-reasoning-body">{props.reasoning}</div>
    </details>
  );
}
