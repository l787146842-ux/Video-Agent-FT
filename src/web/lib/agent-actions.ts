/**
 * Agent 消息发送高层封装
 * 从 stores 收集上下文（供应商/模型/技能/附件/选中草稿/历史），
 * 对齐旧 chat-streaming.ts 的 sendAgentMessage 行为。
 */
import { state, studioActions } from '@/stores/studio';
import { chatState, chatActions } from '@/stores/chat';
import { showToast } from '@/stores/toast';
import { streamAgentChat } from '@/hooks/use-sse';
import {
  agentProvider, agentModel, agentSkill, agentAssetMode,
} from '@/stores/agent-prefs';
import { CHAT_HISTORY_WINDOW, uid } from '@/lib/utils';
import { partsToPlainText } from '@/lib/rich-input';
import type { AgentChatRequest, AnyGroup, MediaType, RichContentPart } from '@/types';

/**
 * Agent 可调取的素材 = 故事板全部草稿卡（关键元素/分镜/音频）中已有媒体的 URL。
 * 未归类素材（state.assets）不参与上下文——它是从故事板移除的素材，agent 不可调取。
 */
function selectedAssetUrls(kind: MediaType): string[] {
  const urls: string[] = [];
  const boards: AnyGroup[][] = [state.keyElements, state.shots, state.audioItems];
  for (const groups of boards) {
    for (const g of groups) {
      for (const d of g.drafts || []) {
        const url = kind === 'image' ? d.imgUrl : kind === 'video' ? d.videoUrl : d.audioUrl;
        if (url) urls.push(url);
      }
    }
  }
  return urls;
}

/** 规范化 parts：字符串 → 单个 text 片段；丢弃空 text 片段 */
function normalizeParts(input: string | RichContentPart[]): RichContentPart[] {
  if (typeof input === 'string') {
    const t = input.trim();
    return t ? [{ type: 'text', text: input }] : [];
  }
  return input.filter((p) => (p.type === 'text' ? p.text.trim().length > 0 : !!p.url));
}

/**
 * 发送用户消息给 Agent（SSE 流式）
 * 供聊天输入框与左侧面板微调按钮共用。
 *
 * 入参可为：
 * - string：纯文本（微调按钮 / 确认按钮等纯文字场景）
 * - RichContentPart[]：有序富文本（文字与内联缩略图交错，来自富文本输入框）
 *
 * 返回 true 表示消息已受理发送或已入队（调用方可据此清空输入框）；
 * false 表示被拦截（内容为空 / 未选供应商模型）。
 *
 * Agent 忙碌（推理中）时不拦截：消息进入排队引导区（输入框顶部），
 * 当前任务完成后由 ChatInput 的自动出队逻辑按序发出。
 */
export async function sendUserMessage(
  input: string | RichContentPart[],
  opts?: { gateOverrides?: string[] },
): Promise<boolean> {
  const parts = normalizeParts(input);
  const mediaParts = parts.filter((p) => p.type !== 'text') as Array<
    Extract<RichContentPart, { type: 'image' | 'video' | 'audio' }>
  >;
  const docAttachments = state.pendingAttachments;
  const hasContent = parts.length > 0 || docAttachments.length > 0;
  if (!hasContent) return false;

  const provider = agentProvider();
  const model = agentModel();
  if (!provider || !model) {
    showToast('请先选择 Agent API 和对应模型', 'warning');
    return false;
  }

  const skill = agentSkill();

  // 纯文本正文：媒体以 [图片:名称] 占位符保留位置（message 字段 / 历史 / mock 用）
  const message = partsToPlainText(parts).trim() || '请查看我上传的素材';

  // 文档/Skill 引用块：发送后才真正附加，消息里以可点击的块状展示（不再拼纯文本前缀）
  const docBlocks = docAttachments.map((a) => a.name);

  // Agent 推理中：不阻断用户，消息进入排队引导区，当前任务完成后自动发送
  if (state.agentBusy) {
    const queuedDisplay = docBlocks.length
      ? `${message}（附件：${docBlocks.join('、')}）`
      : message;
    chatActions.enqueueMessage({ id: uid('q'), text: message, displayText: queuedDisplay, parts });
    chatActions.setInput('');
    showToast('已加入排队，Agent 完成当前任务后自动发送（可点「引导」立即接管）', 'info');
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
  // slug 随请求发给后端记入项目 usedSkills（新建项目为空），前端乐观更新；
  // 不自动弹出文档面板（发送后停留在对话页，用户可手动打开）。
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
    // 会话层一次性闸机豁免（814F7）：「本次放行」按钮携带，后端单次消费即清除
    ...(opts?.gateOverrides?.length ? { gate_overrides: opts.gateOverrides } : {}),
  };

  // 即发即返：不阻塞等待整个推理流结束，输入框（含 Skill/媒体块）发送后立即清空；
  // 流的错误/结果由 streamAgentChat 内部处理（失败也会落为错误消息）
  void streamAgentChat(request);
  return true;
}
