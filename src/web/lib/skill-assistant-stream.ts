/**
 * Skill 助手流式帧解析（对齐后端 routes/plugins.py /skills/assistant/stream）。
 *
 * 事件名复用主链约定（reasoning_delta / delta / status / done / error），
 * 但载荷是本端点专属形状，不经 use-sse 主链路由——在本模块独立收敛，
 * 不进入 SseEvent 联合（避免主链误消费）。
 */
import { pumpSseBody } from '@/lib/reconnecting-sse';
import type { SkillAssistantChecks } from '@/api/docs';

export type SkillAssistantFrame =
  | { type: 'reasoning_delta'; text: string }
  | { type: 'delta'; text: string }
  /** 文档正文增量：直接进中间预览，不进聊天正文 */
  | { type: 'doc_delta'; text: string }
  | { type: 'status'; text: string }
  | {
    type: 'done';
    reply: string;
    content: string | null;
    checks: SkillAssistantChecks | null;
  }
  | { type: 'error'; message: string };

/** 帧流消费：异常 JSON 帧不中断流（与主链 parseSseStream 同口径）；
 * 网络中断由调用方按「未收到 done」判定（pumpSseBody 不穿透读流异常）。 */
export async function consumeSkillAssistantStream(
  body: ReadableStream<Uint8Array>,
  onFrame: (frame: SkillAssistantFrame) => void,
  signal?: AbortSignal,
): Promise<void> {
  await pumpSseBody(body, (data) => {
    let frame: SkillAssistantFrame;
    try {
      frame = JSON.parse(data) as SkillAssistantFrame;
    } catch {
      return;
    }
    if (frame && typeof frame.type === 'string') onFrame(frame);
  }, signal);
}
