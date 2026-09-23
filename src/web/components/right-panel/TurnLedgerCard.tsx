/**
 * TurnLedgerCard — 轮次账本卡（F2 阶段二：渲染统一）。
 *
 * 单组件承载 live/settled 双相位，消除「销毁重建」式双套渲染：
 * - live 相位（ChatFeed 流式块）：阶段进度条 + AgentTimeline(live)
 *   （旋转图标/走秒等运行装饰归 AgentTimeline 相位分支）；
 * - settled 相位（ChatMessageItem 消息内）：阶段完成卡 + 已回应标注 +
 *   同构 AgentTimeline(settled)，账目数据经 ledgerFromSettled 归一入口。
 * 两相位 DOM 骨架同构（同一 .agent-timeline 面板结构），流结束时
 * 「相位翻转」在渲染层不重排、不闪跳。
 *
 * 组件以片段形态直接渲染子件（不加包裹元素），保持 .chat-msg 既有
 * flex 布局层级与间距口径，零视觉漂移（样式清账战役期间不动 CSS）。
 */
import { Show } from 'solid-js';
import type { ChatMessage } from '@/types';
import type { TurnLedger, TurnPhase } from '@/lib/turn-ledger';
import { AgentTimeline } from './AgentTimeline';
import { StageProgressBar } from './StageProgressBar';

/** 批次B：prefers-reduced-motion 检测（jsdom 下 matchMedia 缺失时回落允许动画，
 * 测试以 matchMedia mock 真实断言 reduce 场景） */
function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function TurnLedgerCard(props: {
  /** 显式相位：live=流式累积中；settled=已完成（含停止/出错后的定型） */
  phase: TurnPhase;
  /** 本轮账本数据源（live=chatState.turnLedger；settled=消息翻转账本，
   *  无本地账本时由消费侧回落 ledgerFromSettled(trace) 同一归一入口） */
  ledger: () => TurnLedger;
  /** settled 相位：本轮所属消息（阶段完成卡标题/生命周期徽标派生依据） */
  message?: () => ChatMessage;
  /** 暂停卡生命周期（answered/expired 时阶段卡挂徽标，回看不迷惑） */
  confirmState?: 'active' | 'answered' | 'expired' | 'none';
  /** 已回应暂停卡的「当时所选值」（其后首条用户消息文本） */
  answeredValue?: string;
}) {
  /** settled 相位消息访问器（live 相位不消费，缺失时以空消息兜底） */
  const msg = (): ChatMessage => (props.message ? props.message() : { sender: 'agent', text: '' });

  /** 批次B账本翻转淡入：settled 新挂载卡片 120ms opacity 0→1 淡入；
   * reduced-motion 时为空串（opacity 直接呈现，无过渡）。相位翻转时
   * fallback 子件新建即带类，CSS animation 随挂载播放一次 */
  const fadeClass = prefersReducedMotion() ? '' : 'ledger-fade-in';

  return (
    <Show
      when={props.phase === 'live'}
      fallback={
        <>
          {/* 2026-09-22 批7（Q1，用户裁决）：原「阶段完成卡」（StageCard）**整卡删除**。
              用户目击（截图1 红框）：同一句题面在屏幕上画了两遍——StageCard 画一次
              （`阶段完成 · 已执行 2 个操作 · 已回应` + `画幅比例选哪种?`），
              ConfirmActions 的 `.confirm-wizard-question` 又画一次。根因是两条渲染
              路径各画各的，而 StageCard 的判重条件只在「active 且带选项」时让位，
              answered/expired 一律照画（红框那张正是 answered 态）。
              删除后题面唯一出口 = ConfirmActions（其无选项分支本批已补题面行，
              见该文件；无选项暂停此前**只**由本卡承载题面，不补会丢字）。
              回看不受损：批K 已把「问题→你的选择」搬进**用户自己的气泡**
              （UserBubble → AskQuestionReceipt → PauseQaBlock），agent 侧无需再承载。
              操作数徽标另有归属：AgentTimeline「已处理操作」面板（trace 同源）。 */}

          {/* 过程时间线（深度思考 + 已处理操作；settled 定型面板形态，
              账目优先消费相位翻转账本，回落路径由 ledger 数据源侧保证） */}
          <AgentTimeline
            phase="settled"
            reasoning={() => props.ledger().reasoning}
            items={props.ledger().items}
            thinkingMs={props.ledger().thinkingMs}
            class={fadeClass}
          />
        </>
      }
    >
      {/* live 相位：流式块（阶段进度条 + 运行装饰时间线），数据源 = 归一后的本轮账本 */}
      <StageProgressBar />
      <AgentTimeline
        phase="live"
        reasoning={() => props.ledger().reasoning}
        items={props.ledger().items}
        liveStatus={() => props.ledger().statusText}
      />
    </Show>
  );
}
