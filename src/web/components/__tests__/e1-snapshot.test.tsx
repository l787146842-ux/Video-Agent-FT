/**
 * E1 回档三件套前端钉死测试：
 * ① 版本历史列表（SnapshotHistoryBar）：拉取快照指针清单渲染、空态兜底；
 * ② 消息级快照动作（SnapshotMessageActions）：二次确认把关——取消不调
 *    restore，确认后调用（生成中禁回退由后端 409 兜底，前端只管发起）。
 */
import { render, waitFor } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { SnapshotHistoryBar } from '../left-panel/SnapshotHistoryBar';
import { SnapshotMessageActions } from '../right-panel/SnapshotMessageActions';
import { getSnapshots, restoreSnapshot, forkSnapshot, getProjectState } from '@/api/project';
import { confirmDialog } from '@/components/shared/ConfirmDialog';
import { applyProjectSnapshot } from '@/lib/project-apply';
import { buildDoneMessage } from '@/stores/chat/done-message';
import { emptyLedger } from '@/lib/turn-ledger';
import type { ChatMessage, SseDonePayload, ServerStateSnapshot } from '@/types';

vi.mock('@/api/project', () => ({
  getSnapshots: vi.fn(),
  restoreSnapshot: vi.fn(),
  forkSnapshot: vi.fn(),
  getProjectState: vi.fn(),
}));
// E1 免刷新收编：确认走全局确认卡、整板重置下沉 lib/project-apply、SSE 断/续在 use-sse
vi.mock('@/components/shared/ConfirmDialog', () => ({ confirmDialog: vi.fn() }));
vi.mock('@/lib/project-apply', () => ({ applyProjectSnapshot: vi.fn() }));
vi.mock('@/hooks/use-sse', () => ({
  disconnectAgentStream: vi.fn(),
  resumeAgentTasks: vi.fn(),
}));

const msg = (snapshotId = 'snap-1'): ChatMessage => ({
  sender: 'agent', text: '回复', snapshotId,
});

describe('E1 版本历史列表', () => {
  beforeEach(() => {
    vi.mocked(getSnapshots).mockResolvedValue({ snapshots: [] });
  });
  afterEach(() => vi.clearAllMocks());

  it('空清单渲染空态兜底', async () => {
    const { container } = render(() => <SnapshotHistoryBar />);
    await waitFor(() => {
      expect(container.textContent).toContain('暂无历史版本');
    });
  });

  it('快照清单按最新在前渲染标签与时间', async () => {
    vi.mocked(getSnapshots).mockResolvedValue({
      snapshots: [
        { id: 's1', ts: '2026-08-31T01:00:00+00:00', label: '轮次完成 t1' },
        { id: 's2', ts: '2026-08-31T02:00:00+00:00', label: '轮次完成 t2' },
      ],
    });
    const { container } = render(() => <SnapshotHistoryBar />);
    await waitFor(() => {
      expect(container.textContent).toContain('轮次完成 t2');
    });
    // 最新在前
    const rows = container.querySelectorAll('.snapshot-history-row');
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('轮次完成 t2');
  });

  it('拉取失败静默兜底（不打断主流程）', async () => {
    vi.mocked(getSnapshots).mockRejectedValue(new Error('网络错误'));
    const { container } = render(() => <SnapshotHistoryBar />);
    await waitFor(() => {
      expect(container.textContent).toContain('暂无历史版本');
    });
  });
});

describe('E1 消息级快照动作（确认卡把关 + 免刷新整板重置）', () => {
  beforeEach(() => {
    vi.mocked(restoreSnapshot).mockResolvedValue({ ok: true, state: { project_id: 'p1' } as ServerStateSnapshot });
    vi.mocked(forkSnapshot).mockResolvedValue({ ok: true, project_id: 'p2' });
    vi.mocked(getProjectState).mockResolvedValue({ project_id: 'p2' } as ServerStateSnapshot);
  });
  afterEach(() => vi.clearAllMocks());

  it('取消确认：不发起回档/分叉、不重置整板', async () => {
    vi.mocked(confirmDialog).mockResolvedValue(false);
    const { container } = render(() => <SnapshotMessageActions message={msg()} />);
    const [restoreBtn] = container.querySelectorAll('button');
    restoreBtn.click();
    await waitFor(() => expect(confirmDialog).toHaveBeenCalled());
    expect(restoreSnapshot).not.toHaveBeenCalled();
    expect(applyProjectSnapshot).not.toHaveBeenCalled();
  });

  it('确认回档：调用 restoreSnapshot 并整板重置（免刷新，不再 reload）', async () => {
    vi.mocked(confirmDialog).mockResolvedValue(true);
    const { container } = render(() => <SnapshotMessageActions message={msg('snap-9')} />);
    const buttons = container.querySelectorAll('button');
    buttons[0].click();
    await waitFor(() => expect(restoreSnapshot).toHaveBeenCalledWith('snap-9'));
    await waitFor(() => expect(applyProjectSnapshot).toHaveBeenCalled());
  });

  it('确认分叉：调用 forkSnapshot 后补拉整板并重置（免刷新）', async () => {
    vi.mocked(confirmDialog).mockResolvedValue(true);
    const { container } = render(() => <SnapshotMessageActions message={msg('snap-7')} />);
    const buttons = container.querySelectorAll('button');
    buttons[1].click();
    await waitFor(() => expect(forkSnapshot).toHaveBeenCalledWith('snap-7'));
    await waitFor(() => expect(getProjectState).toHaveBeenCalled());
    await waitFor(() => expect(applyProjectSnapshot).toHaveBeenCalled());
  });
});

describe('E1 live 落账：done 同轮下发 snapshot_id', () => {
  it('payload 带 snapshot_id：live 主气泡挂 snapshotId（当前会话即见回档动作）', () => {
    const payload = { snapshot_id: 'snap-live', turn_id: 't1' } as SseDonePayload;
    const m = buildDoneMessage(payload, 0, 'model-x', emptyLedger());
    expect(m.snapshotId).toBe('snap-live');
  });

  it('payload 无 snapshot_id：不挂 snapshotId（停止/无快照轮不渲染回档动作）', () => {
    const payload = { turn_id: 't2' } as SseDonePayload;
    const m = buildDoneMessage(payload, 0, 'model-x', emptyLedger());
    expect(m.snapshotId).toBeUndefined();
  });
});
