import { createSignal, createEffect, For, Show, onMount, onCleanup } from 'solid-js';
import { FiArrowLeft } from 'solid-icons/fi';
import { getSubagentThreads, getSubagentRecord } from '@/api/conversations';
import { formatElapsed } from '@/lib/timeline';
import { clearPendingSubagentRecord, pendingSubagentRecord } from '@/stores/chat/subagent-actors';
import type { SubagentThread, SubagentRecordMessage } from '@/types';
import { MarkdownBubble } from '../right-panel/MarkdownBubble';

/** 子任务视图打开期间的轮询间隔：子级在父本轮内联同步跑完，
 *  父阻塞期间无独立 SSE 帧可推，故靠轻量轮询把 running→completed 过渡显形。
 *  2026-09-22 批4（Q4.1）：4000ms → 1500ms。子代理思考此前「做完几步才刷新
 *  完整」，一半原因在这里：后端 5s 才落一条增量、前端又 4s 才问一次，两级
 *  延迟叠加。后端已按步内增量实时落流（见 session_log.project_readable_record），
 *  前端降低轮询粒度后即可呈现近似流式的观感（dsh 走真事件流，本层受现有
 *  轮询架构约束，取「够用且不压服务器」的折中）。 */
const POLL_MS = 1500;

function statusClass(s: string): string {
  return s === 'running' ? 'running' : s === 'completed' ? 'completed'
    : (s === 'failed' || s === 'incomplete') ? 'failed' : 'unknown';
}
/** 2026-09-26 11111 取证批（R4）：新增「未完工」态（未按契约打卡即收尾），
 *  与「已中断」区分——线程没崩，是活没干完（后端 thread_status 客观判定）。 */
function statusText(s: string): string {
  return s === 'running' ? '执行中' : s === 'completed' ? '已完成'
    : s === 'incomplete' ? '未完工'
      : s === 'failed' ? '已中断' : '未知';
}
/** epoch ms → HH:MM（记录条目时间戳；无值返回空串不显示） */
function formatHHMM(ts?: number): string {
  if (!ts) return '';
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** 条目内容等价判定（轮询增量更新用；不比较对象引用）。
 *  2026-09-22 批4（Q4.1）：必须比较 elapsed_ms/streaming——在途步的正文会随
 *  轮询增长，若漏比这两个字段，稳定化会把新对象误判为「未变」而复用旧引用，
 *  Solid 便不重渲染，实时增量永远长不出来（本批要修的正是这个观感）。 */
export function sameRecordMsg(a: SubagentRecordMessage, b: SubagentRecordMessage): boolean {
  return a.sender === b.sender
    && a.text === b.text
    && a.ts === b.ts
    && a.reasoning_content === b.reasoning_content
    && a.elapsed_ms === b.elapsed_ms
    && !!a.streaming === !!b.streaming
    && (a.actionLog || []).join('\u0001') === (b.actionLog || []).join('\u0001');
}

function sameThread(a: SubagentThread, b: SubagentThread): boolean {
  return a.conversation_id === b.conversation_id
    && a.status === b.status
    && a.steps === b.steps
    && a.label === b.label
    && a.title === b.title;
}

/**
 * 抓取结果与上一轮逐项对齐（引用稳定化）：
 * 同位置内容未变的条目复用旧对象引用，Solid `<For>` 按引用比对 ⇒ 不重建
 * 该条 DOM ⇒ 滚动位置不跳；整轮完全一致时直接返回旧数组（同一引用 =
 * signal 不触发重渲染）。轮询只做增量更新，不做尾部整体重建。
 */
export function stabilizeItems<T>(prev: T[], next: T[], same: (a: T, b: T) => boolean): T[] {
  if (prev.length === next.length && prev.every((p, i) => same(p, next[i]))) {
    return prev;
  }
  return next.map((n, i) => {
    const p = prev[i];
    return p && same(p, n) ? p : n;
  });
}

/**
 * 子代理只读面板（B3 前端）：中间面板「子任务」视图内容区
 *（顶栏「子任务」入口切 middleView；点左栏任意处切回预览框）。
 * - 列表态：卡片（任务摘要 + 运行态 + 步数），点击进记录态；
 * - 记录态：从后端事件流派生的只读执行记录（用户任务 / 助手正文+思考 / 工具活动），
 *   无输入框（只读回看，对齐 Qoder：点卡片进子代理执行记录）。
 * 组件仅在子任务视图挂载（MiddlePanel 条件渲染），onMount 起轮询、卸载清理。
 */
export function SubagentRail() {
  const [threads, setThreads] = createSignal<SubagentThread[]>([]);
  const [selected, setSelected] = createSignal<SubagentThread | null>(null);
  const [record, setRecord] = createSignal<SubagentRecordMessage[]>([]);
  const [loadingList, setLoadingList] = createSignal(false);
  const [loadingRecord, setLoadingRecord] = createSignal(false);
  const [err, setErr] = createSignal('');

  async function refreshList() {
    setLoadingList(true);
    try {
      const resp = await getSubagentThreads();
      // 增量更新：内容一致的条目复用旧引用，避免整列表重建（父阻塞期轮询高频）
      setThreads((prev) => stabilizeItems(prev, resp.subagents || [], sameThread));
      setErr('');
    } catch {
      setErr('子任务列表加载失败');
    } finally {
      setLoadingList(false);
    }
  }

  async function refreshRecord(thread: SubagentThread) {
    try {
      const resp = await getSubagentRecord(thread.conversation_id);
      // 仅当仍是同一选中线程才落数据（防快速切换串台）
      if (selected()?.conversation_id === thread.conversation_id) {
        // 增量更新：同位置未变条目复用旧引用 ⇒ 不重建 DOM ⇒ 滚动位置不跳
        setRecord((prev) => stabilizeItems(prev, resp.messages || [], sameRecordMsg));
        setErr('');
      }
    } catch {
      setErr('执行记录加载失败');
    }
  }

  async function openThread(thread: SubagentThread) {
    setSelected(thread);
    setRecord([]);
    setLoadingRecord(true);
    await refreshRecord(thread);
    setLoadingRecord(false);
  }

  function closeThread() {
    setSelected(null);
    setRecord([]);
    setErr('');
  }

  // actor 卡点击 → 直接进该子代理的只读记录（流式二期）：请求到达即选中对应线程；
  // 清单尚未拉到时不消费（不提前清请求），轮询/首拉更新 threads 后本 effect 再跑一次
  createEffect(() => {
    const cid = pendingSubagentRecord();
    if (!cid) return;
    const hit = threads().find((th) => th.conversation_id === cid);
    if (!hit) return;
    clearPendingSubagentRecord();
    void openThread(hit);
  });

  onMount(() => {
    refreshList();
    const id = setInterval(() => {
      const sel = selected();
      // 选中态：只刷新当前线程记录；列表态：刷新清单
      if (sel) void refreshRecord(sel);
      else void refreshList();
    }, POLL_MS);
    onCleanup(() => clearInterval(id));
  });

  // 列表按更新时间倒序（id 含时间戳，字典序近似创建序；无 sort 元数据靠后端原序反转兜底）
  const ordered = () => [...threads()].reverse();

  return (
    <div class="subagent-rail">
      <Show
        when={selected()}
        fallback={
          /* ---------- 列表态 ---------- */
          <div class="subagent-list">
            <Show when={err() && !threads().length}>
              <div class="subagent-empty">{err()}</div>
            </Show>
            <Show when={!loadingList() && !threads().length && !err()}>
              <div class="subagent-empty">
                还没有子任务。批量拆解剧本 / 撰写提示词时，Agent 会把这段重活委派给子代理，
                它会在这里以卡片形式出现。
              </div>
            </Show>
            <For each={ordered()}>
              {(th) => (
                <button
                  type="button"
                  class="subagent-card"
                  data-testid="subagent-card"
                  onClick={() => openThread(th)}
                >
                  <div class="subagent-card-head">
                    <span class={`subagent-status ${statusClass(th.status)}`}>
                      <span class="subagent-status-dot" />
                      {statusText(th.status)}
                    </span>
                    <span class="subagent-steps">{th.steps} 步</span>
                  </div>
                  <div class="subagent-card-label" title={th.label || th.title}>
                    {th.label || th.title || '子任务'}
                  </div>
                </button>
              )}
            </For>
          </div>
        }
      >
        {/* ---------- 记录态（只读，无输入框） ---------- */}
        {(th) => (
          <div class="subagent-record">
            <div class="subagent-record-head">
              <button type="button" class="subagent-back" onClick={closeThread}
                aria-label="返回子任务列表">
                <FiArrowLeft size={14} />
                <span>返回</span>
              </button>
              <span class={`subagent-status ${statusClass(th().status)}`}>
                <span class="subagent-status-dot" />
                {statusText(th().status)}
              </span>
            </div>
            <div class="subagent-record-title" title={th().label || th().title}>
              {th().label || th().title || '子任务执行记录'}
            </div>

            <div class="subagent-record-list" data-testid="subagent-record-list">
              <Show when={loadingRecord() && !record().length}>
                <div class="subagent-empty">加载中…</div>
              </Show>
              <Show when={!loadingRecord() && !record().length && !err()}>
                <div class="subagent-empty">该子任务暂无可回看的执行记录。</div>
              </Show>
              <Show when={err()}>
                <div class="subagent-empty">{err()}</div>
              </Show>
              <For each={record()}>
                {(m) => (
                  <Show
                    when={m.sender === 'user'}
                    fallback={
                      <div class={`chat-msg agent${m.streaming ? ' subagent-step-live' : ''}`}>
                        {/* 2026-09-22 批4（Q4.1）：在途步默认展开思考并随轮询长出，
                            不再要求用户手点 <details> 才看得到（对齐主对话框
                            流式中自动展开的口径）。已完成步保持折叠。 */}
                        <Show when={m.reasoning_content}>
                          <details class="subagent-reasoning" open={!!m.streaming}>
                            <summary>
                              {m.streaming ? '思考中…' : '思考'}
                              <Show when={m.elapsed_ms != null}>
                                <span class="subagent-step-elapsed">
                                  · {formatElapsed(m.elapsed_ms || 0)}
                                </span>
                              </Show>
                            </summary>
                            <div class="subagent-reasoning-body">{m.reasoning_content}</div>
                          </details>
                        </Show>
                        <Show when={m.text}>
                          <MarkdownBubble text={m.text || ''} />
                        </Show>
                        <Show when={m.actionLog && m.actionLog.length}>
                          <div class="subagent-tool-line">
                            执行：{(m.actionLog || []).join('、')}
                          </div>
                        </Show>
                        {/* 无思考的步（纯工具步）：耗时挂条目尾部，回看可知每步多久 */}
                        <Show when={!m.reasoning_content && m.elapsed_ms != null}>
                          <div class="subagent-step-elapsed">· {formatElapsed(m.elapsed_ms || 0)}</div>
                        </Show>
                      </div>
                    }
                  >
                    <div class="chat-msg user">
                      <div class="chat-bubble">{m.text}</div>
                      <Show when={m.ts}>
                        <div class="msg-meta">{formatHHMM(m.ts)}</div>
                      </Show>
                    </div>
                  </Show>
                )}
              </For>
            </div>
          </div>
        )}
      </Show>
    </div>
  );
}
