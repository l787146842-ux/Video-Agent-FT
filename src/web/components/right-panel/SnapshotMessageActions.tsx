import { chatState } from '@/stores/chat';
import { state } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { restoreSnapshot, forkSnapshot, getProjectState } from '@/api/project';
import { ApiError } from '@/api/client';
import { confirmDialog } from '@/components/shared/ConfirmDialog';
import { applyProjectSnapshot } from '@/lib/project-apply';
import { requestInsertText } from '@/lib/chat/chat-input-bridge';
import { disconnectAgentStream, resumeAgentTasks } from '@/hooks/use-sse';
import type { ChatMessage } from '@/types';

/** E1 回档三件套：消息级快照动作条（挂于有 snapshotId 的 agent 消息）。
 *
 * 二次确认走全局确认卡（confirmDialog，亮橙确认语义，非浏览器原生弹窗）；
 * 生成中禁回退由后端 409 拒收，错误经 ApiError.payload 出人话 toast；
 * 回档/分叉成功后免刷新——applyProjectSnapshot 整板重置 + SSE 重订阅，
 * 回档另把原请求经响应式插入桥回填输入框（替代旧的 sessionStorage + reload）。 */
export function SnapshotMessageActions(props: { message: ChatMessage; domIndex?: number }) {
  const msg = () => props.message;

  /** 回档前取本条之前最近一条用户消息正文（免刷新后经插入桥回填） */
  const refillPrompt = (): string => {
    const idx = props.domIndex ?? chatState.messages.indexOf(msg());
    const prevUser = [...chatState.messages.slice(0, idx)]
      .reverse().find((m) => m.sender === 'user' && m.text);
    return prevUser?.text || '';
  };

  /** 错误 → 人话 toast：ApiError 携后端结构化负载取其 message，其余走兜底文案 */
  const showErr = (e: unknown, fallback: string) => {
    showToast(e instanceof ApiError ? e.payload.message : fallback, 'warning');
  };

  /** 回到此刻：二次确认 → 回档 → 免刷新整板重置 + SSE 重订阅 + 原请求回填 */
  const doRestoreHere = async () => {
    const sid = msg().snapshotId;
    if (!sid) return;
    const ok = await confirmDialog({
      title: '回档到这条消息的时刻？',
      message: '之后的改动将被覆盖（可经撤销/重做复核）。',
      confirmText: '回档',
      danger: true,
    });
    if (!ok) return;
    const refill = refillPrompt();
    try {
      const res = await restoreSnapshot(sid);
      // 回档同项目：projectId 不变，LayoutShell 的重订阅 effect 不触发，需显式重连
      disconnectAgentStream();
      applyProjectSnapshot(res.state);
      if (refill) requestInsertText(refill);
      await resumeAgentTasks(state.projectId);
      showToast('已回档，原请求已回填到输入框', 'success');
    } catch (e) {
      showErr(e, '回档失败（生成中禁止回退）');
    }
  };

  /** 从此刻新开项目：二次确认 → 分叉（原项目不动）→ 免刷新切到新项目 */
  const doForkHere = async () => {
    const sid = msg().snapshotId;
    if (!sid) return;
    const ok = await confirmDialog({
      title: '从这条消息的时刻新开一个项目？',
      message: '原项目保持不变。',
      confirmText: '新开项目',
    });
    if (!ok) return;
    try {
      await forkSnapshot(sid);
      // 分叉后端已切活跃项目但不回传 state，补拉整板；断开旧项目订阅
      // （不杀后端任务，尊重「原项目不动」），projectId 变化由 LayoutShell effect 自动重订阅
      disconnectAgentStream();
      const snapshot = await getProjectState();
      applyProjectSnapshot(snapshot);
      showToast('已从此刻新开项目', 'success');
    } catch (e) {
      showErr(e, '分叉失败（生成中禁止回退）');
    }
  };

  return (
    <div class="msg-snapshot-actions">
      <button type="button" class="gate-override-btn" onClick={() => void doRestoreHere()}>
        回到此刻
      </button>
      <button type="button" class="gate-override-btn" onClick={() => void doForkHere()}>
        从此刻新开项目
      </button>
    </div>
  );
}
