/**
 * 消息级分支（悬停工具条「分支」动作）。
 *
 * 以选中消息为分叉点：POST /api/conversations/snapshot {up_to_index}
 * 打截断快照（仅含该消息及之前内容）→ 派生分支对话 → applyPayload
 * 切换活跃对话。原对话不动；分叉点之后的消息不进新对话。
 *
 * 忙碌守卫：分支会切换活跃对话，当前对话流式中禁止（批 6-2 按对话口径；
 * 别的对话任务在跑不阻断）。
 */
import { agentActions } from '@/stores/agent-state';
import { convState, convActions } from '@/stores/conversations';
import { showToast } from '@/stores/toast';
import { createSnapshot, branchSnapshot } from '@/api/conversations';
import { t } from '@/lib/locale';

/**
 * 从指定消息下标分支：新对话仅含该消息及之前的历史。
 * 返回 true = 分支创建成功（已切换到新对话）。
 */
export async function branchAtMessage(upToIndex: number): Promise<boolean> {
  if (agentActions.isConvBusy(convState.activeId)) {
    showToast(t('rp.conv.busyGuard'), 'warning');
    return false;
  }
  try {
    const snap = await createSnapshot(upToIndex);
    // 数量上限淘汰对用户可见：后端带回非空 pruned 清单即 toast 提示
    if (snap.pruned && snap.pruned.length > 0) {
      showToast(t('rp.msg.snapshotsPruned', { n: snap.pruned.length }), 'info', 5000);
    }
    const payload = await branchSnapshot(snap.snap_id);
    // E-2：分支响应仅元信息，分支消息由 applyPayload 内经按会话拉消息接口装载
    await convActions.applyPayload(payload);
    showToast(t('rp.msg.branchedAt'), 'success');
    return true;
  } catch (e) {
    showToast(t('rp.msg.branchFailed', { error: (e as Error).message }), 'error');
    return false;
  }
}
