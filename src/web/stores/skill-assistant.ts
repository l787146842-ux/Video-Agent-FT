import { createSignal } from 'solid-js';
import { openSkillAssistantStream, type SkillAssistantChecks } from '@/api/docs';
import {
  consumeSkillAssistantStream, type SkillAssistantFrame,
} from '@/lib/skill-assistant-stream';
import type { SkillAssistantMessage } from '@/types/api.generated';
import { agentProvider, agentModel } from '@/stores/agent-prefs';
import { showToast } from '@/stores/toast';

/**
 * Skill 优化助手（会话级）：流式对话状态与发送动作。
 *
 * 自 skill-studio.ts 拆出（前端 250 行红线）；原路径重导出，调用方零改动。
 * 依赖注入：commitDraft（草稿入撤销栈）与 draftRaw/selectedSlug 由调用方
 * 经 `wireAssistant()` 提供，避免两模块循环 import。
 */

export interface AssistantMsg {
  role: 'user' | 'assistant';
  text: string;
  /** 推理模型思考全文（流式累积，done 后固化可折叠回看） */
  reasoning?: string;
  /** 本轮请求模式（决定自检徽标的检查口径文案） */
  mode?: 'create' | 'optimize';
  /** 创作/优化后端的项目规范自检结果（无全文可查时为空） */
  checks?: SkillAssistantChecks | null;
}

/** 流式中的助手回合：与已完成消息分开，避免逐帧重建历史气泡 */
export interface AssistantStream {
  reasoning: string;
  text: string;
  /** 文档正文增量（中间预览实时跟随；done 后由 content 权威覆盖） */
  doc: string;
  /** 过程状态（自检/自修复等，非正文） */
  status: string;
}

const [assistantMessages, setAssistantMessages] = createSignal<AssistantMsg[]>([]);
const [assistantBusy, setAssistantBusy] = createSignal(false);
const [assistantStream, setAssistantStream] = createSignal<AssistantStream | null>(null);
export { assistantMessages, assistantBusy, assistantStream };
/** 中间预览的实时草稿（空 = 未在生成，预览显示已提交草稿） */
export function assistantLiveDoc(): string { return assistantStream()?.doc || ''; }
/** 在途请求：离页/重置即中断，不在后台空烧 token */
let assistantAbort: AbortController | null = null;

/** 依赖注入口：由 skill-studio.ts 在模块初始化时调用（避免循环 import） */
interface AssistantDeps {
  draftRaw: () => string;
  selectedSlug: () => string;
  commitDraft: (next: string) => void;
}
let deps: AssistantDeps | null = null;
export function wireAssistant(d: AssistantDeps): void {
  deps = d;
}

export function resetAssistant() {
  assistantAbort?.abort();
  assistantAbort = null;
  setAssistantMessages([]);
  setAssistantStream(null);
  setAssistantBusy(false);
}

/** 发送用户请求（SSE 流式）：思考/正文实时入流式气泡；done 帧收口为正式消息
 * （reply 覆盖正文展示，content 覆盖草稿入撤销栈）。流断时保留已收内容。 */
export async function sendAssistant(text: string): Promise<void> {
  const msg = text.trim();
  if (!msg || assistantBusy() || !deps) return;
  setAssistantMessages((m) => [...m, { role: 'user', text: msg }]); setAssistantBusy(true);
  setAssistantStream({ reasoning: '', text: '', doc: '', status: '' });
  const mode = deps.selectedSlug() ? 'optimize' : 'create';
  const history: SkillAssistantMessage[] = assistantMessages().slice(-10).map((m) => ({ role: m.role, content: m.text }));
  const abort = new AbortController();
  assistantAbort = abort;
  // 容器持有 done 帧：闭包赋值 + TS 控制流不追踪局部变量（会窄化为 never）
  const collected: { done: Extract<SkillAssistantFrame, { type: 'done' }> | null } = { done: null };
  let failure = '';
  try {
    const body = await openSkillAssistantStream({
      content: deps.draftRaw(),
      messages: history,
      provider: agentProvider(),
      model: agentModel(),
      mode,
    }, abort.signal);
    await consumeSkillAssistantStream(body, (frame) => {
      if (frame.type === 'reasoning_delta') {
        setAssistantStream((s) => (s ? { ...s, reasoning: s.reasoning + frame.text } : s));
      } else if (frame.type === 'delta') {
        setAssistantStream((s) => (s ? { ...s, text: s.text + frame.text } : s));
      } else if (frame.type === 'doc_delta') {
        setAssistantStream((s) => (s ? { ...s, doc: s.doc + frame.text } : s));
      } else if (frame.type === 'status') {
        setAssistantStream((s) => (s ? { ...s, status: frame.text } : s));
      } else if (frame.type === 'done') {
        collected.done = frame;
      } else if (frame.type === 'error') {
        failure = frame.message;
      }
    }, abort.signal);
  } catch (err) {
    failure = (err as Error).message;
  } finally {
    // 离页/重置已中断：不留残留消息（流式气泡已由 resetAssistant 清空）
    if (assistantAbort === abort) {
      const streamed = assistantStream();
      const reasoning = streamed?.reasoning || undefined;
      const partialText = streamed?.text.trim() || '';
      if (collected.done) {
        const fin = collected.done;
        setAssistantMessages((m) => [...m, {
          role: 'assistant',
          text: fin.reply || '（空回复）',
          reasoning,
          mode,
          checks: fin.checks ?? null,
        }]);
        if (fin.content) deps.commitDraft(fin.content);
        else {
          // 模型未产出可解析的全文：明确告知预览未动（避免「以为改好了」）
          showToast('本轮未解析到完整 Skill 全文，左侧预览未更新', 'warning');
        }
      } else {
        const reasonNote = failure || '流式连接中断，回复可能不完整';
        setAssistantMessages((m) => [...m, {
          role: 'assistant',
          text: partialText ? `${partialText}\n\n（${reasonNote}）` : `请求失败：${reasonNote}`,
          reasoning,
          mode,
        }]);
        // 中断的文档不落草稿：清空实时预览，避免半成品被误当成已保存内容
        if (streamed?.doc) showToast('生成中断，本轮预览未更新', 'warning');
      }
      assistantAbort = null;
      setAssistantStream(null);
      setAssistantBusy(false);
    }
  }
}
