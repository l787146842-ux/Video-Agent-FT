/**
 * 项目级快照应用（跨 store 编排的单一实现）。
 *
 * 后端「整板状态」下发后，前端需一次性重置四个 store 到该快照：
 * studio（画布/项目态）、chat（消息）、conversations（多对话标签）、history（undo/redo 指示）。
 * 此前只在 use-project-actions 的本地 applySnapshot 里，E1 回档/分叉改免刷新后
 * 需复用同一套重置——下沉到 lib 作为单一事实源，避免两处各写一遍漏项。
 */
import { studioActions } from '@/stores/studio';
import { chatActions } from '@/stores/chat';
import { convActions } from '@/stores/conversations';
import { refreshHistoryStatus } from '@/stores/history';
import type { ServerStateSnapshot } from '@/types';

/** 把整板快照应用到前端全部 store（项目切换/新建/删除 + E1 回档/分叉共用）。
 * 快照为空（后端未回传 state）时静默跳过，由调用方决定是否补拉。 */
export function applyProjectSnapshot(snapshot?: ServerStateSnapshot | null): void {
  if (!snapshot) return;
  studioActions.resetForProject(snapshot);
  chatActions.loadMessages(snapshot.chatMessages || []);
  // 项目/回档后多对话标签栏随之重置
  convActions.loadFromSnapshot(snapshot);
  // 切换/回档会重建后端 undo/redo 栈，同步指示位
  void refreshHistoryStatus();
}
