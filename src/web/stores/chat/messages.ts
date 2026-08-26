/** Chat store · 消息列表域（任务 #11 三分拆）：消息入库/截断/输入/收尾落盘/
 * 决策表单投影/文档卡片/历史加载；流式临时态归 stream.ts，排队归 queue.ts。 */
import { produce } from 'solid-js/store';
import type { ChatMessage, SseDonePayload, PendingDecisionPayload } from '@/types';
import { t } from '@/lib/locale';
import { actionForPayload, type ErrorPayload } from '@/lib/error-payload';
import {
  resetStreamFields, continueLastTaskSuggestion, buildStopMessages,
} from '@/lib/stream-finalize';
import type { StopPhase, StopInflightItem } from '@/lib/stream-finalize';
import { setChatState } from '../chat-core';
import { buildDoneMessage, isTurnSettled } from './done-message';
import { queueActions } from './queue';

export const messageActions = {
  addMessage(msg: ChatMessage) {
    setChatState('messages', (prev) => [...prev, { ...msg, ts: msg.ts ?? Date.now() }]);
  },

  /** 截断重答本地同步（与后端 truncate_chat_tail 同语义）：丢弃最后一条
   * 非系统动作用户消息之后的全部消息；text 非空时替换该消息正文。
   * 仅在 /chat/truncate-resend 成功后调用（旧回复消失，新任务流式接续）。 */
  truncateTailForResend(newText?: string) {
    setChatState('messages', (prev) => {
      let idx = -1;
      for (let i = prev.length - 1; i >= 0; i -= 1) {
        const m = prev[i];
        if (m.sender === 'user' && m.kind !== 'system_action') { idx = i; break; }
      }
      if (idx < 0) return prev;
      const next = prev.slice(0, idx + 1);
      const body = (newText || '').trim();
      // 替换正文时同步清 parts（与后端替换语义对齐：旧图文排版随重写作废）；
      // 纯重答路径（无 newText）不动
      if (body) next[idx] = { ...next[idx], text: body, parts: undefined };
      return next;
    });
  },

  setInput(text: string) {
    setChatState('inputText', text);
  },

  /** 流式完成：将结果写入消息列表。
   * 落账幂等键 = turn_id：特定交错下（终态帧在同解析循环内重复派发，
   * 如 replay done 与增量 done 同源双达）同 turnId 主气泡只落一次 */
  finishStream(payload: SseDonePayload) {
    // 深度思考耗时角标（末条 reasoning - 首条 reasoning；无思考时 0）
    setChatState(produce((s) => {
      // 同轮消息共用 turnId（渲染层聚合为轮次容器，消除碎片化）
      const turnId = payload.turn_id || undefined;
      // 幂等：同 turnId 的 done 主气泡（唯一携 meta 的消息）已落账则整体跳过
      if (turnId && s.messages.some(
        (m) => m.sender === 'agent' && m.turnId === turnId && m.meta !== undefined,
      )) return;
      // 当前轮 turn_id 打戳：终态收尾后保留，供错误/停止终态帧幂等守卫判重
      if (turnId) s.currentTurnId = turnId;
      const startMs = s.turnLedger.reasoningStartMs;
      const endMs = s.turnLedger.reasoningEndMs;
      const thinkingMs = startMs && endMs && endMs >= startMs ? endMs - startMs : 0;
      s.messages.push(buildDoneMessage(payload, thinkingMs, s.streamingModel, s.turnLedger));
      // 文档卡片（doc_written 即显过的按名称去重；服务端仍按 documents_written 全量落盘，刷新后由快照重建）
      (payload.documents_written || []).forEach((name) => {
        if (s.renderedDocCards.includes(name)) return;
        s.renderedDocCards.push(name);
        s.messages.push({ sender: 'agent', docCard: name, text: '', turnId, ts: Date.now() });
      });
      // 生图结果图片卡片
      if (payload.image_urls && payload.image_urls.length > 0) {
        s.messages.push({
          sender: 'agent',
          text: '',
          ts: Date.now(),
          imageCard: { image_urls: payload.image_urls },
          turnId,
        });
      }
      // 视频结果内联预览卡：done payload 的 chat_inserts 中 kind=video 项（带首帧 thumb）；输入框插入通道不变（use-sse 侧）
      const videoInserts = (payload.chat_inserts || [])
        .filter((it) => it.kind === 'video' && !!it.url);
      if (videoInserts.length > 0) {
        s.messages.push({
          sender: 'agent',
          text: '',
          ts: Date.now(),
          videoCard: {
            items: videoInserts.map((it) => ({
              url: it.url,
              name: it.name || undefined,
              thumb: it.thumb || undefined,
            })),
          },
          turnId,
        });
      }
      resetStreamFields(s);
    }));
  },

  /** 流式错误：输入为结构化 ErrorPayload，affordance 按完整负载解析
   *  （code 覆盖优先于 kind 映射；不做正则猜文案）；会话中已有用户消息时派生「继续刚才的任务」 */
  streamError(payload: ErrorPayload) {
    const action = actionForPayload(payload);
    setChatState(produce((s) => {
      // turn_id 幂等守卫：同轮已落终态气泡（done meta/错误/停止）则跳过，
      // 防 replay 错误与增量错误同源双达重复落泡
      const turnId = s.currentTurnId || undefined;
      if (turnId && s.messages.some((m) => m.turnId === turnId && isTurnSettled(m))) return;
      // affordance 由 actionForPayload 映射表集中决定（人话在气泡，raw 在折叠）
      s.messages.push({
        sender: 'agent', text: `⚠️ ${payload.message}`, modelName: s.streamingModel || undefined,
        ts: Date.now(),
        settingsHint: !!action.settingsHint,
        errorKind: payload.kind,
        errorDetail: payload.raw || undefined,
        suggestedActions: s.messages.some((m) => m.sender === 'user') ? continueLastTaskSuggestion() : undefined,
        turnId,
      });
      resetStreamFields(s);
    }));
  },

  /** 清空流式状态（用户手动停止）。停止后不纯丢弃：停止气泡本地派生
   * 「继续刚才的任务」建议（kind=retry 即点击走机械重发）。中断不变式：
   * 任何中断都有痕迹、都有出口（无文本也落轻量气泡；inflight 附提醒）。 */
  cancelStream(opts?: {
    /** 停止阶段（stopped 事件/停止响应下发；缺省按本地流状态推导） */
    phase?: StopPhase;
    /** 在途外部生成任务登记（后端 /stop 响应或 stopped 事件携带） */
    inflight?: StopInflightItem[];
  }) {
    setChatState(produce((s) => {
      // turn_id 幂等守卫：同轮已落终态气泡则跳过（本地停止后迟到 stopped 帧/
      // replay stopped 补落不再重复产生停止气泡）
      const turnId = s.currentTurnId || undefined;
      if (turnId && s.messages.some((m) => m.turnId === turnId && isTurnSettled(m))) return;
      // 停止气泡构造归 lib/stream-finalize.buildStopMessages
      // （不变式：无文本停止也落轻量气泡 + 继续建议）
      const stopMessages = buildStopMessages({
        phase: opts?.phase, inflight: opts?.inflight,
        text: s.streamingText, model: s.streamingModel,
        hasRunningTool: s.turnLedger.items.some((item) => item.status === 'running'),
      });
      if (turnId) stopMessages.forEach((m) => { m.turnId = turnId; });
      s.messages.push(...stopMessages);
      resetStreamFields(s);
    }));
  },

  /** 结构化决策表单投影（replay 重建通道）。把 pending_decision_payload
   * 挂到最近一条待回应 agent 暂停消息；无载体时派生轻量卡消息。
   * token 幂等守卫：重连/重放 replay 不重复挂卡；不跨用户消息向前附挂
   * （用户已回应后旧决策不再复活）。 */
  applyDecisionForm(payload: PendingDecisionPayload) {
    const hasBody = Boolean(payload.token) || (payload.schema?.fields || []).length > 0;
    if (!hasBody) return;
    setChatState(produce((s) => {
      // 幂等（同一 some()）：同 token 已在列表，或空 token 时以
      // 「schema 首字段 key + 问句」组合判重（重连 replay 同源重建不双挂）
      const firstKey = (payload.schema?.fields || [])[0]?.key || '';
      if (s.messages.some((m) => {
        const df = m.decisionForm;
        if (!df) return false;
        if (payload.token) return df.token === payload.token;
        return !!firstKey
          && (df.schema?.fields || [])[0]?.key === firstKey
          && (df.message || '') === (payload.message || '');
      })) return;
      for (let i = s.messages.length - 1; i >= 0; i -= 1) {
        const m = s.messages[i];
        if (m.sender === 'user') break;
        if (m.sender === 'agent' && (m.confirm || m.kind) && !m.decisionForm) {
          m.decisionForm = payload;
          return;
        }
      }
      // 无载体：派生独立卡消息（confirm 取决策问句供阶段卡展示；
      // 交互面由 DecisionFormCard 接管，ConfirmActions 遇 decisionForm 让位）
      s.messages.push({
        sender: 'agent', text: '', ts: Date.now(),
        decisionForm: payload,
        confirm: payload.message || t('rp.decision.defaultTitle'),
      });
    }));
  },

  /** 文档写入即显（doc_written 事件）：独立文档卡片立即渲染，
   * 不等整轮 done；同轮重复名称去重（done 全量清单与事件双通道防双显）。
   * 携带后端透传层打戳的 turn_id，即显卡严格归入轮次容器 */
  docWritten(name: string, turnId?: string) {
    if (!name) return;
    setChatState(produce((s) => {
      // 流式中 turn_id 唯一打戳源：建立当前轮标识供终态幂等守卫
      if (turnId) s.currentTurnId = turnId;
      if (s.renderedDocCards.includes(name)) return;
      s.renderedDocCards.push(name);
      s.messages.push({ sender: 'agent', text: '', docCard: name, turnId, ts: Date.now() });
    }));
  },

  /** 非流式响应 documents_written 即显（与流式通道对齐，不留半截通道）：
   * 后端非流式载荷携带文档清单时前端同样渲染卡片；非流式无流式轮边界，
   * 先重置「本轮已显」去重表（与 startStream 每轮清零同语义）再按清单渲染 */
  applyNonStreamDocs(names: string[]) {
    if (!names || !names.length) return;
    setChatState(produce((s) => {
      s.renderedDocCards = [];
      names.forEach((name) => {
        if (!name || s.renderedDocCards.includes(name)) return;
        s.renderedDocCards.push(name);
        s.messages.push({ sender: 'agent', text: '', docCard: name, ts: Date.now() });
      });
    }));
  },

  /** 从后端加载历史消息 */
  loadMessages(msgs: ChatMessage[]) {
    setChatState('messages', msgs);
    // 历史重建视同新轮次展示，去重表同步清零（防切项目/刷新后残留误去重）
    setChatState('renderedDocCards', []);
    // 轮次上下文随会话切换清零（新轮由 startStream/doc_written 重新建立）
    setChatState('currentTurnId', undefined);
    // 按当前项目+对话键恢复排队消息（刷新存活）
    queueActions.restoreQueue();
  },
};
