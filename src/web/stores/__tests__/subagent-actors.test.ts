/**
 * stores/chat/subagent-actors 子代理 actor 归组单测（流式二期，计划书 §五）。
 *
 * 钉死：
 * ① 归组：同一子代理的一串子事件只产一张 actor 卡（账本里只占一个槽位条目，
 *    子工具不再各占一行普通工具卡）；
 * ② 状态迁移：running →（父 run_subagent 收尾帧）completed / failed，
 *    非委派帧不误认领（锚点 id 过滤）；
 * ③ 分流：带 subagent 标记的帧只进 actor 域、不落普通工具卡；父自身帧照旧
 *    （委派锚点卡保留）；子级 state_refresh 的故事板刷新腿不受影响（两腿都在）；
 * ④ 归组键：cid 优先，cid 空（降级不落流）按 label#depth 兜底；
 * ⑤ actor 槽位不入操作计数（父委派卡已计一次，防一次委派算两次）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { routeSseEvent, type SseEventCtx, type SseEventFx } from '@/lib/sse-events';
import { SUBAGENT_ACTOR, countableItems } from '@/lib/turn-ledger';
import type { SseEvent, SseSubagentMeta } from '@/types';
import { chatState, chatActions } from '../chat';
import {
  subagentActorActions, subagentActors, actorByKey, actorKeyOf, actorSlotId,
  resetSubagentActors, SUBAGENT_DELEGATE_TOOL,
} from '../chat/subagent-actors';

const META: SseSubagentMeta = {
  cid: 'conv-sub-1', stage: 'script_analyze', label: '剧本分析', depth: 1,
};

beforeEach(() => {
  resetSubagentActors();
  chatActions.loadMessages([]);
  chatActions.startStream('model-A');   // 建立本轮空账本
});

describe('子事件归组（一个子代理 = 一张 actor 卡）', () => {
  it('子工具起止只产一张卡一个槽位，工具进卡内名单（不散落主 Feed）', () => {
    subagentActorActions.applyChildEvent(META, {
      type: 'tool_started', id: 'c1', name: 'read_uploaded_doc', summary: '读剧本',
    } as SseEvent);
    subagentActorActions.applyChildEvent(META, {
      type: 'tool_finished', id: 'c1', ok: true, elapsed_ms: 12, result_summary: '读完',
    } as SseEvent);
    subagentActorActions.applyChildEvent(META, {
      type: 'tool_started', id: 'c2', name: 'script_analysis_report', summary: '交分析',
    } as SseEvent);

    expect(subagentActors()).toHaveLength(1);
    const actor = actorByKey('conv-sub-1');
    expect(actor?.label).toBe('剧本分析');
    expect(actor?.stage).toBe('script_analyze');
    expect(actor?.depth).toBe(1);
    expect(actor?.status).toBe('running');
    expect(actor?.tools.map((tl) => `${tl.id}:${tl.status}`)).toEqual(['c1:done', 'c2:running']);
    expect(actor?.tools[0].resultSummary).toBe('读完');
    expect(actor?.tools[0].elapsedMs).toBe(12);

    // 账本里只有一个 actor 槽位条目，没有子工具的普通条目
    const items = chatState.turnLedger.items;
    expect(items).toHaveLength(1);
    expect(items[0].name).toBe(SUBAGENT_ACTOR);
    expect(items[0].id).toBe(actorSlotId('conv-sub-1'));
    expect(items[0].summary).toBe('剧本分析');
    expect(items[0].status).toBe('running');
  });

  it('重复 tool_started（replay 与增量同源双达）按 id upsert，不双登工具', () => {
    const ev = {
      type: 'tool_started', id: 'c1', name: 'read_draft', summary: '读草稿',
    } as SseEvent;
    subagentActorActions.applyChildEvent(META, ev);
    subagentActorActions.applyChildEvent(META, ev);
    expect(actorByKey('conv-sub-1')?.tools).toHaveLength(1);
    expect(chatState.turnLedger.items).toHaveLength(1);
  });

  it('子级 state_refresh（actions_applied）→ 步数递增', () => {
    subagentActorActions.applyChildEvent(META, {
      type: 'actions_applied', payload: { count: 2 },
    } as SseEvent);
    subagentActorActions.applyChildEvent(META, {
      type: 'actions_applied', count: 1,
    } as SseEvent);
    expect(actorByKey('conv-sub-1')?.steps).toBe(3);
  });
});

describe('状态迁移（父委派帧收尾）', () => {
  it('父 run_subagent 起止 → completed；在途子工具定型，槽位翻完成态', () => {
    subagentActorActions.applyDelegateEvent({
      type: 'tool_started', id: 'p1', name: SUBAGENT_DELEGATE_TOOL, summary: '委派子代理',
    } as SseEvent);
    subagentActorActions.applyChildEvent(META, {
      type: 'tool_started', id: 'c1', name: 'read_draft', summary: '读草稿',
    } as SseEvent);
    subagentActorActions.applyDelegateEvent({
      type: 'tool_finished', id: 'p1', ok: true, elapsed_ms: 900,
    } as SseEvent);

    const actor = actorByKey('conv-sub-1');
    expect(actor?.status).toBe('completed');
    expect(actor?.finishedAt).toBeGreaterThan(0);
    expect(actor?.tools[0].status).toBe('done');   // 旋转图标不留
    expect(chatState.turnLedger.items[0].status).toBe('done');
  });

  it('委派失败（ok=false）→ failed，在途子工具同判失败', () => {
    subagentActorActions.applyDelegateEvent({
      type: 'tool_started', id: 'p1', name: SUBAGENT_DELEGATE_TOOL, summary: '委派',
    } as SseEvent);
    subagentActorActions.applyChildEvent(META, {
      type: 'tool_started', id: 'c1', name: 'x', summary: '子工具',
    } as SseEvent);
    subagentActorActions.applyDelegateEvent({
      type: 'tool_finished', id: 'p1', ok: false, elapsed_ms: 10,
    } as SseEvent);

    expect(actorByKey('conv-sub-1')?.status).toBe('failed');
    expect(actorByKey('conv-sub-1')?.tools[0].status).toBe('failed');
    expect(chatState.turnLedger.items[0].status).toBe('failed');
  });

  it('非委派工具的收尾帧不误认领（锚点 id 过滤，actor 仍 running）', () => {
    subagentActorActions.applyChildEvent(META, {
      type: 'tool_started', id: 'c1', name: 'x', summary: '子工具',
    } as SseEvent);
    subagentActorActions.applyDelegateEvent({
      type: 'tool_finished', id: 'other-tool', ok: true, elapsed_ms: 1,
    } as SseEvent);
    expect(actorByKey('conv-sub-1')?.status).toBe('running');
  });

  it('两次委派（串行）各归各卡，收尾只动最近一个 running', () => {
    const second: SseSubagentMeta = {
      cid: 'conv-sub-2', stage: 'write_media_prompt', label: '媒体提示词编写', depth: 1,
    };
    subagentActorActions.applyDelegateEvent({
      type: 'tool_started', id: 'p1', name: SUBAGENT_DELEGATE_TOOL, summary: '委派一',
    } as SseEvent);
    subagentActorActions.applyChildEvent(META, {
      type: 'tool_started', id: 'c1', name: 'x', summary: '子工具',
    } as SseEvent);
    subagentActorActions.applyDelegateEvent({
      type: 'tool_finished', id: 'p1', ok: true, elapsed_ms: 10,
    } as SseEvent);

    subagentActorActions.applyDelegateEvent({
      type: 'tool_started', id: 'p2', name: SUBAGENT_DELEGATE_TOOL, summary: '委派二',
    } as SseEvent);
    subagentActorActions.applyChildEvent(second, {
      type: 'tool_started', id: 'c9', name: 'prompt_draft', summary: '写提示词',
    } as SseEvent);
    subagentActorActions.applyDelegateEvent({
      type: 'tool_finished', id: 'p2', ok: false, elapsed_ms: 10,
    } as SseEvent);

    expect(subagentActors()).toHaveLength(2);
    expect(actorByKey('conv-sub-1')?.status).toBe('completed');
    expect(actorByKey('conv-sub-2')?.status).toBe('failed');
    expect(chatState.turnLedger.items).toHaveLength(2);   // 两张卡两个槽位
  });
});

describe('归组键兜底（计划书 §七风险 C）', () => {
  it('cid 空（降级不落流）→ label#depth 兜底键，仍归一张卡且无记录可点', () => {
    const degraded: SseSubagentMeta = { cid: '', stage: '', label: '写提示词', depth: 1 };
    expect(actorKeyOf(degraded)).toBe('写提示词#1');
    expect(actorKeyOf(META)).toBe('conv-sub-1');

    subagentActorActions.applyChildEvent(degraded, {
      type: 'tool_started', id: 'c1', name: 'x', summary: '子工具',
    } as SseEvent);
    subagentActorActions.applyChildEvent(degraded, {
      type: 'tool_finished', id: 'c1', ok: true, elapsed_ms: 1,
    } as SseEvent);

    expect(subagentActors()).toHaveLength(1);
    expect(actorByKey('写提示词#1')?.cid).toBe('');   // 无隐藏线程 → 卡不可点
    expect(chatState.turnLedger.items).toHaveLength(1);
  });

  it('label 也空 → 键退化为 subagent#depth（不产生空键冲突）', () => {
    expect(actorKeyOf({ cid: '', stage: '', label: '', depth: 1 })).toBe('subagent#1');
  });
});

describe('操作计数口径', () => {
  it('actor 槽位不入 countableItems（父委派卡已计一次操作）', () => {
    subagentActorActions.applyChildEvent(META, {
      type: 'tool_started', id: 'c1', name: 'x', summary: '子工具',
    } as SseEvent);
    const items = [
      { id: 'p1', name: SUBAGENT_DELEGATE_TOOL, summary: '委派', status: 'done' as const },
      ...chatState.turnLedger.items,
    ];
    expect(items).toHaveLength(2);
    expect(countableItems(items)).toHaveLength(1);
    expect(countableItems(items)[0].id).toBe('p1');
  });
});

// ---------- 路由分流（lib/sse-events.routeSseEvent） ----------

/** 最小 fx 假件：只观察分流去向（不驱动真实 store/组件） */
function makeFakeFx() {
  const chat = {
    startStream: vi.fn(), streamError: vi.fn(), setStatus: vi.fn(), systemNotice: vi.fn(),
    appendDelta: vi.fn(), appendReasoning: vi.fn(), toolStarted: vi.fn(), toolFinished: vi.fn(),
    docWritten: vi.fn(), addMessage: vi.fn(), removeQueuedMessage: vi.fn(),
    restoreStreamingState: vi.fn(), clearStreaming: vi.fn(), loadMessages: vi.fn(),
    applyDecisionForm: vi.fn(), finishStream: vi.fn(), cancelStream: vi.fn(),
  };
  return {
    chat,
    setStreaming: vi.fn(), setAgentBusy: vi.fn(), setErrorText: vi.fn(),
    syncSnapshot: vi.fn(), markBoardApplied: vi.fn(), applyFallbackModel: vi.fn(),
    toast: vi.fn(), insertMedia: vi.fn(), refreshHistory: vi.fn(),
    subagentEvent: vi.fn(), subagentDelegate: vi.fn(),
    now: () => 1000,
  };
}

describe('事件分流（routeSseEvent）', () => {
  it('带 subagent 标记的子工具帧 → 只进 actor 域，不落普通工具卡', () => {
    const fx = makeFakeFx();
    const ctx: SseEventCtx = {
      fx: fx as SseEventFx, isRecovering: () => false, hasOwnership: () => true, finalize: vi.fn(),
    };
    routeSseEvent({
      type: 'tool_started', id: 'c1', name: 'read_draft', summary: '读草稿', subagent: META,
    } as SseEvent, ctx);
    routeSseEvent({
      type: 'tool_finished', id: 'c1', ok: true, elapsed_ms: 5, subagent: META,
    } as SseEvent, ctx);

    expect(fx.subagentEvent).toHaveBeenCalledTimes(2);
    expect(fx.subagentEvent.mock.calls[0][0]).toEqual(META);
    expect(fx.chat.toolStarted).not.toHaveBeenCalled();
    expect(fx.chat.toolFinished).not.toHaveBeenCalled();
  });

  it('父自身帧照旧：普通工具卡 + 委派锚点交 actor 域（run_subagent 卡保留）', () => {
    const fx = makeFakeFx();
    const ctx: SseEventCtx = {
      fx: fx as SseEventFx, isRecovering: () => false, hasOwnership: () => true, finalize: vi.fn(),
    };
    routeSseEvent({
      type: 'tool_started', id: 'p1', name: SUBAGENT_DELEGATE_TOOL, summary: '委派子代理',
    } as SseEvent, ctx);
    expect(fx.chat.toolStarted).toHaveBeenCalledWith(
      'p1', SUBAGENT_DELEGATE_TOOL, '委派子代理', undefined, undefined);
    expect(fx.subagentDelegate).toHaveBeenCalledTimes(1);
    expect(fx.subagentEvent).not.toHaveBeenCalled();

    routeSseEvent({
      type: 'tool_finished', id: 'p1', ok: true, elapsed_ms: 900,
    } as SseEvent, ctx);
    expect(fx.chat.toolFinished).toHaveBeenCalledTimes(1);
    expect(fx.subagentDelegate).toHaveBeenCalledTimes(2);
  });

  it('子级 state_refresh：故事板同步腿保留 + actor 计步（两腿都在）', () => {
    const fx = makeFakeFx();
    const ctx: SseEventCtx = {
      fx: fx as SseEventFx, isRecovering: () => false, hasOwnership: () => true, finalize: vi.fn(),
    };
    routeSseEvent({
      type: 'actions_applied', payload: { count: 1, state: { board_version: 3 } }, subagent: META,
    } as unknown as SseEvent, ctx);

    expect(fx.syncSnapshot).toHaveBeenCalledTimes(1);
    expect(fx.markBoardApplied).toHaveBeenCalledTimes(1);
    expect(fx.subagentEvent).toHaveBeenCalledTimes(1);
  });
});
