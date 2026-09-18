/** Chat store · 会话投影兜底域（D2 批 commit3）：重连/刷新后拉一致切，
 * 活跃暂停存在而消息尾无 confirm 载体时物化暂停卡（done 帧丢失类兜底腿）。
 * 兜底腿：失败静默、不阻断主链（replay/历史仍为主源）；幂等不双挂。
 */
import { getConversationProjection, type ProjectionActivePause } from '@/api/conversations';
import type { ChatMessage } from '@/types';
import { messageActions } from './messages';

/** 选项面归一：投影折的是模型原始 tool_call 参数，缺 label 的项机械消费无意义
 * （确认卡点击发 value||label），丢弃；出口对齐 ChatMessage.confirmOptions 契约。 */
function normalizeOptions(pause: ProjectionActivePause): ChatMessage['confirmOptions'] {
  const options: NonNullable<ChatMessage['confirmOptions']> = [];
  for (const o of pause.options || []) {
    const label = String(o?.label || '').trim();
    if (!label) continue;
    options.push({ label, description: o.description, group: o.group, value: o.value });
  }
  return options;
}

/** 拉投影一致切并物化暂停卡兜底；convId 空/请求失败/无活跃暂停均静默返回 */
export async function refreshProjectionFallback(convId: string): Promise<void> {
  if (!convId) return;
  try {
    const snap = await getConversationProjection(convId);
    const pause = snap?.values?.interaction_pause?.active_pause;
    if (!pause) return;
    messageActions.applyPauseFallback({
      message: pause.message,
      options: normalizeOptions(pause),
    });
  } catch { /* 投影失败静默：兜底腿不影响主链 */ }
}
