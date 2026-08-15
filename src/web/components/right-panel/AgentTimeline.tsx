import { For, Show, createEffect, createSignal, onCleanup } from 'solid-js';
import {
  FiCheckCircle, FiChevronDown, FiLoader, FiXCircle, FiZap,
} from 'solid-icons/fi';
import { t } from '@/lib/locale';
import type { ChatMessage, TraceAction } from '@/types';

/** 耗时格式化：<0.1s 显示毫秒（本地状态操作很快，0.0s 看着像没计时） */
export function formatElapsed(ms: number): string {
  return ms < 100 ? `${Math.max(1, Math.round(ms))}ms` : `${(ms / 1000).toFixed(1)}s`;
}

/** 时间线单条操作条目（流式运行态与历史重建共用） */
export interface TimelineItem {
  id: string;
  summary: string;
  status: 'running' | 'done' | 'failed';
  elapsed_ms?: number;
  /** 814G2：运行态走秒起点 */
  started_at_ms?: number;
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

/** 执行器工具 → 大阶段名（阶段完成卡只展示大阶段，不重复正文细节） */
const STAGE_TOOL_LABELS: Array<[string, string]> = [
  ['script_analyze', '剧本分析'],
  ['storyboard_key_elements', '关键元素拆解'],
  ['storyboard_shots', '分镜设计'],
  ['storyboard_audio', '音频层设计'],
  ['write_media_prompt', '媒体提示词编写'],
  ['image_generate', '设定图生成'],
  ['audio_generate', '音频生成'],
  ['video_assembler', '时间线组装'],
];

/**
 * 推导本轮完成的「大阶段」名：按执行顺序取最后一个命中的阶段执行器。
 * 无阶段执行器（如纯确认轮）返回空串，卡片回退通用「阶段完成」。
 */
export function stageLabelFromMessage(msg: ChatMessage): string {
  const steps = msg.trace?.steps || [];
  let label = '';
  steps.forEach((s) => {
    (s.actions || []).forEach((a: TraceAction) => {
      const hit = STAGE_TOOL_LABELS.find(([tool]) => a.name === tool);
      if (hit) label = hit[1];
    });
  });
  return label;
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
  /** 深度思考总耗时（毫秒，完成后展示在卡片角标） */
  thinkingMs?: number;
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

  // 流式思考视窗自动跟随（814G9）：overflow-y:auto 可滚轮回看上文；
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

  // 814G2：运行中条目走秒计时（有 running 条目时每 500ms 刷新一次 now）
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
                      {/* 814G2：完成态显示最终耗时；运行态走秒（有起点才显示） */}
                      <Show when={item.status !== 'running' && item.elapsed_ms != null}>
                        <span class="tl-item-elapsed">
                          · {formatElapsed(item.elapsed_ms || 0)}
                        </span>
                      </Show>
                      <Show when={item.status === 'running' && item.started_at_ms != null}>
                        <span class="tl-item-elapsed">
                          · {formatElapsed(Math.max(0, now() - (item.started_at_ms || 0)))}
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
