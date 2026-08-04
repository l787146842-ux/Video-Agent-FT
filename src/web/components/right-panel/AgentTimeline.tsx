import { For, Show, createSignal } from 'solid-js';
import {
  FiCheckCircle, FiChevronDown, FiLoader, FiXCircle, FiZap,
} from 'solid-icons/fi';
import { t } from '@/lib/locale';
import type { ChatMessage, TraceAction } from '@/types';

/** 时间线单条操作条目（流式运行态与历史重建共用） */
export interface TimelineItem {
  id: string;
  summary: string;
  status: 'running' | 'done' | 'failed';
  elapsed_ms?: number;
}

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
      items.push({
        id: `t-${s.step}-${i}`,
        summary: a.summary || a.name,
        status: a.ok ? 'done' : 'failed',
        elapsed_ms: a.elapsed_ms,
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

/**
 * Agent 过程时间线（深度思考 + 已处理操作，两个折叠面板）。
 * 内容全部来自 SSE 一次性事件 / 消息 trace 字段，不进下次 LLM 上下文。
 */
export function AgentTimeline(props: {
  /** 静态文本或响应式 getter（流式场景传 () => chatState.streamingReasoning） */
  reasoning?: string | (() => string);
  items: TimelineItem[];
  /** 流式中：操作面板默认展开，运行项显示旋转图标 */
  live?: boolean;
}) {
  const [thinkOpen, setThinkOpen] = createSignal(false);
  // live 仅取一次性初始值（流式入场时默认展开操作面板），后续展开态由用户控制
  // eslint-disable-next-line solid/reactivity
  const [opsOpen, setOpsOpen] = createSignal(!!props.live);

  const reasoningText = () =>
    (typeof props.reasoning === 'function' ? props.reasoning() : props.reasoning) || '';
  const hasReasoning = () => !!reasoningText();
  const hasItems = () => props.items.length > 0;
  const doneCount = () => props.items.filter((i) => i.status !== 'running').length;

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
              <FiChevronDown size={12} class="tl-arrow" />
            </button>
            <div class="tl-panel-body">
              <div class="tl-reasoning">{reasoningText()}</div>
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
              <span class="tl-panel-title">
                {props.live
                  ? t('rp.timeline.processing', { count: doneCount() })
                  : t('rp.timeline.processed', { count: props.items.length })}
              </span>
              <FiChevronDown size={12} class="tl-arrow" />
            </button>
            <div class="tl-panel-body">
              <ul class="tl-item-list">
                <For each={props.items}>
                  {(item) => (
                    <li class={`tl-item tl-item-${item.status}`}>
                      <Show
                        when={item.status !== 'running'}
                        fallback={<FiLoader size={13} class="tl-item-icon spin" />}
                      >
                        <Show
                          when={item.status === 'done'}
                          fallback={<FiXCircle size={13} class="tl-item-icon failed" />}
                        >
                          <FiCheckCircle size={13} class="tl-item-icon ok" />
                        </Show>
                      </Show>
                      <span class="tl-item-summary">{item.summary}</span>
                      <Show when={item.elapsed_ms != null && item.elapsed_ms > 0}>
                        <span class="tl-item-elapsed">
                          · {((item.elapsed_ms || 0) / 1000).toFixed(1)}s
                        </span>
                      </Show>
                    </li>
                  )}
                </For>
              </ul>
            </div>
          </div>
        </Show>
      </div>
    </Show>
  );
}
