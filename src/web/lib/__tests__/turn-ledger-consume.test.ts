/**
 * settledLedgerForMessage 消费面测试（F2 阶段二：渲染统一）。
 *
 * 从 turn-ledger.test.ts 拆出（前端物理行数 250 红线）；
 * 阶段一归一模型对拍用例仍在 turn-ledger.test.ts。
 *
 * 钉死契约：
 * ① 有账目/思考的翻转账本优先消费（不二次重建，引用直返）；
 * ② 空翻转账本（纯文本轮未走工具事件）回落 trace/actionLog 重建，
 *    action_log 兜底路径不丢；
 * ③ 无本地账本（历史/刷新）回落 ledgerFromSettled 同一归一入口；
 * ④ 一致性回落：账本条目少于 trace 动作总数（SSE 丢事件边缘）时
 *    回落服务端权威源重建；账本完整时仍走快路径。
 */
import { describe, it, expect } from 'vitest';
import {
  ledgerFromLive, ledgerFromSettled, settleLedger, settledLedgerForMessage,
} from '../turn-ledger';

describe('settledLedgerForMessage（渲染层单一消费面）', () => {
  it('有账目/思考的翻转账本优先消费（不二次重建）', () => {
    const led = settleLedger(ledgerFromLive({
      tools: [{ id: 't1', name: 'gen', summary: '生图', status: 'running' }],
    }));
    const got = settledLedgerForMessage({ ledger: led, actionLog: ['兜底条目'] });
    expect(got).toBe(led);
    expect(got.items.map((i) => i.summary)).toEqual(['生图']);
  });

  it('仅有思考无账目的翻转账本同样优先消费', () => {
    const led = settleLedger(ledgerFromLive({ reasoning: '账本思考' }));
    const got = settledLedgerForMessage({ ledger: led, actionLog: ['兜底条目'] });
    expect(got).toBe(led);
    expect(got.reasoning).toBe('账本思考');
  });

  it('空翻转账本（纯文本轮）回落 trace/actionLog 重建，action_log 兜底不丢', () => {
    const empty = settleLedger(ledgerFromLive());
    const got = settledLedgerForMessage({
      ledger: empty,
      actionLog: ['新建关键元素分组「主角」'],
    });
    expect(got.phase).toBe('settled');
    expect(got.items.map((i) => i.summary)).toEqual(['新建关键元素分组「主角」']);
  });

  it('无本地账本（历史/刷新）回落 ledgerFromSettled 同一归一入口', () => {
    const got = settledLedgerForMessage({
      trace: {
        steps: [{
          step: 1, timing_ms: 900, token_usage: 0, actions_applied: 1, finish_reason: 'stop',
          reasoning: '历史思考',
          actions: [{ name: 'x', summary: '分析剧本', ok: true, elapsed_ms: 800 }],
        }],
      },
      thinkingMs: 800,
    });
    expect(got.reasoning).toBe('历史思考');
    expect(got.items.map((i) => i.summary)).toEqual(['分析剧本']);
    expect(got.thinkingMs).toBe(800);
    // 与直接调归一入口输出同构（消费面不引入第三种形态）
    expect(got).toEqual(ledgerFromSettled({
      trace: {
        steps: [{
          step: 1, timing_ms: 900, token_usage: 0, actions_applied: 1, finish_reason: 'stop',
          reasoning: '历史思考',
          actions: [{ name: 'x', summary: '分析剧本', ok: true, elapsed_ms: 800 }],
        }],
      },
      thinkingMs: 800,
    }));
  });

  it('账本条目少于 trace 动作总数时回落权威源重建（SSE 丢事件边缘）', () => {
    const led = settleLedger(ledgerFromLive({
      tools: [{ id: 't1', name: 'gen', summary: '生图', status: 'running' }],
    }));
    const got = settledLedgerForMessage({
      ledger: led,
      trace: {
        steps: [{
          step: 1, timing_ms: 900, token_usage: 0, actions_applied: 2, finish_reason: 'stop',
          reasoning: '服务端思考',
          actions: [
            { name: 'gen', summary: '生图', ok: true, elapsed_ms: 500 },
            { name: 'write', summary: '写规格文档', ok: true, elapsed_ms: 300 },
          ],
        }],
      },
    });
    // 重建自 trace：两条动作都在，时间线不缩水
    expect(got).not.toBe(led);
    expect(got.items.map((i) => i.summary)).toEqual(['生图', '写规格文档']);
    expect(got.phase).toBe('settled');
  });

  it('账本条目不少于 trace 动作总数时仍走快路径（引用直返）', () => {
    const led = settleLedger(ledgerFromLive({
      tools: [
        { id: 't1', name: 'gen', summary: '生图', status: 'running' },
        { id: 't2', name: 'write', summary: '写规格文档', status: 'running' },
      ],
    }));
    const got = settledLedgerForMessage({
      ledger: led,
      trace: {
        steps: [{
          step: 1, timing_ms: 900, token_usage: 0, actions_applied: 2, finish_reason: 'stop',
          actions: [
            { name: 'gen', summary: '生图', ok: true, elapsed_ms: 500 },
            { name: 'write', summary: '写规格文档', ok: true, elapsed_ms: 300 },
          ],
        }],
      },
    });
    expect(got).toBe(led);
  });
});
