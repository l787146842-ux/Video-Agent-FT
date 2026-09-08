/**
 * 微调浮动子对话浮窗（批 S4；方案「微调真子对话对齐外部标杆」）。
 *
 * 非模态可拖拽浮窗，模式同 DocsPanel：fixed 全屏容器不拦事件
 * （pointer-events:none），窗口本体生效事件；标题栏按住拖动；右上角 ×
 * 仅隐藏（线程存活，再点入口 openThread 重载历史）。
 * 渲染条件：注册表任一线程 open=true（一期单浮窗；多 open 取最近登记）。
 * 浮窗打开且有运行中任务 → subscribeScopeThread 惰性订阅（防连接耗尽）。
 * 数据面只消费 adjustScopes（scope fx 结构性分流，delta 不进 chatState）。
 */
import {
  createSignal, createEffect, createMemo, lazy, For, Show, Suspense, type JSX,
} from 'solid-js';
import { FiX } from 'solid-icons/fi';
import { adjustScopes, adjustScopeActions } from '@/stores/adjust-scopes';
import { subscribeScopeThread } from '@/hooks/use-sse';
import { t } from '@/lib/locale';
import type { TimelineItem } from '@/lib/timeline';
import type { ChatMessage } from '@/types';
import { MarkdownBubble } from '@/components/right-panel/MarkdownBubble';
import { ImageResultCard } from '@/components/right-panel/ImageResultCard';
import { VideoResultCard } from '@/components/right-panel/VideoResultCard';
import { AgentTimeline } from '@/components/right-panel/AgentTimeline';

// 底部区（素材清单 + 附件入口 + 输入行）惰性装载：浮窗打开才加载，首包不预付（入口体积预算）
const AdjustInputBar = lazy(() => import('./AdjustInputBar'));

/** 消息行：用户气泡 / agent markdown 气泡 + 图卡/视频卡（渲染件复用主聊天） */
function MessageRow(props: { message: ChatMessage }) {
  const m = () => props.message;
  return (
    <Show
      when={m().sender === 'user'}
      fallback={
        <div class="adjust-msg agent">
          <Show when={m().imageCard} keyed>{(card) => <ImageResultCard card={card} />}</Show>
          <Show when={m().videoCard} keyed>{(card) => <VideoResultCard card={card} />}</Show>
          <Show when={m().text}><MarkdownBubble text={m().text} /></Show>
        </div>
      }
    >
      <div class="adjust-msg user">
        <div class="adjust-bubble-user">{m().text}</div>
      </div>
    </Show>
  );
}

export function AdjustDialog() {
  /** 当前浮窗线程：任一 open 即渲染；多 open 取最近登记（一期单浮窗） */
  const activeKey = createMemo(() => {
    let key = '';
    for (const [k, th] of Object.entries(adjustScopes)) if (th.open) key = k;
    return key;
  });
  const thread = () => (activeKey() ? adjustScopes[activeKey()] : undefined);

  // ===== 拖拽定位（同 DocsPanel：null=默认位，拖动后记左上角坐标） =====
  const [pos, setPos] = createSignal<{ x: number; y: number } | null>(null);
  let panelEl: HTMLDivElement | undefined;
  let bodyEl: HTMLDivElement | undefined;
  let dragOffset: { dx: number; dy: number } | null = null;

  /** 切换/重开浮窗回默认位 */
  createEffect(() => { void activeKey(); setPos(null); });

  /** 标题栏按下开始拖拽（忽略按钮/输入等可交互元素上的按下） */
  const startDrag = (e: PointerEvent & { currentTarget: HTMLElement }) => {
    const target = e.target as HTMLElement;
    if (target.closest('button, input, textarea, a')) return;
    const el = panelEl;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    dragOffset = { dx: e.clientX - rect.left, dy: e.clientY - rect.top };
    e.preventDefault();
    const onMove = (ev: PointerEvent) => {
      if (!dragOffset || !panelEl) return;
      const w = panelEl.offsetWidth;
      const x = Math.min(Math.max(ev.clientX - dragOffset.dx, 8), Math.max(8, window.innerWidth - w - 8));
      const y = Math.min(Math.max(ev.clientY - dragOffset.dy, 8), Math.max(8, window.innerHeight - 60));
      setPos({ x, y });
    };
    const onUp = () => {
      dragOffset = null;
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };

  const panelStyle = (): JSX.CSSProperties | undefined => {
    const p = pos();
    return p ? { position: 'fixed', left: `${p.x}px`, top: `${p.y}px` } : undefined;
  };

  /** 浮窗打开且任务运行中 → 惰性订阅（replay 恢复流式累积；空闲不开连接） */
  createEffect(() => {
    const k = activeKey();
    if (k && adjustScopes[k]?.taskId) subscribeScopeThread(k);
  });

  /** 新消息/流式推进 → 滚到底 */
  createEffect(() => {
    const th = thread();
    void th?.messages.length;
    void th?.streaming.text;
    requestAnimationFrame(() => { if (bodyEl) bodyEl.scrollTop = bodyEl.scrollHeight; });
  });

  /** 折叠工具步骤数据面：线程工具条目 → 时间线条目（复用 AgentTimeline 渲染） */
  const timelineItems = (): TimelineItem[] => (thread()?.streaming.tools || []).map((x) => ({
    id: x.id,
    summary: x.summary || x.name,
    name: x.name,
    status: x.status,
    started_at_ms: x.startedAtMs,
    elapsed_ms: x.elapsedMs,
    result_summary: x.resultSummary,
  }));

  const [text, setText] = createSignal('');

  return (
    <Show when={thread()} keyed>
      {(th) => (
        <div class="adjust-dialog">
          <div class="adjust-dialog-inner" ref={panelEl} style={panelStyle()}>
            {/* 标题栏：按住拖动；× 仅隐藏（线程存活） */}
            <div class="adjust-dialog-header" onPointerDown={startDrag}>
              <span class="adjust-dialog-title" title={th.scope.label}>
                {t('rp.adjust.title')} | {th.scope.label}
              </span>
              <button
                type="button"
                class="adjust-dialog-close"
                title={t('rp.adjust.close')}
                onClick={() => adjustScopeActions.closeThread(activeKey())}
              >
                <FiX size={15} />
              </button>
            </div>

            {/* 消息流：历史气泡 + 流式块（思考/工具步骤折叠面板/逐字回复） */}
            <div class="adjust-dialog-body" ref={bodyEl}>
              <For each={th.messages}>{(m) => <MessageRow message={m} />}</For>
              <Show when={th.status === 'starting' && !th.streaming.active}>
                <div class="adjust-status">{t('rp.streaming.connecting')}</div>
              </Show>
              <Show when={th.streaming.active}>
                <div class="adjust-msg agent">
                  <AgentTimeline
                    reasoning={() => th.streaming.reasoning}
                    items={timelineItems()}
                    live
                    liveStatus={() => th.streaming.statusText}
                  />
                  <Show when={th.streaming.text}>
                    <MarkdownBubble text={th.streaming.text} />
                  </Show>
                </div>
              </Show>
            </div>

            {/* 底部：参考素材清单 + 输入行（附件/粘贴/发送）——惰性块，浮窗打开才装载 */}
            <div class="adjust-dialog-footer">
              <Suspense fallback={null}>
                <AdjustInputBar scopeKey={activeKey} thread={thread} text={text} setText={setText} />
              </Suspense>
            </div>
          </div>
        </div>
      )}
    </Show>
  );
}
