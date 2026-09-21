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
import { StageCard } from './StageCard';

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
          {/* 阶段完成卡：可展开、默认展开；正文=本轮概述（确认文案）+执行清单。
              确认文案与模型正文判重防双显；历史消息同样可展开，暂停点回看不丢失。
              （A 批：问答回执卡改挂**用户气泡**内——见 UserBubble/AskQuestionReceipt） */}
          <Show when={msg().confirm}>
            <StageCard msg={msg} state={props.confirmState || 'none'} class={fadeClass} />
          </Show>

          {/* 2026-09-21 批K（用户要求）：原「已回应选项对勾区」（AnsweredOptions）
              已从本卡移除——问答回执改在**用户自己的气泡**内逐问呈现
              （见 UserBubble/PauseQaBlock）。移除理由：该区把整排选项重画后
              用文字匹配打勾，多问题时会混在一起、同名选项会互相串。
              注：`AnsweredOptions` 组件与 `answered-options` 样式保留
              （其他消费面/回归测试仍引用），只是本卡不再挂载。 */}

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
