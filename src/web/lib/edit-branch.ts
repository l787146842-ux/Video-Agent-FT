/**
 * 编辑历史消息 = 分支（edit-and-branch 心智）。
 *
 * 「编辑」不再只是回填输入框在原对话发新消息（长对话会积累大量
 * “改过的版本”）：点击编辑即从当前对话打快照并派生分支对话，
 * 修改后的内容在新对话里经输入框走统一发送入口发出——
 * 原对话历史保持不动，修改版独立成线。
 *
 * 复用已验收的会话分支机制（快照 + branchSnapshot），零后端改动；
 * 发送仍由用户在输入框确认后走 submitMessage('new')，无新发送路径。
 */
import { state } from '@/stores/studio';
import { convActions } from '@/stores/conversations';
import { showToast } from '@/stores/toast';
import { createSnapshot, branchSnapshot } from '@/api/conversations';
import { requestEditBackfill } from '@/lib/chat-input-bridge';
import { t } from '@/lib/locale';

/**
 * 编辑并分支：忙碌中拒收（分支切换对话，流式中禁止）；
 * 成功后分支对话成为活跃对话，被编辑消息正文回填输入框待修改。
 * 返回 true = 分支创建成功。
 */
export async function editMessageInBranch(text: string): Promise<boolean> {
  const body = (text || '').trim();
  if (!body) return false;
  if (state.agentBusy) {
    showToast(t('rp.conv.busyGuard'), 'warning');
    return false;
  }
  try {
    const snap = await createSnapshot();
    const payload = await branchSnapshot(snap.snap_id);
    convActions.applyPayload(payload);
    requestEditBackfill(body);
    showToast(t('rp.msg.editBranched'), 'success');
    return true;
  } catch (e) {
    showToast(t('rp.msg.editBranchFailed', { error: (e as Error).message }), 'error');
    return false;
  }
}
