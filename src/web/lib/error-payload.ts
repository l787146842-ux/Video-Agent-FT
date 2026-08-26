/**
 * ErrorPayload — 统一错误语义契约。
 *
 * 单一事实源：后端 src/video_agent/web/error_payload.py 经 sidecar
 * （src/web/types/sse.schema.json）生成到 api.generated.ts；本文件只消费
 * 生成物并做前端收窄（kind 收窄为封闭字面量集合），不再人工镜像。
 * 后端 HTTP 错误响应与 SSE error 事件共用同一结构。
 *
 * 此前 chat store 对错误文案做 /401|403|token|鉴权/ 正则猜测决定是否挂
 * 「检查 API 配置」按钮——两套机制并存（SSE 走 error_code，HTTP 走猜文案）。
 * 本模块是前端唯一归口：api/client.ts 的 HTTP 失败与 hooks/use-sse.ts 的
 * 错误事件都解析为 ErrorPayload，chat store 按 ERROR_ACTION_MAP 做动作。
 */
import {
  SSE_ERROR_KINDS,
  SSE_LEGACY_ERROR_CODES,
  type ErrorPayloadContract,
  type SseErrorKind,
} from '@/types/api.generated';

/** kind 归类（封闭集合，后端 ALL_KINDS 生成，改动自动同步） */
export const ERROR_KINDS = SSE_ERROR_KINDS;
export type ErrorKind = SseErrorKind;

/** 统一错误负载（HTTP 失败响应体与 SSE error 事件解析后的同一形态；
 * 生成物 ErrorPayloadContract 收窄 kind 为封闭字面量） */
export type ErrorPayload = Omit<ErrorPayloadContract, 'kind'> & { kind: ErrorKind };

/** kind → 交互动作描述（错误气泡 affordance 单一事实源；集中一处可扩展） */
export interface ErrorAction {
  /** 附「检查 API 配置」跳转按钮 */
  settingsHint?: boolean;
  /** 提示额度（文案随后端人话下发；渲染扩展位） */
  quotaHint?: boolean;
  /** 提示网络/重试（network/upstream 瞬态故障，「继续刚才的任务」机械重发承接） */
  retryHint?: boolean;
}

export const ERROR_ACTION_MAP: Record<ErrorKind, ErrorAction> = {
  auth: { settingsHint: true },
  quota: { quotaHint: true },
  network: { retryHint: true },
  upstream: { retryHint: true },
  content: {},
  unknown: {},
};

/** 收窄 kind（未知值归 unknown，防类型退化） */
export function normalizeKind(kind: unknown): ErrorKind {
  return (ERROR_KINDS as readonly string[]).includes(kind as string)
    ? (kind as ErrorKind)
    : 'unknown';
}

export function actionForKind(kind: ErrorKind | string | null | undefined): ErrorAction {
  return ERROR_ACTION_MAP[normalizeKind(kind)] || ERROR_ACTION_MAP.unknown;
}

/** code 级覆盖：个别 code 的 affordance 比其所属 kind 更明确（集中一处可扩展）。
 * 未配置供应商归 unknown，但应附「检查 API 配置」跳转按钮。 */
const CODE_ACTION_OVERRIDES: Record<string, ErrorAction> = {
  'err.unknown.provider_not_configured': { settingsHint: true },
};

/** 按完整负载解析动作（code 覆盖优先于 kind 映射） */
export function actionForPayload(payload: Pick<ErrorPayload, 'code' | 'kind'>): ErrorAction {
  return CODE_ACTION_OVERRIDES[payload.code] || actionForKind(payload.kind);
}

/** 既有（legacy）error_code → kind/code 桥接（后端 LEGACY_CODE_MAP 生成；
 * 后端未携带 code/kind 的旧响应/旧记录兜底归类） */
const LEGACY_CODE_MAP: Record<string, { kind: ErrorKind; code: string }> = SSE_LEGACY_ERROR_CODES;

export function legacyCodePayload(legacyCode: string | null | undefined, message: string, raw?: string): ErrorPayload {
  const hit = LEGACY_CODE_MAP[(legacyCode || '').trim()];
  if (hit) return { code: hit.code, kind: hit.kind, message, raw: raw || undefined };
  const slug = (legacyCode || '').trim().toLowerCase() || 'internal';
  return { code: `err.unknown.${slug}`, kind: 'unknown', message, raw: raw || undefined };
}

/** 仅凭 HTTP 状态归类（本地 fetch 失败之外的服务端状态码） */
export function kindFromHttpStatus(status: number): ErrorKind {
  if (status === 401 || status === 403) return 'auth';
  if (status === 429) return 'quota';
  if (status >= 500) return 'upstream';
  return 'unknown';
}

/** 兜底构造（无结构化信息的本地失败：订阅断连、fetch 抛错等） */
export function makeErrorPayload(
  message: string,
  kind: ErrorKind = 'unknown',
  code = `err.${kind}`,
  raw?: string,
): ErrorPayload {
  return { code, kind, message, raw: raw || undefined };
}

/** HTTP 失败响应体 → ErrorPayload（api/client.ts 的 ApiError 携带） */
export function httpErrorPayload(
  status: number,
  body: Record<string, unknown> | null,
  fallbackText: string,
): ErrorPayload {
  const detail = typeof body?.detail === 'string' ? body.detail : '';
  const message = typeof body?.message === 'string' ? body.message : '';
  const text = detail || message || fallbackText;
  const raw = typeof body?.raw === 'string' ? body.raw : undefined;
  // 后端已带结构化字段：直接采信
  if (typeof body?.code === 'string' && body.code) {
    return { code: body.code, kind: normalizeKind(body.kind), message: text, raw };
  }
  // 旧后端/第三方响应：legacy error_code 桥接，再退状态码归类
  const legacy = typeof body?.error_code === 'string' ? body.error_code : '';
  if (legacy) {
    const p = legacyCodePayload(legacy, text, raw);
    // legacy 码未登记但状态码有明确语义时，以状态码归类为准
    if (p.kind === 'unknown') return makeErrorPayload(text, kindFromHttpStatus(status), `err.${kindFromHttpStatus(status)}`, raw);
    return p;
  }
  return makeErrorPayload(text, kindFromHttpStatus(status), `err.${kindFromHttpStatus(status)}`, raw);
}

/** SSE error 事件 → ErrorPayload（hooks/use-sse.ts 消费） */
export function sseErrorPayload(ev: {
  detail?: string; text?: string; error_code?: string; raw?: string;
  code?: string; kind?: string;
}): ErrorPayload {
  const message = ev.detail || ev.text || '服务端错误';
  // 新契约字段优先
  if (ev.code) {
    return { code: ev.code, kind: normalizeKind(ev.kind), message, raw: ev.raw || undefined };
  }
  // 旧事件（仅 error_code）：桥接归类
  if (ev.error_code) return legacyCodePayload(ev.error_code, message, ev.raw);
  return makeErrorPayload(message, 'unknown', 'err.unknown', ev.raw);
}
