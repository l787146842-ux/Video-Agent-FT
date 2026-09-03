/**
 * 带指数退避重连的 SSE 订阅封装（fetch + ReadableStream 传输）。
 *
 * 任务7/P0：项目内 SSE 唯一传输机制——原生 EventSource 结构性无法携带
 * 自定义头，生产模式 api_key_auth 对 /api/ 强制 X-API-Key 必 401；
 * 本封装经 client.buildAuthHeaders 注入鉴权头后走 fetch 读流，
 * 断连（HTTP 失败/流结束/网络中断）按指数退避自动重连。
 */
import { buildAuthHeaders } from '@/api/client';

export interface ReconnectingSSEOptions {
  /** 初始重连延迟（ms），默认 1000 */
  initialDelay?: number;
  /** 最大重连延迟（ms），默认 15000；内部硬 cap 15s，传更大值也按 15s 封顶 */
  maxDelay?: number;
  /** 退避倍数，默认 2 */
  backoffFactor?: number;
}

/** 退避上限硬 cap（审查修复）：长期订阅不得无限拉长重连间隔，≤15s */
const MAX_DELAY_CAP_MS = 15000;

export interface ReconnectingSSE {
  /** 彻底关闭（不再重连） */
  close: () => void;
}

/** SSE 帧流解析（纯函数）：data: 帧 → onData(payload)；注释帧（心跳）
 * 与非 data 行忽略；JSON 解析交给调用方（总线侧按自身契约 parse）。
 * 返回流内是否收到过至少一个 data 帧（退避重置收紧的判定依据）。 */
export async function pumpSseBody(
  body: ReadableStream<Uint8Array>,
  onData: (data: string) => void,
  signal?: AbortSignal,
): Promise<boolean> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let gotData = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 2);
        if (!raw.startsWith('data:')) continue;
        gotData = true;
        onData(raw.slice(5).trim());
      }
    }
  } catch {
    // 读流抛错（含主动 abort）不穿透：携带已收帧事实返回，
    // 退避重置判定（gotData）不因异常路径丢失；signal.aborted 短路留在 connect 侧
  } finally {
    // 先 cancel 后 releaseLock（锁在时才能安全取消底层流）
    if (signal && !signal.aborted) {
      try { await reader.cancel(); } catch { /* 流已尽 */ }
    }
    reader.releaseLock();
  }
  return gotData;
}

/**
 * 创建带自动重连的 SSE 订阅（fetch 传输 + 鉴权头）。
 * 返回 { close } 句柄，组件 onCleanup 时调用。
 */
export function createReconnectingSSE(
  url: string,
  onMessage: (data: string) => void,
  options: ReconnectingSSEOptions = {},
): ReconnectingSSE {
  const {
    initialDelay = 1000,
    maxDelay: maxDelayOpt = MAX_DELAY_CAP_MS,
    backoffFactor = 2,
  } = options;
  const maxDelay = Math.min(maxDelayOpt, MAX_DELAY_CAP_MS);

  let closed = false;
  let delay = initialDelay;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | null = null;

  async function connect(): Promise<void> {
    if (closed) return;
    controller = new AbortController();
    const { signal } = controller;
    try {
      // SSE 传输层：结构性无法走 api/ 的 JSON helper（需 ReadableStream 读流），
      // 鉴权头经 buildAuthHeaders 唯一出口注入——铁律 10.1 的合法传输例外。
      // eslint-disable-next-line no-restricted-syntax
      const res = await fetch(url, { headers: buildAuthHeaders(), signal });
      if (!res.ok || !res.body) throw new Error(`SSE 连接失败 (HTTP ${res.status})`);
      // 退避重置收紧：流内收到至少一个数据帧才重置（连接成功后立即被关流不重置）
      const gotData = await pumpSseBody(res.body, onMessage, signal);
      if (gotData) delay = initialDelay;
      if (closed || signal.aborted) return;
      // 服务端正常关流（心跳超时/重启）：与网络中断同样走重连
      scheduleReconnect();
    } catch {
      if (closed || signal.aborted) return;
      scheduleReconnect();
    }
  }

  function scheduleReconnect(): void {
    if (closed || reconnectTimer !== undefined) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = undefined;
      delay = Math.min(delay * backoffFactor, maxDelay);
      void connect();
    }, delay);
  }

  void connect();

  return {
    close() {
      closed = true;
      if (reconnectTimer !== undefined) {
        clearTimeout(reconnectTimer);
        reconnectTimer = undefined;
      }
      controller?.abort();
      controller = null;
    },
  };
}
