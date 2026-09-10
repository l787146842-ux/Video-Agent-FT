import { createSignal, For, Show, onMount, onCleanup } from 'solid-js';
import { FiArrowLeft } from 'solid-icons/fi';
import { getSubagentThreads, getSubagentRecord } from '@/api/conversations';
import type { SubagentThread, SubagentRecordMessage } from '@/types';
import { MarkdownBubble } from '../right-panel/MarkdownBubble';

/** 左栏「子任务」Tab 打开期间的轮询间隔：子级在父本轮内联同步跑完，
 *  父阻塞期间无独立 SSE 帧可推，故靠轻量轮询把 running→completed 过渡显形。 */
const POLL_MS = 4000;

function statusClass(s: string): string {
  return s === 'running' ? 'running' : s === 'completed' ? 'completed' : 'unknown';
}
function statusText(s: string): string {
  return s === 'running' ? '执行中' : s === 'completed' ? '已完成' : '未知';
}
/** epoch ms → HH:MM（记录条目时间戳；无值返回空串不显示） */
function formatHHMM(ts?: number): string {
  if (!ts) return '';
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/**
 * 子代理只读面板（B3 前端）：左栏第 3 个 Tab 的内容区。
 * - 列表态：卡片（任务摘要 + 运行态 + 步数），点击进记录态；
 * - 记录态：从后端事件流派生的只读执行记录（用户任务 / 助手正文+思考 / 工具活动），
 *   无输入框（只读回看，对齐 Qoder：点卡片进子代理执行记录）。
 * 组件仅在 Tab 激活时挂载（LeftPanel 条件渲染），onMount 起轮询、卸载清理。
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
      setThreads(resp.subagents || []);
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
        setRecord(resp.messages || []);
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
                      <Show
                        when={m.sender === 'system'}
                        fallback={
                          <div class="chat-msg agent">
                            <Show when={m.reasoning_content}>
                              <details class="subagent-reasoning">
                                <summary>思考</summary>
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
                          </div>
                        }
                      >
                        {/* 完成章（dsh A2）：谁在何时宣告完成 + 当时客观账本 */}
                        <div class="subagent-stamp" data-testid="subagent-stamp">
                          <div class="subagent-stamp-head">
                            <span>本轮宣告完成</span>
                            <Show when={m.ts}>
                              <span class="msg-meta">{formatHHMM(m.ts)}</span>
                            </Show>
                          </div>
                          <div class="subagent-stamp-body">{m.text}</div>
                        </div>
                      </Show>
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
