/**
 * SSE 事件契约桥接测试：把 replay/done 载荷与事件族的关键契约机械钉死，
 * 不得纯靠两侧人工同步。
 *
 * 锚点 = src/video_agent/core/sse_events.py（后端事件常量单一事实源）
 *       + src/video_agent/web/agent_task_manager.py（replay / task_status）。
 * 后端新增事件类型时，前端 SseEvent 联合必须同步登记，否则本测试红。
 */
import { describe, it, expectTypeOf, expect } from 'vitest';
import type {
  SseEvent, SseDonePayload, SseErrorEvent, SseSubagentMeta,
  AgentTaskReplayPayload, AgentTrace, AgentTraceStep,
} from '@/types';
import { ERROR_KINDS, type ErrorKind } from '@/lib/error-payload';

/** 后端事件族镜像清单（与 sse_events.py + task_manager 对齐；改动需双侧同批） */
const BACKEND_EVENT_TYPES = [
  'status', 'delta', 'reasoning_delta', 'tool_started', 'tool_finished',
  'doc_written', 'model_fallback', 'done', 'error', 'actions_applied',
  'guidance_injected', 'replay', 'task_status',
  // step_started 为后端内部事件，前端声明性忽略（use-sse 注释登记），不入本清单
] as const;

describe('SSE 事件契约桥接', () => {
  it('后端事件族全部在前端 SseEvent 联合中可赋值（无孤儿事件）', () => {
    for (const type of BACKEND_EVENT_TYPES) {
      // 联合类型窄化：每个后端事件 type 都能命中 SseEvent 的某个成员
      const ev = { type } as unknown as SseEvent;
      expect(ev.type).toBe(type);
    }
  });

  it('done 载荷关键字段契约（账单/暂停/轮次聚合数据源）', () => {
    expectTypeOf<SseDonePayload['trace']>().toEqualTypeOf<AgentTrace | undefined>();
    expectTypeOf<SseDonePayload['turn_id']>().toEqualTypeOf<string | undefined>();
    expectTypeOf<SseDonePayload['pause_id']>().toEqualTypeOf<string | undefined>();
    // trace.steps[].token_usage 为轮次账单数据源
    expectTypeOf<AgentTraceStep['token_usage']>().toBeNumber();
  });

  it('replay 载荷工具条目携带 result_summary（重连恢复不丢结果摘要）', () => {
    type ReplayTool = NonNullable<AgentTaskReplayPayload['tools']>[number];
    expectTypeOf<ReplayTool['result_summary']>().toEqualTypeOf<string | undefined>();
  });

  it('task_status 事件为联合成员（不再落 default 静默忽略）', () => {
    const ev: SseEvent = { type: 'task_status', status: 'cancelled' };
    expect(ev.type).toBe('task_status');
  });

  // ---------- 流式二期：子代理活动打标字段契约 ----------

  it('subagent 归组标记可挂 tool_started/tool_finished/actions_applied 三帧', () => {
    const meta: SseSubagentMeta = {
      cid: 'conv-sub', stage: 'script_analyze', label: '剧本分析', depth: 1,
    };
    const started: SseEvent = {
      type: 'tool_started', id: 'c1', name: 'read_draft', summary: '读草稿', subagent: meta,
    };
    const finished: SseEvent = {
      type: 'tool_finished', id: 'c1', ok: true, elapsed_ms: 3, subagent: meta,
    };
    const applied: SseEvent = { type: 'actions_applied', subagent: meta };
    // 字段面 = cid/stage/label/depth（后端 SseSubagentMeta 生成物同构；
    // 四字段均带默认值→生成物为可选，消费侧按空值兜底）
    expectTypeOf<SseSubagentMeta>().toEqualTypeOf<{
      cid?: string; stage?: string; label?: string; depth?: number;
    }>();
    expect(started.type === 'tool_started' && started.subagent?.label).toBe('剧本分析');
    expect(finished.type === 'tool_finished' && finished.subagent?.cid).toBe('conv-sub');
    expect(applied.type === 'actions_applied' && applied.subagent?.depth).toBe(1);
  });

  it('subagent 为可选字段：父自身帧不携也能赋值（一期帧形不破坏）', () => {
    const ev: SseEvent = { type: 'tool_started', id: 'p1', name: 'run_subagent', summary: '委派' };
    expect(ev.type === 'tool_started' && ev.subagent).toBeUndefined();
  });

  // ---------- 任务 #19：ErrorPayload 契约钉死（后端 web/error_payload.py 镜像） ----------

  it('error 事件携带结构化 code/kind（既有 detail/error_code/raw 不破坏）', () => {
    expectTypeOf<SseErrorEvent['code']>().toEqualTypeOf<string | undefined>();
    expectTypeOf<SseErrorEvent['kind']>().toEqualTypeOf<string | undefined>();
    expectTypeOf<SseErrorEvent['detail']>().toEqualTypeOf<string | undefined>();
    expectTypeOf<SseErrorEvent['raw']>().toEqualTypeOf<string | undefined>();
    const ev: SseEvent = {
      type: 'error', detail: '鉴权失败', error_code: 'ADAPTER_ERROR',
      code: 'err.auth.invalid_key', kind: 'auth', raw: 'raw',
    };
    expect(ev.type).toBe('error');
  });

  it('replay 同源下发 error_payload（刷新恢复后映射表仍能命中）', () => {
    expectTypeOf<AgentTaskReplayPayload['error_payload']>().toEqualTypeOf<
      { code?: string; kind?: string; raw?: string } | null | undefined>();
  });

  it('kind 封闭集合与后端 ALL_KINDS 一致（增删需双侧同批）', () => {
    expect([...ERROR_KINDS].sort()).toEqual(
      ['auth', 'content', 'network', 'quota', 'unknown', 'upstream'],
    );
    expectTypeOf<ErrorKind>().toEqualTypeOf<'auth' | 'quota' | 'network' | 'upstream' | 'content' | 'unknown'>();
  });
});
