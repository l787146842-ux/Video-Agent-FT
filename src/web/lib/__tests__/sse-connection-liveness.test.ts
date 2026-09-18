/**
 * lib/sse-connection 活感/断口纯函数单测（D2 批 commit3）。
 *
 * 钉死三件事：
 * ① shouldTripLiveness：静默超时判定为严格大于（刚好等于阈值不跳闸，防边界误报），
 *    阈值 = 服务端 15s 注释心跳的 3 倍（零误报口径），检查间隔细于阈值；
 * ② detectSeqGap：event_seq 断口判定——replay 首帧携高水位（lastSeq=null 不判）、
 *    连续 +1 不跳、跳号跳闸（QueueFull 丢非终态帧类）、重复/回退帧不跳
 *    （replay 与 live 重叠按幂等丢弃，不得误判成断口而无限重连）；
 * ③ parseSseStream 第 4 参 onChunk：字节级活感钩子——注释心跳帧（无 data、零事件）
 *    同样回调（3333 冻屏根因类＝半开死连接，判活靠字节不靠事件）、帧跨块拆分按块计、
 *    解析失败不遮蔽活感、不传该参向后兼容（既有三参调用不受影响）。
 */
import { describe, it, expect, vi } from 'vitest';
import {
  LIVENESS_TIMEOUT_MS, LIVENESS_CHECK_MS, shouldTripLiveness, detectSeqGap,
} from '../sse-connection';
import { parseSseStream } from '../sse-events';
import type { SseEvent } from '@/types';

/** 服务端注释心跳间隔（routes/agent.py：静默满 15s 发 `: heartbeat`） */
const SERVER_HEARTBEAT_MS = 15000;

const enc = new TextEncoder();

/** 假响应：按原始字节块顺序投递后自然关流（心跳是注释帧，不经 data: 包装） */
function rawResponse(chunks: string[]): Response {
  let i = 0;
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () => {
          if (i >= chunks.length) return { done: true as const, value: undefined };
          const value = enc.encode(chunks[i]);
          i += 1;
          return { done: false as const, value };
        },
      }),
    },
  } as unknown as Response;
}

describe('shouldTripLiveness（字节级静默超时判定）', () => {
  it('静默刚好等于阈值不跳闸（严格大于，边界不误报）', () => {
    expect(shouldTripLiveness(1000, 1000 + LIVENESS_TIMEOUT_MS)).toBe(false);
  });

  it('超阈值 1ms 跳闸（半开死连接：无字节无关流，reader.read 永挂）', () => {
    expect(shouldTripLiveness(1000, 1000 + LIVENESS_TIMEOUT_MS + 1)).toBe(true);
  });

  it('心跳刚刷新过不跳闸（注释心跳即活感来源）', () => {
    expect(shouldTripLiveness(50000, 50000 + SERVER_HEARTBEAT_MS)).toBe(false);
  });

  it('阈值可注入（测试与调参不依赖 45s 常量）', () => {
    expect(shouldTripLiveness(0, 100, 50)).toBe(true);
    expect(shouldTripLiveness(0, 50, 50)).toBe(false);
  });

  it('常量契约：45s = 3 个心跳周期；检查间隔 5s 细于阈值且整除', () => {
    expect(LIVENESS_TIMEOUT_MS).toBe(45000);
    expect(LIVENESS_TIMEOUT_MS / SERVER_HEARTBEAT_MS).toBe(3);
    expect(LIVENESS_CHECK_MS).toBe(5000);
    expect(LIVENESS_CHECK_MS).toBeLessThan(LIVENESS_TIMEOUT_MS);
    expect(LIVENESS_TIMEOUT_MS % LIVENESS_CHECK_MS).toBe(0);
  });
});

describe('detectSeqGap（event_seq 断口判定）', () => {
  it('首帧不判（replay 首帧携当前高水位，无历史可比）', () => {
    expect(detectSeqGap(null, 57)).toBe(false);
    expect(detectSeqGap(null, 1)).toBe(false);
  });

  it('连续 +1 不跳闸（正常活流）', () => {
    expect(detectSeqGap(57, 58)).toBe(false);
  });

  it('跳号跳闸（中间帧丢失 → 重连 replay 幂等补齐）', () => {
    expect(detectSeqGap(57, 59)).toBe(true);
    expect(detectSeqGap(57, 120)).toBe(true);
  });

  it('重复投递不跳闸（replay 与 live 重叠，幂等丢弃）', () => {
    expect(detectSeqGap(58, 58)).toBe(false);
  });

  it('回退帧不跳闸（迟到旧帧不误判为断口，防无限重连）', () => {
    expect(detectSeqGap(58, 3)).toBe(false);
  });
});

describe('parseSseStream onChunk（字节级活感钩子）', () => {
  it('注释心跳块也回调 onChunk：零事件也算活（判活靠字节不靠事件）', async () => {
    const events: SseEvent[] = [];
    const onChunk = vi.fn();
    await parseSseStream(
      rawResponse([': heartbeat\n\n', ': heartbeat\n\n']),
      (ev) => events.push(ev), () => {}, onChunk,
    );
    expect(events).toHaveLength(0);
    expect(onChunk).toHaveBeenCalledTimes(2);
  });

  it('每个字节块回调一次（帧跨块拆分按块计，不按帧计）', async () => {
    const events: SseEvent[] = [];
    const onChunk = vi.fn();
    await parseSseStream(
      rawResponse([
        'data: {"type":"del',
        'ta","text":"你好"}\n\n',
        'data: {"type":"delta","text":"世界"}\n\n',
      ]),
      (ev) => events.push(ev), () => {}, onChunk,
    );
    expect(onChunk).toHaveBeenCalledTimes(3);
    expect(events.map((e) => e.type)).toEqual(['delta', 'delta']);
    expect((events[0] as { text?: string }).text).toBe('你好');
  });

  it('异常帧：onParseError 计数、onChunk 照常回调（活感不被解析失败遮蔽）', async () => {
    const onParseError = vi.fn();
    const onChunk = vi.fn();
    await parseSseStream(
      rawResponse(['data: {坏帧\n\n', ': heartbeat\n\n']),
      () => {}, onParseError, onChunk,
    );
    expect(onParseError).toHaveBeenCalledTimes(1);
    expect(onChunk).toHaveBeenCalledTimes(2);
  });

  it('不传 onChunk 向后兼容（既有三参调用不受影响）', async () => {
    const events: SseEvent[] = [];
    await parseSseStream(
      rawResponse(['data: {"type":"delta","text":"a"}\n\n']),
      (ev) => events.push(ev), () => {},
    );
    expect(events).toHaveLength(1);
  });
});
