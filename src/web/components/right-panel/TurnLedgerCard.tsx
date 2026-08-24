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
import { AnsweredOptions } from './AnsweredOptions';

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

  return (
    <Show
      when={props.phase === 'live'}
      fallback={
        <>
          {/* 阶段完成卡：可展开、默认展开；正文=本轮概述（确认文案）+执行清单。
              确认文案与模型正文判重防双显；历史消息同样可展开，暂停点回看不丢失） */}
          <Show when={msg().confirm}>
            <StageCard msg={msg} state={props.confirmState || 'none'} />
          </Show>

          {/* 已回应暂停卡的「当时选了哪项」对勾标注（只读回看） */}
          <Show when={msg().confirm && (props.answeredValue || '') && (msg().confirmOptions || []).length > 0}>
            <AnsweredOptions options={msg().confirmOptions || []} answeredValue={props.answeredValue || ''} />
          </Show>

          {/* 过程时间线（深度思考 + 已处理操作；settled 定型面板形态，
              账目优先消费相位翻转账本，回落路径由 ledger 数据源侧保证） */}
          <AgentTimeline
            phase="settled"
            reasoning={() => props.ledger().reasoning}
            items={props.ledger().items}
            thinkingMs={props.ledger().thinkingMs}
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
