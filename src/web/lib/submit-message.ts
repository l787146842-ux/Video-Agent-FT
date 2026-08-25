/**
 * 发送路径统一入口。
 *
 * 此前四条并行「发消息」路径各自携带序列化/校验/排队判定的变体：
 * - sendUserMessage@lib/agent-actions.ts（新消息）
 * - resendNearestUserMessage@lib/chat/resend.ts（机械重发）
 * - sendGuidanceToTask 引导登记@QueuedMessagesBar（轮间注入）
 * - 排队自动出队@lib/chat/chat-queue-autosend.ts
 *
 * 本模块是唯一收口：序列化（normalizeParts）/ 校验（内容、供应商模型）/
 * 排队判定（agentBusy 入队 + 引导登记 / queued 失败回队）单点实现；
 * 四路径都以 intent 调用本入口，行为差异只体现在 intent 分支。
 */
import { state, studioActions } from '@/stores/studio';
import { chatState, chatActions, type QueuedMessage } from '@/stores/chat';
import { showToast } from '@/stores/toast';
import { streamAgentChat, sendGuidanceToTask } from '@/hooks/use-sse';
import {
  agentProvider, agentModel, agentSkill, agentAssetMode, agentThinkingLevel,
} from '@/stores/agent-prefs';
import { CHAT_HISTORY_WINDOW, uid } from '@/lib/utils';
import { partsToPlainText } from '@/lib/rich-input';
import { t } from '@/lib/locale';
import type { AgentChatRequest, AnyGroup, MediaType, RichContentPart } from '@/types';

/** 发送意图：新消息 / 机械重发 / 引导注入 / 排队出队 */
export type SubmitIntent = 'new' | 'resend' | 'guidance' | 'queued';

/** 统一发送负载 */
export interface SubmitPayload {
  /** 正文：纯文本或有序富文本片段（文字与内联缩略图交错） */
  input: string | RichContentPart[];
  /** 会话层一次性闸机豁免（「本次放行」） */
  gateOverrides?: string[];
  /** 暂停回应结构化回携（对标 AskUserQuestion） */
  pauseResponse?: { pause_id: string; value: string; label?: string };
  /** 系统动作标记（如「本次放行」留痕，渲染为系统动作行） */
  systemAction?: 'system_action';
  /** queued/guidance 意图的原排队条目：
   *  queued 失败回队保留原 id 与顺序；guidance 移队首并登记轮间注入 */
  queuedEntry?: QueuedMessage;
}

/**
 * Agent 可调取的素材 = 故事板全部草稿卡（关键元素/分镜/音频）中已有媒体的 URL。
 * 未归类素材（state.assets）不参与上下文——它是从故事板移除的素材，agent 不可调取。
 * 请求体瘦身：按「选中草稿优先」排序并封顶（图 9、视频/音频 10）。
 */
function selectedAssetUrls(kind: MediaType): string[] {
  const urls: string[] = [];
  const boards: AnyGroup[][] = [state.keyElements, state.shots, state.audioItems];
  for (const groups of boards) {
    for (const g of groups) {
      for (const d of g.drafts || []) {
        const url = kind === 'image' ? d.imgUrl : kind === 'video' ? d.videoUrl : d.audioUrl;
        if (url) {
          if (d.id === state.selectedDraftId) urls.unshift(url);
          else urls.push(url);
        }
      }
    }
  }
  return urls.slice(0, kind === 'image' ? 9 : 10);
}

/** 规范化 parts（序列化单点）：字符串 → 单个 text 片段；丢弃空 text 片段 */
export function normalizeParts(input: string | RichContentPart[]): RichContentPart[] {
  if (typeof input === 'string') {
    const trimmed = input.trim();
    return trimmed ? [{ type: 'text', text: input }] : [];
  }
  return input.filter((p) => (p.type === 'text' ? p.text.trim().length > 0 : !!p.url));
}

/** queued 意图校验失败：原条目放回队首，消息不丢（对齐 B0/F60 语义） */
function requeueAtFront(entry: QueuedMessage): void {
  chatActions.enqueueMessage(entry);
  chatActions.moveQueuedToFront(entry.id);
}

/**
 * 统一发送入口。返回 true = 已受理发送或已入队（调用方可据此清空输入框）；
 * false = 被拦截（内容为空 / 未选供应商模型）。
 *
 * intent 差异（其余流程四路径完全一致）：
 * - new：普通新消息。
 * - resend：机械重发（重跑 = 原内容含富文本附件，零模型猜测）；语义标记，
 *   便于追踪与日后差异化（如跳过历史窗口）。
 * - guidance：不新建任务——把排队条目移到队首并登记到运行中任务的轮间
 *   注入队列；注入成功由 guidance_injected 事件上屏出队，任务已结束则
 *   保留队首回落自动出队。
 * - queued：排队出队重发；校验被拦截时原条目回队首不丢失。
 */
export async function submitMessage(intent: SubmitIntent, payload: SubmitPayload): Promise<boolean> {
  // guidance：注入时机是「运行中任务的轮边界」，只登记不打断，不走序列化/建任务
  if (intent === 'guidance') {
    const entry = payload.queuedEntry;
    if (!entry) return false;
    chatActions.moveQueuedToFront(entry.id);
    sendGuidanceToTask(entry.id, entry.text);
    return true;
  }

  const parts = normalizeParts(payload.input);
  const mediaParts = parts.filter((p) => p.type !== 'text') as Array<
    Extract<RichContentPart, { type: 'image' | 'video' | 'audio' }>
  >;
  const docAttachments = state.pendingAttachments;
  const hasContent = parts.length > 0 || docAttachments.length > 0;
  if (!hasContent) {
    if (intent === 'queued' && payload.queuedEntry) requeueAtFront(payload.queuedEntry);
    return false;
  }

  const provider = agentProvider();
  const model = agentModel();
  if (!provider || !model) {
    showToast(t('rp.send.noProvider'), 'warning');
    if (intent === 'queued' && payload.queuedEntry) requeueAtFront(payload.queuedEntry);
    return false;
  }

  const skill = agentSkill();

  // 纯文本正文：媒体以 [图片:名称] 占位符保留位置（message 字段 / 历史 / mock 用）
  const message = partsToPlainText(parts).trim() || '请查看我上传的素材';

  // 文档/Skill 引用块：发送后才真正附加，消息里以可点击的块状展示（不再拼纯文本前缀）
  const docBlocks = docAttachments.map((a) => a.name);

  // Agent 推理中：不阻断用户，消息进入排队引导区，当前任务完成后自动发送
  if (state.agentBusy) {
    // 暂停回应不入队：pause_response 只对当前活动暂停有意义，
    // 排队重发会在任务结束后把同一回答再发一遍（连点双发断点）；直接拒收提示
    if (payload.pauseResponse) {
      showToast(t('rp.queue.pauseRejected'), 'warning');
      return false;
    }
    // queued 意图复用原条目（保留 id 与顺序）；其余意图新建条目
    const entry = intent === 'queued' && payload.queuedEntry
      ? payload.queuedEntry
      : {
        id: uid('q'),
        text: message,
        displayText: docBlocks.length ? `${message}（附件：${docBlocks.join('、')}）` : message,
        parts,
      };
    chatActions.enqueueMessage(entry);
    chatActions.setInput('');
    // 同时登记到服务端运行中任务，轮间注入成功即渲染用户气泡并出队；
    // 任务已结束则回落「任务完成后自动出队重发」
    sendGuidanceToTask(entry.id, message);
    showToast(t('rp.queue.enqueued'), 'info');
    return true;
  }

  // 附件 = 内联媒体（供后端 bind）+ 文档 chips
  const attachments = [
    ...mediaParts.map((p) => ({
      id: uid('att'),
      name: p.name,
      url: p.url,
      kind: p.type,
    })),
    ...docAttachments.map((a) => ({
      id: a.id,
      name: a.name,
      url: a.url,
      kind: a.type,
    })),
  ];

  // 历史（发送前的最近 N 条）
  const history = chatState.messages.slice(-CHAT_HISTORY_WINDOW).map((m) => ({
    role: m.sender === 'agent' || m.sender === 'assistant' ? 'assistant' : 'user',
    content: m.text,
  }));

  // Skill 写入文档：仅当消息中携带了 Skill 引用块（名称在消息里）时才登记。
  let skillSlug = '';
  if (skill && skill.name && message.includes(skill.name) && skill.id.startsWith('doc:')) {
    skillSlug = skill.id.slice(4);
    studioActions.markSkillUsed(skillSlug);
  }
  const skillBlocks = skillSlug ? [skill!.name] : [];

  chatActions.addMessage({
    sender: 'user', text: message, parts,
    docBlocks: docBlocks.length ? docBlocks : undefined,
    skillBlocks: skillBlocks.length ? skillBlocks : undefined,
    // 系统动作（如「本次放行」）不占用户气泡形态，渲染为系统动作行
    kind: payload.systemAction || undefined,
  });
  chatActions.setInput('');
  studioActions.setPendingAttachments([]);

  const request: AgentChatRequest = {
    message,
    // 幂等键：后端同 id 处理中时拒绝重复提交（防断连重发/双标签页重复落盘）
    request_id: uid('req'),
    provider,
    model,
    ms_model: provider === 'modelscope' ? model : '',
    messages: history,
    images: selectedAssetUrls('image'),
    videos: selectedAssetUrls('video'),
    selected_draft_id: state.selectedDraftId || '',
    selected_type: state.selectedType || '',
    asset_mode: agentAssetMode(),
    context_mode: 'studio',
    attachments,
    content_parts: parts,
    skill_slug: skillSlug,
    // 渐进式披露：后端只注入 Skill 目录，选中项仅作相关性标注
    skill_name: skill?.name || '',
    // 引用块随消息持久化，刷新后气泡里的文档/Skill 块可重建
    doc_blocks: docBlocks,
    skill_blocks: skillBlocks,
    // 会话层一次性闸机豁免：「本次放行」按钮携带，后端单次消费即清除
    ...(payload.gateOverrides?.length ? { gate_overrides: payload.gateOverrides } : {}),
    // 暂停回应结构化回携：后端与 active_pause 匹配后落 pauseAnsweredId/Value 标记
    ...(payload.pauseResponse ? { pause_response: payload.pauseResponse } : {}),
    // 系统动作标记：后端随用户消息持久化 kind，刷新后仍可重建系统动作行
    ...(payload.systemAction ? { system_action: payload.systemAction } : {}),
    // 会话级推理档位（''=默认/模型原生）
    thinking_level: agentThinkingLevel(),
  };

  // 即发即返：不阻塞等待整个推理流结束，输入框发送后立即清空；
  // 流的错误/结果由 streamAgentChat 内部处理（失败也会落为错误消息）
  void streamAgentChat(request);
  return true;
}
