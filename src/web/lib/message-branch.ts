/**
 * 消息级分支（悬停工具条「分支」动作，任务 #17）。
 *
 * 以选中消息为分叉点：POST /api/conversations/snapshot {up_to_index}
 * 打截断快照（仅含该消息及之前内容）→ 派生分支对话 → applyPayload
 * 切换活跃对话。原对话不动；分叉点之后的消息不进新对话。
 *
 * 忙碌守卫：分支会切换活跃对话，流式中禁止（UI 层点击时兜底提示）。
 */
import { state } from '@/stores/studio';
import { convActions } from '@/stores/conversations';
import { showToast } from '@/stores/toast';
import { createSnapshot, branchSnapshot } from '@/api/conversations';
import { t } from '@/lib/locale';

/**
 * 从指定消息下标分支：新对话仅含该消息及之前的历史。
 * 返回 true = 分支创建成功（已切换到新对话）。
 */
export async function branchAtMessage(upToIndex: number): Promise<boolean> {
  if (state.agentBusy) {
    showToast(t('rp.conv.busyGuard'), 'warning');
    return false;
  }
  try {
    const snap = await createSnapshot(upToIndex);
    const payload = await branchSnapshot(snap.snap_id);
    convActions.applyPayload(payload);
    showToast(t('rp.msg.branchedAt'), 'success');
    return true;
  } catch (e) {
    showToast(t('rp.msg.branchFailed', { error: (e as Error).message }), 'error');
    return false;
  }
}
