/**
 * Agent 消息发送高层封装（发送路径收敛后的兼容入口）。
 *
 * 序列化/校验/排队判定的单点实现已归 lib/submit-message.submitMessage；
 * 本文件仅保留 sendUserMessage 旧签名（聊天输入框与左侧面板微调按钮共用），
 * 以 intent='new' 委托统一入口。
 */
import { submitMessage } from '@/lib/submit-message';
import type { PauseAnswer, RichContentPart } from '@/types';

/**
 * 发送用户消息给 Agent（SSE 流式）
 *
 * 入参可为：
 * - string：纯文本（微调按钮 / 确认按钮等纯文字场景）
 * - RichContentPart[]：有序富文本（文字与内联缩略图交错，来自富文本输入框）
 *
 * 返回 true 表示消息已受理发送或已入队（调用方可据此清空输入框）；
 * false 表示被拦截（内容为空 / 未选供应商模型）。
 *
 * Agent 忙碌（推理中）时不拦截：消息进入排队引导区（输入框顶部），
 * 当前任务完成后由排队自动出队逻辑按序发出。
 */
export async function sendUserMessage(
  input: string | RichContentPart[],
  opts?: {
    gateOverrides?: string[];
    /** 暂停回应结构化回携（对标 AskUserQuestion）：点选暂停卡选项时携带，
     *  后端校验后随消息持久化标记，前端对勾不再靠文本反推。
     *  2026-09-21 批J：新增 `answers` —— 问题级回答
     *  `{id, selected[], custom?}`（多问题卡逐问作答时携带，对齐 dsh）。 */
    pauseResponse?: {
      pause_id: string;
      value: string;
      label?: string;
      answers?: PauseAnswer[];
    };
    /** 系统动作标记（唯一形态值 'system_action'，如「本次放行」）：
     *  本地与持久化消息渲染为系统动作行 */
    systemAction?: 'system_action';
  },
): Promise<boolean> {
  return submitMessage('new', {
    input,
    gateOverrides: opts?.gateOverrides,
    pauseResponse: opts?.pauseResponse,
    systemAction: opts?.systemAction,
  });
}
