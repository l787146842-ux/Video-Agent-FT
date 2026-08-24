/**
 * turn-ledger 归一纯函数测试（F2 阶段一：轮次账本数据模型统一）。
 *
 * 钉死契约：
 * ① ledgerFromLive（SSE 累积/replay 快照）与 ledgerFromSettled（trace/actionLog）
 *    输出同构 TurnLedger——同输入语义两侧对拍一致；
 * ② settleLedger 相位翻转复用同一批账目（不二次构造），running→done 不变式；
 * ③ 归一细节：status 白名单收窄、起点缺失以恢复时刻为准、actionLog 兜底。
 */
import { describe, it, expect } from 'vitest';
import {
  emptyLedger, ledgerFromLive, ledgerFromSettled, settleLedger, type LedgerItem,
} from '../turn-ledger';

/** 语义投影：id 来源不同（live=SSE 事件 id、settled=重建规则 t-{step}-{i}），
 * 对拍只比语义字段；started_at_ms 为 live 运行态专属（settled 无走秒需求） */
function semantic(it: LedgerItem) {
  return {
    name: it.name,
    summary: it.summary,
    status: it.status,
    elapsed_ms: it.elapsed_ms,
    result_summary: it.result_summary,
    planning: it.planning,
    args: it.args,
  };
}

describe('emptyLedger（空账本）', () => {
  it('默认 live 相位全零；statusText 可注入连接中文案', () => {
    const led = emptyLedger('正在连接…');
    expect(led.phase).toBe('live');
    expect(led.reasoning).toBe('');
    expect(led.items).toEqual([]);
    expect(led.statusText).toBe('正在连接…');
    expect(led.reasoningStartMs).toBe(0);
    expect(led.reasoningEndMs).toBe(0);
    expect(led.thinkingMs).toBeUndefined();
  });
});

describe('ledgerFromLive（live 归一入口）', () => {
  it('空输入归一为空 live 账本', () => {
    const led = ledgerFromLive();
    expect(led.phase).toBe('live');
    expect(led.items).toEqual([]);
    expect(led.reasoning).toBe('');
  });

  it('status 白名单收窄：未知态归 running（防类型退化）', () => {
    // 后端 replay 快照为弱类型字符串，此处按运行时真实形态注入未知值
    const bogus = 'bogus' as unknown as LedgerItem['status'];
    const led = ledgerFromLive({
      now: 5000,
      tools: [
        { id: 'a', summary: '甲', status: 'done' },
        { id: 'b', summary: '乙', status: 'failed' },
        { id: 'c', summary: '丙', status: bogus },
        { id: 'd', summary: '丁' },
      ],
    });
    expect(led.items.map((i) => i.status)).toEqual(['done', 'failed', 'running', 'running']);
  });

  it('running 条目无走秒起点时以恢复时刻 now 为准', () => {
    const led = ledgerFromLive({ now: 1771234567, tools: [{ id: 't1', summary: '生图' }] });
    expect(led.items[0].started_at_ms).toBe(1771234567);
  });

  it('有 reasoning 时以恢复时刻记录思考首末时刻；无思考恒 0', () => {
    const withR = ledgerFromLive({ now: 900, reasoning: '思考片段' });
    expect(withR.reasoningStartMs).toBe(900);
    expect(withR.reasoningEndMs).toBe(900);
    const noR = ledgerFromLive({ now: 900 });
    expect(noR.reasoningStartMs).toBe(0);
    expect(noR.reasoningEndMs).toBe(0);
  });

  it('planning/args/result_summary 透传；summary 缺失回落 name', () => {
    const led = ledgerFromLive({
      tools: [{
        id: 't1', name: 'gen_image', status: 'done', elapsed_ms: 900,
        result_summary: '出图完成', planning: true, args: { prompt: '赛博海报' },
      }],
    });
    const it = led.items[0];
    expect(it.summary).toBe('gen_image');
    expect(it.planning).toBe(true);
    expect(it.args).toEqual({ prompt: '赛博海报' });
    expect(it.result_summary).toBe('出图完成');
    expect(it.elapsed_ms).toBe(900);
  });
});

describe('ledgerFromSettled（settled 归一入口）', () => {
  it('trace 多轮 reasoning 换行拼接；actions 逐条归一', () => {
    const led = ledgerFromSettled({
      trace: {
        steps: [
          { step: 1, timing_ms: 100, token_usage: 0, actions_applied: 0, finish_reason: 'stop', reasoning: '第一段思考', actions: [{ name: 'script_analyze', summary: '分析剧本', ok: true, elapsed_ms: 800 }] },
          { step: 2, timing_ms: 100, token_usage: 0, actions_applied: 0, finish_reason: 'stop', reasoning: '第二段思考', actions: [{ name: 'gen', summary: '生图', ok: false, elapsed_ms: 50 }] },
        ],
      },
    });
    expect(led.phase).toBe('settled');
    expect(led.reasoning).toBe('第一段思考\n第二段思考');
    expect(led.items[0].id).toBe('t-1-0');
    expect(led.items[0].status).toBe('done');
    expect(led.items[1].id).toBe('t-2-0');
    expect(led.items[1].status).toBe('failed');
  });

  it('model_reasoning 条目归一为 llm-s{step} 同构 id（命中合并降噪）', () => {
    const led = ledgerFromSettled({
      trace: { steps: [{ step: 2, timing_ms: 1, token_usage: 0, actions_applied: 0, finish_reason: 'stop', actions: [{ name: 'model_reasoning', summary: '规划', ok: true, elapsed_ms: 5 }] }] },
    });
    expect(led.items[0].id).toBe('llm-s2');
  });

  it('旧消息无 actions 时 actionLog 兜底（l-{i} 条目）', () => {
    const led = ledgerFromSettled({ actionLog: ['写入文档', '生图'] });
    expect(led.items.map((i) => i.id)).toEqual(['l-0', 'l-1']);
    expect(led.items.map((i) => i.summary)).toEqual(['写入文档', '生图']);
    expect(led.items.every((i) => i.status === 'done')).toBe(true);
  });

  it('thinkingMs 有值才挂（0 视同无）', () => {
    expect(ledgerFromSettled({ thinkingMs: 2500 }).thinkingMs).toBe(2500);
    expect(ledgerFromSettled({ thinkingMs: 0 }).thinkingMs).toBeUndefined();
    expect(ledgerFromSettled({}).thinkingMs).toBeUndefined();
  });
});

describe('settleLedger（相位翻转：live→settled）', () => {
  const live = () => ({
    ...emptyLedger('正在执行…'),
    reasoning: '思考留痕',
    reasoningStartMs: 1000,
    reasoningEndMs: 3500,
    items: [
      { id: 't1', summary: '生图', status: 'done' as const, elapsed_ms: 900 },
      { id: 't2', summary: '未完成项', status: 'running' as const },
    ],
  });

  it('翻转相位并复用同一批账目（条数/摘要/耗时不变，不二次构造）', () => {
    const before = live();
    const settled = settleLedger(before, { turnId: 'turn-x' });
    expect(settled.phase).toBe('settled');
    expect(settled.turnId).toBe('turn-x');
    expect(settled.reasoning).toBe('思考留痕');
    expect(settled.items).toHaveLength(2);
    expect(settled.items[0].summary).toBe('生图');
    expect(settled.items[0].elapsed_ms).toBe(900);
    // settled 轮次无 running（与 trace 重建「完成后不出现旋转图标」不变式对齐）
    expect(settled.items[1].status).toBe('done');
    // 翻转不改动原 live 账本（纯函数）
    expect(before.items[1].status).toBe('running');
    expect(before.phase).toBe('live');
    // 状态栏文案随相位清空（settled 无 live 状态语义）
    expect(settled.statusText).toBe('');
  });

  it('thinkingMs 挂账本（角标数据随相位迁移）', () => {
    expect(settleLedger(live(), { thinkingMs: 2500 }).thinkingMs).toBe(2500);
    expect(settleLedger(live()).thinkingMs).toBeUndefined();
  });

  it('turnId 缺省保留 live 账本自带值', () => {
    const led = { ...live(), turnId: 'turn-live' };
    expect(settleLedger(led).turnId).toBe('turn-live');
  });
});

describe('live/settled 对拍（同输入语义 → 同构输出）', () => {
  it('单轮工具账目与思考文本：两侧归一语义一致、账本形态同构', () => {
    const live = ledgerFromLive({
      tools: [{
        id: 't1', name: 'script_analyze', summary: '分析剧本', status: 'done',
        elapsed_ms: 800, result_summary: '分析完成',
      }],
      reasoning: '先评估素材，再决定拆分方案',
      statusText: '正在回复…',
    });
    const settled = ledgerFromSettled({
      trace: {
        steps: [{
          step: 1, timing_ms: 900, token_usage: 0, actions_applied: 1, finish_reason: 'stop',
          reasoning: '先评估素材，再决定拆分方案',
          actions: [{ name: 'script_analyze', summary: '分析剧本', ok: true, elapsed_ms: 800, result_summary: '分析完成' }],
        }],
      },
    });

    // 相位语义各自正确
    expect(live.phase).toBe('live');
    expect(settled.phase).toBe('settled');
    // 账本顶层形态同构（键集与键序一致）
    expect(Object.keys(live)).toEqual(Object.keys(settled));
    // 思考文本一致
    expect(live.reasoning).toBe(settled.reasoning);
    // 条目语义逐条一致（id 来源不同不参与对拍）
    expect(live.items.length).toBe(settled.items.length);
    expect(live.items.map(semantic)).toEqual(settled.items.map(semantic));
  });

  it('live 翻转后与 settled 重建对拍一致（相位翻转 = 同一账目换相位）', () => {
    const flipped = settleLedger(ledgerFromLive({
      tools: [
        { id: 't1', name: 'doc_write', summary: '写入文档', status: 'done', elapsed_ms: 120, planning: true, args: { content: '预览' } },
        { id: 't2', name: 'gen', summary: '生图', status: 'failed', elapsed_ms: 50 },
      ],
      reasoning: '规划中',
    }), { thinkingMs: 800 });
    const rebuilt = ledgerFromSettled({
      trace: {
        steps: [{
          step: 1, timing_ms: 900, token_usage: 0, actions_applied: 0, finish_reason: 'stop',
          reasoning: '规划中',
          actions: [
            { name: 'doc_write', summary: '写入文档', ok: true, elapsed_ms: 120, planning: true, args: { content: '预览' } },
            { name: 'gen', summary: '生图', ok: false, elapsed_ms: 50 },
          ],
        }],
      },
      thinkingMs: 800,
    });
    expect(flipped.phase).toBe(rebuilt.phase);
    expect(flipped.reasoning).toBe(rebuilt.reasoning);
    expect(flipped.thinkingMs).toBe(rebuilt.thinkingMs);
    expect(flipped.items.map(semantic)).toEqual(rebuilt.items.map(semantic));
  });

  it('空轮对拍：两侧均归一为空账本（形态同构）', () => {
    const live = ledgerFromLive();
    const settled = ledgerFromSettled({});
    expect(Object.keys(live)).toEqual(Object.keys(settled));
    expect(live.items).toEqual([]);
    expect(settled.items).toEqual([]);
    expect(live.reasoning).toBe(settled.reasoning);
  });
});
