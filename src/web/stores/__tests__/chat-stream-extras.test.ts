/**
 * chat store 补强测试（前端回归防护：只加测试不改行为）。
 *
 * 补齐 chat.test.ts 未覆盖的状态机分支：
 * 深度思考增量/工具时间线（toolStarted/toolFinished）、流式恢复与清理、
 * finishStream 的 meta 组合与字段白名单、streamError 设置跳转判定、
 * 排队「引导」移队首。纯状态断言，不依赖 DOM。
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { chatState, chatActions, setChatState } from '../chat';
import { registerQueueStorageKey } from '@/lib/chat/queue-storage';
import type { SseDonePayload, AgentTraceStep } from '@/types';

const donePayload = (extra?: Partial<SseDonePayload>): SseDonePayload => ({
  text: 'ok', elapsed_ms: 1000, steps: 1, applied_actions: 0, ...extra,
});

const traceStep = (step: number, tokenUsage: number): AgentTraceStep => ({
  step, timing_ms: 100, token_usage: tokenUsage, actions_applied: 0, finish_reason: 'stop',
});

describe('chatActions 深度思考与工具时间线', () => {
  beforeEach(() => {
    chatActions.loadMessages([]);
    chatActions.clearStreaming();
  });

  it('appendReasoning 累积文本、记录首末时刻并切换状态文案', () => {
    chatActions.startStream();
    chatActions.appendReasoning('先想');
    const startMs = chatState.turnLedger.reasoningStartMs;
    expect(startMs).toBeGreaterThan(0);
    expect(chatState.turnLedger.reasoning).toBe('先想');
    expect(chatState.turnLedger.statusText).toBe('深度思考中…');
    chatActions.appendReasoning('再想');
    expect(chatState.turnLedger.reasoning).toBe('先想再想');
    expect(chatState.turnLedger.reasoningStartMs).toBe(startMs); // 起点只记一次
    expect(chatState.turnLedger.reasoningEndMs).toBeGreaterThanOrEqual(startMs);
  });

  it('toolStarted 追加运行态条目（带起点）并更新状态栏', () => {
    chatActions.startStream();
    chatActions.toolStarted('t1', 'image_generate', '生图');
    expect(chatState.turnLedger.items.length).toBe(1);
    expect(chatState.turnLedger.items[0].status).toBe('running');
    expect(chatState.turnLedger.items[0].started_at_ms).toBeGreaterThan(0);
    expect(chatState.turnLedger.statusText).toContain('生图');
  });

  it('toolFinished 落完成态（耗时/结果摘要/规划标记）；失败态落 failed', () => {
    chatActions.startStream();
    chatActions.toolStarted('t1', 'audio_generate', '音频');
    chatActions.toolFinished('t1', true, 1200, '产出 3 段音频', true);
    const ok = chatState.turnLedger.items[0];
    expect(ok.status).toBe('done');
    expect(ok.elapsed_ms).toBe(1200);
    expect(ok.result_summary).toBe('产出 3 段音频');
    expect(ok.planning).toBe(true);
    chatActions.toolStarted('t2', 'gen', '生图');
    chatActions.toolFinished('t2', false, 50);
    expect(chatState.turnLedger.items[1].status).toBe('failed');
  });

  it('toolFinished 对未知 id 静默无副作用', () => {
    chatActions.startStream();
    chatActions.toolFinished('ghost', true, 10);
    expect(chatState.turnLedger.items.length).toBe(0);
  });

  it('setStatus 直写状态栏', () => {
    chatActions.startStream();
    chatActions.setStatus('自定义状态');
    expect(chatState.turnLedger.statusText).toBe('自定义状态');
  });
});

describe('chatActions finishStream 分支补齐', () => {
  beforeEach(() => {
    chatActions.loadMessages([]);
    chatActions.clearStreaming();
  });

  it('空文本回落「空回复」；token 账目进 meta', () => {
    chatActions.startStream();
    chatActions.finishStream(donePayload({
      text: '   ',
      trace: { steps: [traceStep(1, 120), traceStep(2, 80)] },
    }));
    const msg = chatState.messages[0];
    expect(msg.text).toBe('（空回复）');
    expect(msg.meta).toContain('200 tokens');
  });

  it('pause_kind 白名单收窄：合法值入库，未知值不入库', () => {
    chatActions.startStream();
    chatActions.finishStream(donePayload({ pause_kind: 'remind', pause_id: 'p1', confirmation: '补料' }));
    expect(chatState.messages[0].kind).toBe('remind');
    expect(chatState.messages[0].pauseId).toBe('p1');
    chatActions.startStream();
    chatActions.finishStream(donePayload({ pause_kind: 'bogus_kind' }));
    expect(chatState.messages[1].kind).toBeUndefined();
  });

  it('fallback_model 优先于 streamingModel 作为气泡标注', () => {
    chatActions.startStream('主模型');
    chatActions.finishStream(donePayload({ fallback_model: '备模型' }));
    expect(chatState.messages[0].modelName).toBe('备模型');
  });

  it('warnings/suggestedActions 有值才入库（空清单不入库）', () => {
    chatActions.startStream();
    chatActions.finishStream(donePayload({
      warnings: ['降级提示'],
      suggested_actions: [{ kind: 'retry', label: '重试', value: '' }],
    }));
    const withExtras = chatState.messages[0];
    expect(withExtras.warnings).toEqual(['降级提示']);
    expect(withExtras.suggestedActions).toHaveLength(1);
    chatActions.startStream();
    chatActions.finishStream(donePayload({ warnings: [], suggested_actions: [] }));
    const plain = chatState.messages[1];
    expect(plain.warnings).toBeUndefined();
    expect(plain.suggestedActions).toBeUndefined();
  });

  it('深度思考耗时角标 = 末条 reasoning - 首条（无思考则不挂）', () => {
    chatActions.startStream();
    setChatState('turnLedger', 'reasoningStartMs', 1000);
    setChatState('turnLedger', 'reasoningEndMs', 3500);
    chatActions.finishStream(donePayload());
    expect(chatState.messages[0].thinkingMs).toBe(2500);
    chatActions.startStream();
    chatActions.finishStream(donePayload());
    expect(chatState.messages[1].thinkingMs).toBeUndefined();
  });
});

describe('chatActions 错误/恢复/清理分支', () => {
  beforeEach(() => {
    chatActions.loadMessages([]);
    chatActions.clearStreaming();
  });

  it('streamError 鉴权类错误挂设置跳转提示，其余不挂；原始报文进折叠（按 kind 查映射表）', () => {
    chatActions.startStream();
    chatActions.streamError({
      code: 'err.auth.invalid_key', kind: 'auth', message: '鉴权失败（HTTP 401）', raw: 'raw body',
    });
    expect(chatState.messages[0].settingsHint).toBe(true);
    expect(chatState.messages[0].errorDetail).toBe('raw body');
    expect(chatState.messages[0].errorKind).toBe('auth');
    chatActions.startStream();
    chatActions.streamError({ code: 'err.network.timeout', kind: 'network', message: '网络超时' });
    expect(chatState.messages[1].settingsHint).toBe(false);
    expect(chatState.messages[1].errorDetail).toBeUndefined();
    expect(chatState.messages[1].errorKind).toBe('network');
  });

  it('restoreStreamingState 整体回放累计状态；有 reasoning 时以恢复时刻重新计时', () => {
    chatActions.restoreStreamingState({
      reasoning: '已有思考', text: '已有正文', statusText: '恢复中',
      tools: [{ id: 't1', name: 'x', summary: 's', status: 'done' }], model: 'm1',
    });
    expect(chatState.isStreaming).toBe(true);
    expect(chatState.turnLedger.reasoning).toBe('已有思考');
    expect(chatState.streamingText).toBe('已有正文');
    expect(chatState.turnLedger.items).toHaveLength(1);
    expect(chatState.turnLedger.reasoningStartMs).toBeGreaterThan(0);
    chatActions.clearStreaming();
    chatActions.restoreStreamingState({ text: '' });
    expect(chatState.turnLedger.reasoningStartMs).toBe(0);
    expect(chatState.turnLedger.reasoningEndMs).toBe(0);
  });

  it('clearStreaming 只清流式字段不产生消息（重连发现已完成的收尾语义）', () => {
    chatActions.startStream();
    chatActions.appendDelta('半截文本');
    chatActions.clearStreaming();
    expect(chatState.isStreaming).toBe(false);
    expect(chatState.streamingText).toBe('');
    expect(chatState.messages.length).toBe(0);
  });
});

describe('排队「引导」移队首', () => {
  beforeEach(() => {
    localStorage.clear();
    registerQueueStorageKey(() => 'ftdyb.queued.p1.conv-x');
    chatActions.clearQueuedMessages();
  });

  it('moveQueuedToFront 把目标移到队首并落盘；未知 id 不变更', () => {
    const q = (id: string) => ({ id, text: id, displayText: id, parts: [] });
    chatActions.enqueueMessage(q('q1'));
    chatActions.enqueueMessage(q('q2'));
    chatActions.enqueueMessage(q('q3'));
    chatActions.moveQueuedToFront('q2');
    expect(chatState.queuedMessages.map((m) => m.id)).toEqual(['q2', 'q1', 'q3']);
    const saved = JSON.parse(localStorage.getItem('ftdyb.queued.p1.conv-x') || '[]');
    expect(saved.map((m: { id: string }) => m.id)).toEqual(['q2', 'q1', 'q3']);
    chatActions.moveQueuedToFront('ghost');
    expect(chatState.queuedMessages.map((m) => m.id)).toEqual(['q2', 'q1', 'q3']);
  });
});
