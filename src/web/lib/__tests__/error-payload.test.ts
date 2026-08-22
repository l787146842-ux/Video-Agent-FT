/**
 * ErrorPayload 契约测试（任务 #19：错误语义结构化，替代正则猜文案）。
 *
 * 锚点 = src/video_agent/web/error_payload.py（后端归类单一事实源）。
 * kind 集合、legacy error_code 桥接、HTTP/SSE 解析与 ERROR_ACTION_MAP
 * 各分支在此机械钉死；后端改归类语义时前端同批改这里，漂移即红。
 */
import { describe, it, expect, expectTypeOf } from 'vitest';
import {
  ERROR_KINDS, ERROR_ACTION_MAP, normalizeKind, actionForKind,
  legacyCodePayload, kindFromHttpStatus, makeErrorPayload,
  httpErrorPayload, sseErrorPayload,
  type ErrorPayload,
} from '../error-payload';

describe('ErrorPayload kind 集合契约（后端 ALL_KINDS 镜像）', () => {
  it('kind 封闭集合与后端一致（增删需双侧同批）', () => {
    expect([...ERROR_KINDS]).toEqual(['auth', 'quota', 'network', 'upstream', 'content', 'unknown']);
  });

  it('normalizeKind 未知值收窄为 unknown（防类型退化）', () => {
    expect(normalizeKind('auth')).toBe('auth');
    expect(normalizeKind('bogus')).toBe('unknown');
    expect(normalizeKind(undefined)).toBe('unknown');
    expect(normalizeKind(42)).toBe('unknown');
  });

  it('ErrorPayload 形态契约（code/kind/message 必填，raw 可空）', () => {
    expectTypeOf<ErrorPayload['code']>().toBeString();
    expectTypeOf<ErrorPayload['message']>().toBeString();
    expectTypeOf<ErrorPayload['raw']>().toEqualTypeOf<string | undefined>();
  });
});

describe('ERROR_ACTION_MAP 各分支（chat 气泡 affordance 单一事实源）', () => {
  it('auth →「检查 API 配置」按钮', () => {
    expect(ERROR_ACTION_MAP.auth.settingsHint).toBe(true);
    expect(actionForKind('auth').settingsHint).toBe(true);
  });

  it('quota → 提示额度（不挂设置按钮）', () => {
    expect(ERROR_ACTION_MAP.quota.quotaHint).toBe(true);
    expect(ERROR_ACTION_MAP.quota.settingsHint).toBeUndefined();
  });

  it('network → 提示网络/重试（不挂设置按钮）', () => {
    expect(ERROR_ACTION_MAP.network.retryHint).toBe(true);
    expect(ERROR_ACTION_MAP.network.settingsHint).toBeUndefined();
  });

  it('upstream → 可重试（与 network 同 affordance）', () => {
    expect(ERROR_ACTION_MAP.upstream.retryHint).toBe(true);
  });

  it('content / unknown → 无附加动作', () => {
    expect(ERROR_ACTION_MAP.content).toEqual({});
    expect(ERROR_ACTION_MAP.unknown).toEqual({});
    expect(actionForKind('nope').settingsHint).toBeUndefined();
  });

  it('每个 kind 都在映射表有登记（新增 kind 忘登记即红）', () => {
    for (const kind of ERROR_KINDS) {
      expect(ERROR_ACTION_MAP[kind]).toBeDefined();
    }
  });
});

describe('HTTP 状态归类', () => {
  it('401/403→auth、429→quota、5xx→upstream、其余→unknown', () => {
    expect(kindFromHttpStatus(401)).toBe('auth');
    expect(kindFromHttpStatus(403)).toBe('auth');
    expect(kindFromHttpStatus(429)).toBe('quota');
    expect(kindFromHttpStatus(500)).toBe('upstream');
    expect(kindFromHttpStatus(529)).toBe('upstream');
    expect(kindFromHttpStatus(400)).toBe('unknown');
  });
});

describe('httpErrorPayload（api/client.ts 的 HTTP 失败解析）', () => {
  it('后端新契约字段直接采信（code/kind/message/raw）', () => {
    const p = httpErrorPayload(401, {
      detail: 'Unauthorized', message: 'Unauthorized',
      code: 'err.auth.invalid_key', kind: 'auth', error_code: 'UNAUTHORIZED',
    }, 'Unauthorized');
    expect(p.code).toBe('err.auth.invalid_key');
    expect(p.kind).toBe('auth');
    expect(p.message).toBe('Unauthorized');
  });

  it('kind 非法值收窄 unknown（code 仍采信）', () => {
    const p = httpErrorPayload(500, { code: 'err.x.y', kind: 'evil' }, '');
    expect(p.kind).toBe('unknown');
    expect(p.code).toBe('err.x.y');
  });

  it('旧后端 legacy error_code 桥接（UNAUTHORIZED→auth、RATE_LIMITED→quota）', () => {
    expect(httpErrorPayload(401, { detail: 'x', error_code: 'UNAUTHORIZED' }, '').kind).toBe('auth');
    expect(httpErrorPayload(429, { detail: 'x', error_code: 'RATE_LIMITED' }, '').kind).toBe('quota');
    expect(httpErrorPayload(504, { detail: 'x', error_code: 'TIMEOUT' }, '').kind).toBe('network');
    expect(httpErrorPayload(502, { detail: 'x', error_code: 'ADAPTER_ERROR' }, '').kind).toBe('upstream');
  });

  it('无结构化信息时按状态码兜底归类，raw 透传', () => {
    const p = httpErrorPayload(403, { detail: '拒绝' }, 'fallback');
    expect(p.kind).toBe('auth');
    expect(p.message).toBe('拒绝');
    const noBody = httpErrorPayload(502, null, 'Bad Gateway');
    expect(noBody.kind).toBe('upstream');
    expect(noBody.message).toBe('Bad Gateway');
    const raw = httpErrorPayload(500, { detail: 'd', raw: 'upstream-json' }, '');
    expect(raw.raw).toBe('upstream-json');
  });
});

describe('sseErrorPayload（use-sse 错误事件解析）', () => {
  it('新契约事件：code/kind 优先于 legacy error_code', () => {
    const p = sseErrorPayload({
      detail: '鉴权失败（HTTP 401）', error_code: 'INTERNAL_ERROR',
      code: 'err.auth.invalid_key', kind: 'auth', raw: 'raw-body',
    });
    expect(p.kind).toBe('auth');
    expect(p.code).toBe('err.auth.invalid_key');
    expect(p.message).toBe('鉴权失败（HTTP 401）');
    expect(p.raw).toBe('raw-body');
  });

  it('旧事件（仅 error_code）：桥接归类且 message 走 detail/text', () => {
    const p = sseErrorPayload({ detail: 'too many', error_code: 'RATE_LIMITED' });
    expect(p.kind).toBe('quota');
    expect(p.code).toBe('err.quota.rate_limited');
    expect(sseErrorPayload({ text: 't', error_code: 'NETWORK_ERROR' }).kind).toBe('network');
  });

  it('无任何码：归 unknown，message 兜底「服务端错误」', () => {
    const p = sseErrorPayload({});
    expect(p.kind).toBe('unknown');
    expect(p.code).toBe('err.unknown');
    expect(p.message).toBe('服务端错误');
  });
});

describe('legacyCodePayload / makeErrorPayload', () => {
  it('legacy 码未登记归 unknown 且 code 附 slug 可读', () => {
    const p = legacyCodePayload('DUPLICATE_REQUEST', '请勿重复发送');
    expect(p.kind).toBe('unknown');
    expect(p.code).toBe('err.unknown.duplicate_request');
  });

  it('makeErrorPayload 缺省 code = err.<kind>', () => {
    expect(makeErrorPayload('断连', 'network').code).toBe('err.network');
    expect(makeErrorPayload('x').kind).toBe('unknown');
  });
});
