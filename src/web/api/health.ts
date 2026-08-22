/**
 * 后端健康探测（全局健康层）：复用 app.py 既有 GET /health
 *（根路径免 API Key，含画布只读缓存探测），不新增后端端点。
 */

export interface BackendHealth {
  /** 后端进程可达且自报 ok */
  ok: boolean;
  /** 画布在线状态（后端读缓存探测；未启用/未知为 null） */
  canvas: boolean | null;
}

/** 探测超时（ms）：心跳间隔的 1/6，卡住的探测不得拖慢状态翻转 */
const PROBE_TIMEOUT_MS = 5000;

export async function fetchBackendHealth(timeoutMs = PROBE_TIMEOUT_MS): Promise<BackendHealth> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch('/health', { signal: ctl.signal, cache: 'no-store' });
    if (!res.ok) return { ok: false, canvas: null };
    const body = (await res.json()) as { status?: string; canvas_online?: boolean | null };
    return {
      ok: body.status === 'ok',
      canvas: typeof body.canvas_online === 'boolean' ? body.canvas_online : null,
    };
  } catch {
    // 网络层失败/超时/非 JSON：一律视为后端不可达（健康层只做断连横幅，不弹错误）
    return { ok: false, canvas: null };
  } finally {
    clearTimeout(timer);
  }
}
