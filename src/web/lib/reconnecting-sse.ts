/**
 * 带指数退避重连的 EventSource 封装
 * 用于工作流进度等需要持久订阅的 SSE 场景。
 */

export interface ReconnectingSSEOptions {
  /** 初始重连延迟（ms），默认 1000 */
  initialDelay?: number;
  /** 最大重连延迟（ms），默认 30000 */
  maxDelay?: number;
  /** 退避倍数，默认 2 */
  backoffFactor?: number;
}

export interface ReconnectingSSE {
  /** 彻底关闭（不再重连） */
  close: () => void;
}

/**
 * 创建带自动重连的 EventSource。
 * 返回 { close } 句柄，组件 onCleanup 时调用。
 */
export function createReconnectingSSE(
  url: string,
  onMessage: (data: string) => void,
  options: ReconnectingSSEOptions = {},
): ReconnectingSSE {
  const {
    initialDelay = 1000,
    maxDelay = 30000,
    backoffFactor = 2,
  } = options;

  let es: EventSource | null = null;
  let closed = false;
  let delay = initialDelay;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

  function connect() {
    if (closed) return;
    es = new EventSource(url);

    es.onopen = () => {
      // 连接成功，重置退避
      delay = initialDelay;
    };

    es.onmessage = (e) => {
      onMessage(e.data);
    };

    es.onerror = () => {
      es?.close();
      es = null;
      if (closed) return;
      // 指数退避重连
      reconnectTimer = setTimeout(() => {
        delay = Math.min(delay * backoffFactor, maxDelay);
        connect();
      }, delay);
    };
  }

  connect();

  return {
    close() {
      closed = true;
      if (reconnectTimer !== undefined) {
        clearTimeout(reconnectTimer);
        reconnectTimer = undefined;
      }
      es?.close();
      es = null;
    },
  };
}
