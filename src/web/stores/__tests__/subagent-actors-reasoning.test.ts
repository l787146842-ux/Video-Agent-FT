/**
 * 子代理思考进 actor 卡（2026-09-21 批G，事故 4444/Q4）。
 *
 * 背景：4444 子代理走**非流式通道**（`planner._launch_subagent` 不传
 * `stream_hook`）→ `reasoning_delta` 永不触发 → 主 Feed 的 actor 卡看不到
 * 子代理思考（只有做完后在只读记录里可见）。
 *
 * 修复两处**必须同批**：
 * ① 后端：子级走流式 + `reasoning_delta` 帧补 `subagent` 标记；
 * ② 前端：带标记的 reasoning 帧进 actor 域（**不进父代理思考面板**），
 *    actor 卡内可展开查看（超上限按尾部截断）。
 *
 * 钉死契约：
 * ① 带 subagent 标记的 reasoning_delta → 进 actor 域，**不进** appendReasoning；
 * ② 无标记的 reasoning_delta → 逐字走原路径（父代理思考零变化）；
 * ③ actor 累加思考；超上限截断保留**尾部**（最新进展优先）；
 * ④ 多个子代理的思考各归各卡（不串）。
 */
/// <reference types="node" />
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { SseEvent, SseSubagentMeta } from '@/types';

const appendReasoningMock = vi.fn();
const subagentEventMock = vi.fn();
const subagentDelegateMock = vi.fn();

vi.mock('@/stores/chat', () => ({
  chatActions: {
    startStream: vi.fn(), streamError: vi.fn(), setStatus: vi.fn(),
    systemNotice: vi.fn(), appendDelta: vi.fn(),
    appendReasoning: (t: string) => appendReasoningMock(t),
    toolStarted: vi.fn(), toolFinished: vi.fn(), docWritten: vi.fn(),
    addMessage: vi.fn(), removeQueuedMessage: vi.fn(),
    restoreStreamingState: vi.fn(), clearStreaming: vi.fn(),
    loadMessages: vi.fn(), applyDecisionForm: vi.fn(),
    finishStream: vi.fn(), cancelStream: vi.fn(),
  },
}));

import { routeSseEvent } from '@/lib/sse-events';

const META: SseSubagentMeta = { cid: 'conv-sub-1', stage: 'storyboard_key_elements', label: '关键元素拆解', depth: 1 };

function fx() {
  return {
    chat: {
      startStream: vi.fn(), streamError: vi.fn(), setStatus: vi.fn(),
      systemNotice: vi.fn(), appendDelta: vi.fn(),
      appendReasoning: (t: string) => appendReasoningMock(t),
      toolStarted: vi.fn(), toolFinished: vi.fn(), docWritten: vi.fn(),
      addMessage: vi.fn(), removeQueuedMessage: vi.fn(),
      restoreStreamingState: vi.fn(), clearStreaming: vi.fn(),
      loadMessages: vi.fn(), applyDecisionForm: vi.fn(),
      finishStream: vi.fn(), cancelStream: vi.fn(),
    },
    setStreaming: vi.fn(), setAgentBusy: vi.fn(), setErrorText: vi.fn(),
    syncSnapshot: vi.fn(), markBoardApplied: vi.fn(), applyFallbackModel: vi.fn(),
    toast: vi.fn(), insertMedia: vi.fn(), refreshHistory: vi.fn(),
    subagentEvent: (m: SseSubagentMeta, ev: SseEvent) => subagentEventMock(m, ev),
    subagentDelegate: (ev: SseEvent) => subagentDelegateMock(ev),
    now: () => 1,
  };
}

function ctx(f: ReturnType<typeof fx>) {
  return { fx: f, isRecovering: () => false, hasOwnership: () => true, finalize: vi.fn() };
}

beforeEach(() => {
  appendReasoningMock.mockClear();
  subagentEventMock.mockClear();
  subagentDelegateMock.mockClear();
});

describe('批G：reasoning_delta 分流（子代理思考不串台）', () => {
  it('① 带 subagent 标记 → 进 actor 域，不进父代理思考面板', () => {
    const f = fx();
    routeSseEvent({ type: 'reasoning_delta', text: '我先读剧本。', subagent: META } as SseEvent, ctx(f));
    expect(subagentEventMock).toHaveBeenCalledTimes(1);
    const [meta, ev] = subagentEventMock.mock.calls[0];
    expect(meta).toEqual(META);
    expect((ev as { text?: string }).text).toBe('我先读剧本。');
    // 关键：父面板**不得**收到这段思考
    expect(appendReasoningMock).not.toHaveBeenCalled();
  });

  it('② 无标记 → 逐字走原路径（父代理思考零变化）', () => {
    const f = fx();
    routeSseEvent({ type: 'reasoning_delta', text: '我在规划。' } as SseEvent, ctx(f));
    expect(appendReasoningMock).toHaveBeenCalledWith('我在规划。');
    expect(subagentEventMock).not.toHaveBeenCalled();
  });
});

describe('批G：actor 域思考累计与截断', () => {
  it('③ 累加思考；超上限按尾部截断（最新进展优先）', async () => {
    const mod = await import('@/stores/chat/subagent-actors');
    mod.resetSubagentActors();
    const { subagentActorActions, actorByKey, SUBAGENT_REASONING_CAP } = mod;

    subagentActorActions.applyChildEvent(META, {
      type: 'reasoning_delta', text: '第一段。',
    } as SseEvent);
    expect(actorByKey('conv-sub-1')?.reasoning).toBe('第一段。');

    subagentActorActions.applyChildEvent(META, {
      type: 'reasoning_delta', text: '第二段。',
    } as SseEvent);
    expect(actorByKey('conv-sub-1')?.reasoning).toBe('第一段。第二段。');

    // 超上限：保留尾部 + 省略前缀标记
    subagentActorActions.applyChildEvent(META, {
      type: 'reasoning_delta', text: 'X'.repeat(SUBAGENT_REASONING_CAP + 500),
    } as SseEvent);
    const r = actorByKey('conv-sub-1')?.reasoning || '';
    expect(r.length).toBeLessThanOrEqual(SUBAGENT_REASONING_CAP + 1); // +1 = 省略号
    expect(r.startsWith('…')).toBe(true);
  });

  it('④ 多个子代理的思考各归各卡（不串）', async () => {
    const mod = await import('@/stores/chat/subagent-actors');
    mod.resetSubagentActors();
    const { subagentActorActions, actorByKey } = mod;
    const metaB: SseSubagentMeta = { cid: 'conv-sub-2', stage: 'script_analyze', label: '剧本分析', depth: 1 };

    subagentActorActions.applyChildEvent(META, { type: 'reasoning_delta', text: 'A 的思考' } as SseEvent);
    subagentActorActions.applyChildEvent(metaB, { type: 'reasoning_delta', text: 'B 的思考' } as SseEvent);

    expect(actorByKey('conv-sub-1')?.reasoning).toBe('A 的思考');
    expect(actorByKey('conv-sub-2')?.reasoning).toBe('B 的思考');
  });

  it('⑤ 非 reasoning 事件不进 reasoning 字段（工具帧照旧）', async () => {
    const mod = await import('@/stores/chat/subagent-actors');
    mod.resetSubagentActors();
    const { subagentActorActions, actorByKey } = mod;

    subagentActorActions.applyChildEvent(META, {
      type: 'tool_started', id: 'c1', name: 'read_uploaded_doc', summary: '读剧本',
    } as SseEvent);
    const actor = actorByKey('conv-sub-1');
    expect(actor?.tools).toHaveLength(1);
    expect(actor?.reasoning).toBeUndefined();
  });
});
