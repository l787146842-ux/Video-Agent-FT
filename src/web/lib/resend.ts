/**
 * 机械重发域（retry 与轮级 regenerate 同源）。
 *
 * 确定性交互公理：重跑 = 机械重发目标用户消息原内容（含富文本附件），
 * 零模型猜测、不重写历史（对齐项目 retry 语义）。
 */
import { chatState } from '@/stores/chat';
import { submitMessage } from './submit-message';

/** 机械重发 startIdx 之前（含）最近一条用户消息；无则不发。
 * 走统一发送入口（intent='resend'），序列化/校验/排队判定单点。 */
export function resendNearestUserMessage(startIdx: number): void {
  const msgs = chatState.messages;
  for (let i = startIdx; i >= 0; i -= 1) {
    const m = msgs[i];
    if (m.sender !== 'user') continue;
    // 富文本重发优先原 parts（含内联附件）；无 parts 回落纯文本
    const parts = (m.parts || []).filter((p) => (p.type === 'text' ? !!p.text.trim() : !!p.url));
    void submitMessage('resend', { input: parts.length ? parts : (m.text || '') });
    return;
  }
}
