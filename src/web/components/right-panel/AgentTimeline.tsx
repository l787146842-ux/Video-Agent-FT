import { For, Show, createEffect, createSignal, onCleanup } from 'solid-js';
import {
  FiAlertCircle, FiCheckCircle, FiChevronDown, FiFlag, FiLoader, FiXCircle, FiZap,
} from 'solid-icons/fi';
import { t } from '@/lib/locale';
import { consolidateTimeline, formatElapsed, type TimelineItem } from '@/lib/timeline';
import type { TurnPhase } from '@/lib/turn-ledger';
import { countableItems, SYSTEM_NOTICE } from '@/lib/turn-ledger';
import { TimelineDetail } from './TimelineDetail';

// 耗时格式化与条目类型归 lib/timeline 单一事实源；保留 re-export 兼容既有导入
// （重建/阶段推导函数同批迁入 lib/timeline，详情区分层减行）
export { stageLabelFromMessage, timelineFromMessage } from '@/lib/timeline';
export { formatElapsed };
export type { TimelineItem };

/** 单条时间线条目（合并条目带逐轮明细，点击展开；展开态用户可控） */
function TimelineRow(props: { item: TimelineItem; now: () => number }) {
  const [open, setOpen] = createSignal(false);
  const item = () => props.item;
  // 事件卡（批 2 插播报）：产物落账里程碑，旗标图标 + 卡片配色与工具行区分
  const isCard = () => item().name === 'event_card';
  // 系统事实条（假停机械续跑等机器判定事件）：三角徽标 + 弱化配色，
  // 与工具行/事件卡三种语气区分；文案由 noticeKind 经 i18n 派生，不读 summary
  const isNotice = () => item().name === SYSTEM_NOTICE;
  const text = () => {
    // 取局部常量做窄化：item() 为 signal 读值，重复调用不参与 TS 收窄
    const kind = item().noticeKind;
    return kind ? t(kind, item().noticeParams) : item().summary;
  };
  return (
    <li class={`tl-item tl-item-${item().status}${isCard() ? ' tl-item-card' : ''}${isNotice() ? ' tl-item-notice' : ''}`}>
      <Show
        when={item().status !== 'running'}
        fallback={<FiLoader size={13} class="tl-item-icon spin" />}
      >
        <Show
          when={item().status === 'done'}
          fallback={<FiXCircle size={13} class="tl-item-icon failed" />}
        >
          <Show
            when={isNotice()}
            fallback={
              <Show
                when={!isCard()}
                fallback={<FiFlag size={13} class="tl-item-icon card" />}
              >
                <FiCheckCircle size={13} class="tl-item-icon ok" />
              </Show>
            }
          >
            <FiAlertCircle size={13} class="tl-item-icon notice" />
          </Show>
        </Show>
      </Show>
      {/* 带明细的合并条目：summary 可点击展开逐轮明细 */}
      <Show
        when={(item().details || []).length > 0}
        fallback={<span class="tl-item-summary">{text()}</span>}
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
      {/* 详情区（分级展开）：expand 档可折叠看输入/输出，
          中间/不展开档保持单行结果摘要形态 */}
      <TimelineDetail item={item()} />
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
 * F2 阶段二：phase 显式相位属性——live/settled 双相位同一组件同一 DOM 骨架，
 * 流结束的相位翻转在渲染层同构（运行装饰只随相位增减，结构不重排）。
 */
export function AgentTimeline(props: {
  /** 静态文本或响应式 getter（流式场景传  => chatState.streamingReasoning） */
  reasoning?: string | (() => string);
  items: TimelineItem[];
  /** 显式相位（F2 阶段二）：live=流式运行装饰（旋转图标/走秒/面板默认展开），
   * settled=定型面板（消费 ledgerFromSettled 归一数据） */
  phase?: TurnPhase;
  /** 兼容别名：等同 phase='live'（两者同传时 phase 优先） */
  live?: boolean;
  /** 深度思考总耗时（毫秒，完成后展示在卡片角标） */
  thinkingMs?: number;
  /** 实时状态文案（状态栏=当前正在做的一件事），流式标题优先展示 */
  liveStatus?: () => string;
  /** 附加根类（批次B：settled 相位淡入类由 TurnLedgerCard 透传） */
  class?: string;
}) {
  /** 相位判定单一出口：phase 显式给出时以其为准，未给出回落 live 兼容别名 */
  const isLive = () => (props.phase !== undefined ? props.phase === 'live' : !!props.live);
  // 深度思考面板：流式中自动展开（实时看思考流），完成后自动折叠（相位翻转后
  // settled 实例重建时初始值为 false）；展开/折叠始终可由用户手动切换
  const [thinkOpen, setThinkOpen] = createSignal(isLive());
  // 初始值仅取一次（流式入场时默认展开操作面板），后续展开态由用户控制
  const [opsOpen, setOpsOpen] = createSignal(isLive());

  const reasoningText = () =>
    (typeof props.reasoning === 'function' ? props.reasoning() : props.reasoning) || '';
  const hasReasoning = () => !!reasoningText();
  const hasItems = () => props.items.length > 0;
  // 操作计数只算真实账目（系统提醒条不是“一次操作”，计入会把机器拦下的
  // 零操作轮吹成“已处理 N 个操作”，反而给谎报做证）
  const countable = () => countableItems(props.items);
  const doneCount = () => countable().filter((i) => i.status !== 'running').length;

  // 流式思考视窗自动跟随：overflow-y:auto 可滚轮回看上文；
  // 仅当用户停在底部附近时才自动追新文字，滚上去看历史不被打断
  let reasoningRef: HTMLDivElement | undefined;
  createEffect(() => {
    void reasoningText();
    if (isLive() && reasoningRef) {
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
      <div class={`agent-timeline${props.class ? ` ${props.class}` : ''}`}>
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
              <Show when={!isLive() && props.thinkingMs}>
                <span class="tl-panel-elapsed">· {formatElapsed(props.thinkingMs || 0)}</span>
              </Show>
              <FiChevronDown size={12} class="tl-arrow" />
            </button>
            <div class="tl-panel-body">
              <Show
                when={!isLive()}
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
              <span class="tl-panel-title" aria-live={isLive() ? 'polite' : undefined}>
                {isLive()
                  ? (props.liveStatus && props.liveStatus()
                    && props.liveStatus() !== t('rp.streaming.processing')
                    ? `${props.liveStatus()}（已完成 ${doneCount()} 项）`
                    : t('rp.timeline.processing', { count: doneCount() }))
                  // 零真实账目而只有系统提醒（本轮被机器判定假停且未落任何账）
                  // → 标题直接说客观事实，不再显示误导性的「已处理 1 个操作」
                  : countable().length === 0
                    ? t('rp.timeline.noAction')
                    : t('rp.timeline.processed', { count: countable().length })}
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
