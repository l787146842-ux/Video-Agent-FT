/**
 * SSE 连接状态机（自 hooks/use-sse.ts 抽出的纯逻辑层）：归属判定/指数
 * 退避重连调度/终态清理顺序/轮间注入判定均为纯函数；连接生命周期经
 * createSseConnection 工厂组装，所有 I/O（HTTP/定时）与响应式副作用由 deps 注入。
 * 订阅模型：POST 取 task_id → 订阅事件流（先 replay 快照再增量）；
 * 刷新/切项目只断订阅，后台任务继续；切回时 resume 重连；停止才取消。
 */
import type { SseEvent, AgentChatRequest } from '@/types';
import type { AgentTaskInfo } from '@/api/sse';
import { ApiError } from '@/api/client';
import { makeErrorPayload, kindFromHttpStatus, type ErrorPayload } from '@/lib/error-payload';
import { t } from '@/lib/locale';
import { parseSseStream, routeSseEvent, type SseEventCtx, type SseEventFx } from '@/lib/sse-events';
/** SSE 自动重连：网络抖动不得落错误气泡/清忙态；指数退避重订阅（服务端先 replay
 * 快照再增量，restoreStreamingState 整体替换累积文本，天然幂等）；重试耗尽才落错误 */
export const MAX_RECONNECT_ATTEMPTS = 3;
export const RECONNECT_BASE_DELAY_MS = 500;
/** 事件订阅 HTTP 失败：携带 status 供重连策略判定（4xx 任务面错误不重连） */
export class SseHttpError extends Error {
  constructor(public readonly status: number) {
    super(`事件订阅失败 (${status})`);
    this.name = 'SseHttpError';
  }
}
/** 订阅失败判定：true = 网络/传输层瞬断值得重连（后台任务仍在跑）；
 * false = 用户取消或任务面错误（4xx：任务不存在/已结束被清理），重连无意义 */
export function isRetriableSubscribeError(err: unknown): boolean {
  if ((err as Error).name === 'AbortError') return false;
  if (err instanceof SseHttpError) {
    // 408/429 属瞬态可重连；其余 4xx = 任务面错误
    return err.status === 408 || err.status === 429 || err.status >= 500;
  }
  return true; // fetch 网络错误 / 读流中断
}
/** 指数退避调度：第 attempt（1 起）次重试等待 base * 2^(attempt-1) ms */
export function reconnectDelayMs(attempt: number, base: number = RECONNECT_BASE_DELAY_MS): number {
  return base * 2 ** (attempt - 1);
}
export interface TaskRef { taskId: string; projectId: string; recovering: boolean }
/** 归属判定：连接是否仍属于该任务（false = 停止/切换/断开已改归属，
 * 不得再处理该任务的失败与清理） */
export function ownsTask(current: { taskId: string } | null | undefined, taskId: string): boolean {
  return current?.taskId === taskId;
}
/** 排队/不打断的轮间注入判定：仅有运行中任务且文本非空才登记 guidance */
export function shouldQueueGuidance(task: TaskRef | null, text: string): boolean {
  return task !== null && text.trim().length > 0;
}
/** 终态清理顺序（历史坑，测试钉死调用顺序）：先复位忙态、置空归属，再关订阅。
 * 顺序搞反时 abort 使帧解析 reject（AbortError），catch 归属判定仍有效会把
 * 主动断开误判为失败 → 落假错误气泡（「BodyStreamBuffer was aborted」+ 继续建议） */
export function finalizeTerminal(eff: {
  resetBusy(): void;
  clearOwnership(): void;
  closeSubscription(): void;
}): void {
  eff.resetBusy();
  eff.clearOwnership();
  eff.closeSubscription();
}
export interface InflightEntry { task_id?: string; media_type?: string; model?: string; summary?: string }
/** 外部 I/O 注入面：HTTP 传输 + 定时（本模块不直接触网/起定时器） */
export interface SseTransport {
  startTask(req: AgentChatRequest): Promise<{ task_id: string; project_id: string }>;
  fetchEvents(taskId: string, signal: AbortSignal): Promise<Response>;
  stopTask(taskId: string): Promise<{ inflight?: InflightEntry[] } | null>;
  listTasks(projectId: string): Promise<AgentTaskInfo[]>;
  postGuidance(taskId: string, id: string, text: string): Promise<unknown>;
  delay(ms: number): Promise<void>;
}

export interface SseConnectionDeps {
  transport: SseTransport;
  fx: SseEventFx;
  isStreaming(): boolean;
  currentProjectId(): string;
}

export function createSseConnection(deps: SseConnectionDeps) {
  const { transport, fx } = deps;
  let abortController: AbortController | null = null;
  let currentTask: TaskRef | null = null;
  /** 每个项目仍在后台运行的任务（切走后记住，切回时恢复订阅） */
  const projectTasks = new Map<string, string>();
  /** resume 双触发互斥（LayoutShell onMount 与 project effect 竞态窗口） */
  let resumeInFlight = false;
  /** 帧解析失败计数（不静默：调试可见，异常帧不中断流） */
  let sseParseErrors = 0;
  /** 关闭当前订阅（不取消后台任务） */
  function closeSubscription(): void {
    abortController?.abort();
    abortController = null;
  }
  const ctx: SseEventCtx = {
    fx,
    isRecovering: () => Boolean(currentTask?.recovering),
    hasOwnership: () => currentTask !== null,
    finalize: (projectKey?: string) => finalizeTerminal({
      resetBusy: () => { fx.setStreaming(false); fx.setAgentBusy(false); },
      clearOwnership: () => {
        const key = projectKey ?? currentTask?.projectId;
        if (key) projectTasks.delete(key);
        currentTask = null;
      },
      closeSubscription,
    }),
  };
  async function subscribeOnce(taskId: string): Promise<void> {
    abortController = new AbortController();
    const res = await transport.fetchEvents(taskId, abortController.signal);
    if (!res.ok || !res.body) throw new SseHttpError(res.status);
    await parseSseStream(res, (ev: SseEvent) => routeSseEvent(ev, ctx), () => {
      sseParseErrors += 1;
      console.warn(`[use-sse] SSE 帧解析失败（累计 ${sseParseErrors} 次）`);
    });
  }
  async function connectToTask(taskId: string, projectId: string, recovering: boolean): Promise<void> {
    fx.setStreaming(true);
    fx.setAgentBusy(true);
    currentTask = { taskId, projectId, recovering };
    let attempt = 0;
    while (true) {
      try {
        await subscribeOnce(taskId);
        break; // 流正常结束（done/error 等终态已在事件路由内收尾）
      } catch (err) {
        // 任务归属已变（停止/切换/断开）：不再处理本任务的失败
        if (!ownsTask(currentTask, taskId)) return;
        if (!isRetriableSubscribeError(err) || attempt >= MAX_RECONNECT_ATTEMPTS) {
          const msg = (err as Error).message || '未知错误';
          // 订阅失败结构化归类（HTTP 状态按码归类；fetch/读流中断 = network）
          const payload = err instanceof SseHttpError
            ? makeErrorPayload(msg, kindFromHttpStatus(err.status))
            : makeErrorPayload(msg, 'network', 'err.network.connection');
          fx.setErrorText(payload.message);
          fx.chat.streamError(payload);
          break;
        }
        // 指数退避重订阅：忙态保持 true（后台任务未停），replay 快照幂等恢复
        attempt += 1;
        fx.chat.setStatus(t('rp.streaming.reconnecting', { attempt, max: MAX_RECONNECT_ATTEMPTS }));
        await transport.delay(reconnectDelayMs(attempt));
        if (!ownsTask(currentTask, taskId)) return; // 等待期间归属变化
      }
    }
    // 仅当仍订阅本任务时清理（终态/disconnect 已在关订阅前置空归属，AbortError 由归属判定跳过）
    if (ownsTask(currentTask, taskId)) {
      fx.setStreaming(false);
      fx.setAgentBusy(false);
      currentTask = null;
      abortController = null;
      if (projectTasks.get(projectId) === taskId) projectTasks.delete(projectId);
    }
  }
  /** 发起 Agent 聊天：后台建任务 + 订阅事件流 */
  async function streamAgentChat(request: AgentChatRequest): Promise<void> {
    if (deps.isStreaming()) return;
    const projectId = deps.currentProjectId();
    fx.setErrorText(null);
    fx.setAgentBusy(true);
    fx.chat.startStream(request.model || '');
    try {
      const started = await transport.startTask(request);
      projectTasks.set(started.project_id || projectId, started.task_id);
      await connectToTask(started.task_id, started.project_id || projectId, false);
    } catch (err) {
      // 建任务失败——ApiError 携带后端结构化负载；非 ApiError（fetch 网络层）归 network
      const payload: ErrorPayload = err instanceof ApiError ? err.payload
        : makeErrorPayload((err as Error).message || '未知错误', 'network', 'err.network.connection');
      fx.setErrorText(payload.message);
      fx.chat.streamError(payload);
      fx.setAgentBusy(false);
    }
  }
  /** 接管外部已启动的 agent 任务（截断重答专用：后端已建任务，响应体含实际模型）：
   * 进忙态 + startStream(model) 补流式徽标后走同一订阅/重连/收尾路径 */
  async function attachStartedTask(started: { task_id: string; project_id: string; model?: string }): Promise<void> {
    if (deps.isStreaming()) return;
    const projectId = started.project_id || deps.currentProjectId();
    fx.setErrorText(null);
    fx.setAgentBusy(true);
    fx.chat.startStream(started.model || '');
    projectTasks.set(projectId, started.task_id);
    await connectToTask(started.task_id, projectId, false);
  }
  /** 断开订阅但保留后台任务（切项目/离开页面时调用） */
  function disconnect(): void {
    if (currentTask) {
      projectTasks.set(currentTask.projectId, currentTask.taskId);
      currentTask = null;
    }
    closeSubscription();
    fx.setStreaming(false);
    fx.setAgentBusy(false);
  }
  /** 排队消息登记到运行中任务（轮间注入）；任务不存在/已结束静默回落
   * 前端「任务结束后自动出队重发」路径，不丢失用户消息 */
  function sendGuidance(id: string, text: string): void {
    if (!shouldQueueGuidance(currentTask, text)) return;
    void transport.postGuidance(currentTask!.taskId, id, text).catch(() => { /* 回落自动出队 */ });
  }
  /** 真正停止后台任务（停止按钮）。等 /stop 响应拿在途外部生成任务登记
   *（inflight）后一并交 cancelStream 措辞；短超时不阻塞 UI（任务可能已结束） */
  async function stop(): Promise<void> {
    const task = currentTask;
    let inflight: InflightEntry[] | undefined;
    if (task) {
      try {
        // 与 1500ms 超时竞速：后端慢/已结束时不卡停止反馈，仅缺 inflight 登记
        const resp = await Promise.race([
          transport.stopTask(task.taskId),
          transport.delay(1500).then(() => null),
        ]);
        inflight = resp?.inflight;
      } catch { /* 任务可能已结束 */ }
      projectTasks.delete(task.projectId);
    }
    closeSubscription();
    fx.chat.cancelStream({ inflight });
    fx.setStreaming(false);
    fx.setAgentBusy(false);
    currentTask = null;
  }
  /** 刷新/切回项目后恢复进行中的后台任务（互斥：双触发只进一次） */
  async function resume(projectId: string): Promise<void> {
    if (!projectId || deps.isStreaming() || resumeInFlight) return;
    resumeInFlight = true;
    try {
      let tasks: AgentTaskInfo[] = [];
      try {
        tasks = await transport.listTasks(projectId);
      } catch { /* 后端未就绪时静默 */ }
      if (!tasks.length) return;
      // await 之后再判一次：窗口内另一触发可能已建立订阅
      if (deps.isStreaming()) return;
      const task = tasks[0]; // 最新任务
      projectTasks.set(projectId, task.task_id);
      fx.chat.restoreStreamingState({
        reasoning: '', text: '', statusText: t('rp.streaming.restoring'), tools: [],
      });
      await connectToTask(task.task_id, projectId, true);
    } finally {
      resumeInFlight = false;
    }
  }
  return {
    streamAgentChat, attachStartedTask, disconnect, stop, resume, sendGuidance,
    getParseErrorCount: () => sseParseErrors,
  };
}
