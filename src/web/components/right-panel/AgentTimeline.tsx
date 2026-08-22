import { For, Show, createEffect, createSignal, onCleanup } from 'solid-js';
import {
  FiCheckCircle, FiChevronDown, FiLoader, FiXCircle, FiZap,
} from 'solid-icons/fi';
import { t } from '@/lib/locale';
import {
  consolidateTimeline, formatElapsed, resultSummaryView, type TimelineItem,
} from '@/lib/timeline';
import type { ChatMessage, TraceAction } from '@/types';

// 耗时格式化与条目类型归 lib/timeline 单一事实源；保留 re-export 兼容既有导入
export { formatElapsed };
export type { TimelineItem };

/**
 * 从已完成消息的 trace / actionLog 重建时间线数据（刷新页面后不丢）。
 * trace.steps[].actions 优先；旧消息无 actions 时用 actionLog 兜底。
 */
export function timelineFromMessage(msg: ChatMessage): { reasoning: string; items: TimelineItem[] } {
  const steps = msg.trace?.steps || [];
  const reasoning = steps
    .map((s) => s.reasoning || '')
    .filter(Boolean)
    .join('\n');
  const items: TimelineItem[] = [];
  steps.forEach((s) => {
    (s.actions || []).forEach((a: TraceAction, i: number) => {
      // 规划条目与 live 事件同构 id（llm-s{step}），历史重建也能命中合并降噪
      const id = a.name === 'model_reasoning' ? `llm-s${s.step}` : `t-${s.step}-${i}`;
      items.push({
        id,
        summary: a.summary || a.name,
        status: a.ok ? 'done' : 'failed',
        elapsed_ms: a.elapsed_ms,
        // 后端持久化的结果摘要（与 live tool_finished 同口径）
        result_summary: a.result_summary || undefined,
        // 规划级执行器徽标（重建与 live 同源）
        planning: a.planning || undefined,
      });
    });
  });
  if (!items.length && (msg.actionLog || []).length) {
    msg.actionLog!.forEach((op, i) => {
      items.push({ id: `l-${i}`, summary: op, status: 'done' });
    });
  }
  return { reasoning, items };
}

/** 执行器工具 → 大阶段名： 起改为后端权威下发（trace 条目 stage 字段），
 * 前端不再硬编码推断，工具改名不会导致卡片退化（13.7 登记）。 */

/**
 * 推导本轮完成的「大阶段」名：取 trace 条目携带的 stage（后端权威）；
 * 无 stage（旧消息）回退空串，卡片显示通用「阶段完成」。
 */
export function stageLabelFromMessage(msg: ChatMessage): string {
  const steps = msg.trace?.steps || [];
  let label = '';
  steps.forEach((s) => {
    (s.actions || []).forEach((a: TraceAction) => {
      if (a.stage) label = a.stage;
    });
  });
  return label;
}

/** 单条时间线条目（合并条目带逐轮明细，点击展开；展开态用户可控） */
function TimelineRow(props: { item: TimelineItem; now: () => number }) {
  const [open, setOpen] = createSignal(false);
  /** result_summary 详情展开态（折叠=一句话摘要，展开=全文） */
  const [resultOpen, setResultOpen] = createSignal(false);
  const item = () => props.item;
  return (
    <li class={`tl-item tl-item-${item().status}`}>
      <Show
        when={item().status !== 'running'}
        fallback={<FiLoader size={13} class="tl-item-icon spin" />}
      >
        <Show
          when={item().status === 'done'}
          fallback={<FiXCircle size={13} class="tl-item-icon failed" />}
        >
          <FiCheckCircle size={13} class="tl-item-icon ok" />
        </Show>
      </Show>
      {/* 带明细的合并条目：summary 可点击展开逐轮明细 */}
      <Show
        when={(item().details || []).length > 0}
        fallback={<span class="tl-item-summary">{item().summary}</span>}
      >
        <button
          type="button"
          class="tl-item-summary tl-item-summary-toggle"
          onClick={() => setOpen(!open())}
        >
          {item().summary}
          <FiChevronDown size={11} class={`tl-item-toggle-arrow${open() ? ' expanded' : ''}`} />
        </button>
      </Show>
      {/* 规划级执行器徽标（不产真实媒体，欠账显性化） */}
      <Show when={item().planning}>
        <span class="tl-planning-badge" title="规划级执行器：产出规划/方案文本，不产生真实媒体文件">规划</span>
      </Show>
      {/* 完成态显示最终耗时；运行态走秒（有起点才显示） */}
      <Show when={item().status !== 'running' && item().elapsed_ms != null}>
        <span class="tl-item-elapsed">· {formatElapsed(item().elapsed_ms || 0)}</span>
      </Show>
      <Show when={item().status === 'running' && item().started_at_ms != null}>
        <span class="tl-item-elapsed">
          · {formatElapsed(Math.max(0, props.now() - (item().started_at_ms || 0)))}
        </span>
      </Show>
      {/* 工具执行结果一句话摘要（与 summary 重复时不重复展示）；
          多句摘要可点击展开全文（折叠态默认一句话，纯前端切换） */}
      <Show
        when={item().status !== 'running' && item().result_summary
          && item().result_summary !== item().summary}
      >
        <Show
          when={resultSummaryView(item().result_summary || '').expandable}
          fallback={
            <span class="tl-item-result" title={item().result_summary}>
              ↳ {item().result_summary}
            </span>
          }
        >
          <button
            type="button"
            class={`tl-item-result tl-item-result-toggle${resultOpen() ? ' expanded' : ''}`}
            onClick={() => setResultOpen(!resultOpen())}
          >
            ↳ {resultOpen()
              ? item().result_summary
              : resultSummaryView(item().result_summary || '').collapsed}
            <FiChevronDown size={11} class={`tl-item-toggle-arrow${resultOpen() ? ' expanded' : ''}`} />
          </button>
        </Show>
      </Show>
      <Show when={open() && (item().details || []).length > 0}>
        <ul class="tl-sublist">
          <For each={item().details}>
            {(d) => (
              <li class={`tl-subitem tl-item-${d.status}`}>
                <span class="tl-item-summary">{d.summary}</span>
                <Show when={d.elapsed_ms != null}>
                  <span class="tl-item-elapsed">· {formatElapsed(d.elapsed_ms || 0)}</span>
                </Show>
              </li>
            )}
          </For>
        </ul>
      </Show>
    </li>
  );
}

/**
 * Agent 过程时间线（深度思考 + 已处理操作，两个折叠面板）。
 * 内容全部来自 SSE 一次性事件 / 消息 trace 字段，不进下次 LLM 上下文。
 */
export function AgentTimeline(props: {
  /** 静态文本或响应式 getter（流式场景传  => chatState.streamingReasoning） */
  reasoning?: string | (() => string);
  items: TimelineItem[];
  /** 流式中：操作面板默认展开，运行项显示旋转图标 */
  live?: boolean;
  /** 深度思考总耗时（毫秒，完成后展示在卡片角标） */
  thinkingMs?: number;
  /** 实时状态文案（状态栏=当前正在做的一件事），流式标题优先展示 */
  liveStatus?: () => string;
}) {
  // 深度思考面板：流式中自动展开（实时看思考流），完成后自动折叠（live 卸载后
  // 消息重建时初始值为 false）；展开/折叠始终可由用户手动切换
  // eslint-disable-next-line solid/reactivity
  const [thinkOpen, setThinkOpen] = createSignal(!!props.live);
  // live 仅取一次性初始值（流式入场时默认展开操作面板），后续展开态由用户控制
  // eslint-disable-next-line solid/reactivity
  const [opsOpen, setOpsOpen] = createSignal(!!props.live);

  const reasoningText = () =>
    (typeof props.reasoning === 'function' ? props.reasoning() : props.reasoning) || '';
  const hasReasoning = () => !!reasoningText();
  const hasItems = () => props.items.length > 0;
  const doneCount = () => props.items.filter((i) => i.status !== 'running').length;

  // 流式思考视窗自动跟随：overflow-y:auto 可滚轮回看上文；
  // 仅当用户停在底部附近时才自动追新文字，滚上去看历史不被打断
  let reasoningRef: HTMLDivElement | undefined;
  createEffect(() => {
    void reasoningText();
    if (props.live && reasoningRef) {
      requestAnimationFrame(() => {
        if (!reasoningRef) return;
        const nearBottom =
          reasoningRef.scrollHeight - reasoningRef.scrollTop - reasoningRef.clientHeight < 60;
        if (nearBottom) reasoningRef.scrollTop = reasoningRef.scrollHeight;
      });
    }
  });

  // ：运行中条目走秒计时（有 running 条目时每 500ms 刷新一次 now）
  const [now, setNow] = createSignal(Date.now());
  const hasRunning = () => props.items.some((i) => i.status === 'running');
  let tickTimer: ReturnType<typeof setInterval> | undefined;
  createEffect(() => {
    const running = hasRunning();
    if (running && tickTimer === undefined) {
      tickTimer = setInterval(() => setNow(Date.now()), 500);
    } else if (!running && tickTimer !== undefined) {
      clearInterval(tickTimer);
      tickTimer = undefined;
    }
  });
  onCleanup(() => { if (tickTimer !== undefined) clearInterval(tickTimer); });

  // 降噪：连续规划条目合并为「规划 N 轮 · 累计 Xs」单条（明细可展开）；
  // 工具/执行器条目不受影响，流式 running 段不合并保持实时逐条可见
  const viewItems = () => consolidateTimeline(props.items);

  return (
    <Show when={hasReasoning() || hasItems()}>
      <div class="agent-timeline">
        {/* 深度思考面板（reasoning 模型才有文本；普通模型不显示该面板） */}
        <Show when={hasReasoning()}>
          <div class={`tl-panel ${thinkOpen() ? 'expanded' : ''}`}>
            <button
              type="button"
              class="tl-panel-header"
              onClick={() => setThinkOpen(!thinkOpen())}
            >
              <FiZap size={13} class="tl-icon-thinking" />
              <span class="tl-panel-title">{t('rp.timeline.thinking')}</span>
              {/* 思考完成后的耗时角标（流式中不显示） */}
              <Show when={!props.live && props.thinkingMs}>
                <span class="tl-panel-elapsed">· {formatElapsed(props.thinkingMs || 0)}</span>
              </Show>
              <FiChevronDown size={12} class="tl-arrow" />
            </button>
            <div class="tl-panel-body">
              <Show
                when={!props.live}
                fallback={
                  // 流式中：定高视窗，旧文字随滚动隐藏，只显示最新几行
                  <div ref={reasoningRef} class="tl-reasoning tl-reasoning-live">
                    {reasoningText()}
                  </div>
                }
              >
                <div class="tl-reasoning">{reasoningText()}</div>
              </Show>
            </div>
          </div>
        </Show>

        {/* 已处理操作面板 */}
        <Show when={hasItems()}>
          <div class={`tl-panel ${opsOpen() ? 'expanded' : ''}`}>
            <button
              type="button"
              class="tl-panel-header"
              onClick={() => setOpsOpen(!opsOpen())}
            >
              <FiCheckCircle size={13} class="tl-icon-done" />
              {/* 流式状态文案（正在执行第 N 项…）对读屏器可闻；历史重建态不挂 live */}
              <span class="tl-panel-title" aria-live={props.live ? 'polite' : undefined}>
                {props.live
                  ? (props.liveStatus && props.liveStatus()
                    && props.liveStatus() !== t('rp.streaming.processing')
                    ? `${props.liveStatus()}（已完成 ${doneCount()} 项）`
                    : t('rp.timeline.processing', { count: doneCount() }))
                  : t('rp.timeline.processed', { count: props.items.length })}
              </span>
              <FiChevronDown size={12} class="tl-arrow" />
            </button>
            <div class="tl-panel-body">
              <ul class="tl-item-list">
                <For each={viewItems()}>
                  {(item) => <TimelineRow item={item} now={now} />}
                </For>
              </ul>
            </div>
          </div>
        </Show>
      </div>
    </Show>
  );
}
