import { chatState } from '@/stores/chat';
import { showToast } from '@/stores/toast';
import { restoreSnapshot, forkSnapshot } from '@/api/project';
import type { ChatMessage } from '@/types';

/** E1 回档三件套：消息级快照动作条（挂于有 snapshotId 的 agent 消息）。
 *
 * 二次确认由 confirm 弹窗把关；生成中禁回退由后端 409 拒收；
 * 回档成功后原请求回填输入框（sessionStorage 一次性桥，重载后消费）。 */
export function SnapshotMessageActions(props: { message: ChatMessage; domIndex?: number }) {
  const msg = () => props.message;

  /** 回档前把本条之前最近一条用户消息正文存入 sessionStorage（重载后回填） */
  const stashRefillPrompt = () => {
    const idx = props.domIndex ?? chatState.messages.indexOf(msg());
    const prevUser = [...chatState.messages.slice(0, idx)]
      .reverse().find((m) => m.sender === 'user' && m.text);
    if (prevUser?.text) sessionStorage.setItem('e1-restore-refill', prevUser.text);
  };

  /** 回到此刻：二次确认 → 回档 → 重载重建视图 */
  const doRestoreHere = async () => {
    const sid = msg().snapshotId;
    if (!sid) return;
    if (!window.confirm('回档到这条消息的时刻？之后的改动将被覆盖（可经撤销/重做复核）。')) return;
    try {
      await restoreSnapshot(sid);
      stashRefillPrompt();
      showToast('已回档，原请求已回填到输入框', 'success');
      location.reload();
    } catch (e) {
      showToast(e instanceof Error ? e.message : '回档失败（生成中禁止回退）', 'warning');
    }
  };

  /** 从此刻新开项目：二次确认 → 分叉（原项目不动）→ 重载切到新项目 */
  const doForkHere = async () => {
    const sid = msg().snapshotId;
    if (!sid) return;
    if (!window.confirm('从这条消息的时刻新开一个项目？原项目保持不变。')) return;
    try {
      await forkSnapshot(sid);
      showToast('已从此刻新开项目', 'success');
      location.reload();
    } catch (e) {
      showToast(e instanceof Error ? e.message : '分叉失败（生成中禁止回退）', 'warning');
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
