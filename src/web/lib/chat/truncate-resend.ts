/**
 * 截断重答动作通道（编辑与重新生成同源，任务 #17 新交互模型）。
 *
 * POST /api/chat/truncate-resend：后端截断最后一条用户消息之后的全部
 * 消息（text 非空时替换该消息正文）并起 agent 任务（携带 UI 当前选中的
 * provider/model/thinking_level，与主输入框同口径）。成功后：
 * ① 本地消息列表同步截断（旧回复消失，与后端 truncate_chat_tail 同语义）；
 * ② 响应体 {task_id, project_id, model}，经 use-sse.attachStartedTask
 *    接管既有事件订阅（startStream(model) 补流式模型徽标），
 *    新回复走既有 SSE 流式通道接续。
 *
 * 忙碌守卫：UI 层（affordances）忙碌时不挂按钮，这里兜底再判一次。
 */
import { truncateResend } from '@/api/chat';
import { ApiError } from '@/api/client';
import { attachStartedTask } from '@/hooks/use-sse';
import { chatActions } from '@/stores/chat';
import { agentProvider, agentModel, agentThinkingLevel } from '@/stores/agent-prefs';
import { agentState } from '@/stores/agent-state';
import { showToast } from '@/stores/toast';
import { t } from '@/lib/locale';

/**
 * 截断重答：text 非空 = 编辑后重答；缺省 = 重新生成（按原文重答）。
 * 返回 true = 已受理（本地已截断、新任务订阅已建立）。
 */
export async function truncateResendAction(text?: string): Promise<boolean> {
  if (agentState.agentBusy) {
    showToast(t('rp.conv.busyGuard'), 'warning');
    return false;
  }
  try {
    const started = await truncateResend(text ?? null, {
      provider: agentProvider(),
      model: agentModel(),
      thinking_level: agentThinkingLevel(),
    });
    // 后端成功后本地才截断（409/400 拒绝时消息列表保持原样）
    chatActions.truncateTailForResend(text);
    await attachStartedTask(started);
    return true;
  } catch (e) {
    const message = e instanceof ApiError ? e.payload.message : ((e as Error).message || '');
    showToast(t('rp.msg.truncateFailed', { error: message }), 'error');
    return false;
  }
}
