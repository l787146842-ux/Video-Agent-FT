/**
 * sse-task-fx 回归钉死：任务快照不得回写对话标签栏。
 *
 * 背景（批 6-2 暴露）：后台任务跑在任务专属 StateManager 实例，其快照里的
 * 对话清单冻结于起任务时刻。切回带运行中任务的对话触发重订阅，replay 快照
 * 若回写 convState，会把其后新建的对话从标签栏抹掉（用户实测：切回会话1
 * 标签只剩一个，新建会话后又恢复）。标签栏唯一事实源 = conversations REST
 * 接口 + 启动/切项目快照。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));
vi.mock('@/stores/history', () => ({ refreshHistoryStatus: vi.fn(async () => {}) }));
vi.mock('@/lib/chat/chat-input-bridge', () => ({ requestInsertMedia: vi.fn() }));
vi.mock('@/stores/studio', () => ({ studioActions: { syncFromServer: vi.fn() } }));

import { makeRoutedTaskFx } from '../sse-task-fx';
import { convState, setConvState } from '@/stores/conversations';
import type { ServerStateSnapshot } from '@/types';

const meta = (id: string, title: string) => ({ id, title });

beforeEach(() => {
  setConvState({ list: [], activeId: '' });
});

describe('syncSnapshot 不回写对话标签栏', () => {
  it('活跃对话任务 replay 快照只同步故事板，不覆盖本地对话清单', () => {
    // 本地已有 4 个对话（起任务后又新建了 3 个）
    setConvState({
      list: [
        meta('c1', '会话1'), meta('c2', '新会话2'),
        meta('c3', '新会话3'), meta('c4', '新会话4'),
      ],
      activeId: 'c1',
    });
    const fx = makeRoutedTaskFx('c1', 't1', {
      setStreaming: vi.fn(),
      setError: vi.fn(),
    });
    // 任务专属实例的陈旧快照：只含起任务时刻的对话
    fx.syncSnapshot({
      conversations: [meta('c1', '会话1')],
      activeConversationId: 'c1',
    } as unknown as ServerStateSnapshot);
    // 标签栏不得被缩：4 个对话原样保留，活跃态也不被陈旧快照改写
    expect(convState.list.map((c) => c.id)).toEqual(['c1', 'c2', 'c3', 'c4']);
    expect(convState.activeId).toBe('c1');
  });

  it('后台对话任务快照同样不回写（防陈旧清单串标签栏）', () => {
    setConvState({
      list: [meta('c1', '会话1'), meta('c2', '新会话2')],
      activeId: 'c2',
    });
    const fx = makeRoutedTaskFx('c1', 't1', {
      setStreaming: vi.fn(),
      setError: vi.fn(),
    });
    fx.syncSnapshot({ conversations: [] } as unknown as ServerStateSnapshot);
    expect(convState.list).toHaveLength(2);
    expect(convState.activeId).toBe('c2');
  });
});
