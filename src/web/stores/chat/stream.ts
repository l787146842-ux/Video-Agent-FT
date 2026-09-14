/** Chat store · 流式会话域（任务 #11 三分拆）：流式生命周期内的临时态
 * （开始/进度/思考/工具/增量/状态/重连恢复/清空）；消息入库归 chat/messages.ts。
 */
import { produce } from 'solid-js/store';
import { t, type LocaleKey } from '@/lib/locale';
import { emptyLedger, ledgerFromLive, SYSTEM_NOTICE } from '@/lib/turn-ledger';
import { resetStreamFields } from '@/lib/stream-finalize';
import { setChatState, type TimelineToolEntry } from '../chat-core';

export const streamActions = {
  /** 流式开始 */
  startStream(modelName?: string) {
    setChatState(produce((s) => {
      s.isStreaming = true;
      s.streamingText = '';
      s.streamingModel = modelName || '';
      // 新轮账本：状态文案走 i18n 键，不硬编码中文
      s.turnLedger = emptyLedger(t('rp.streaming.connecting'));
      s.renderedDocCards = [];
      // 新轮开始：轮次上下文清零（由本轮 doc_written/done 重新建立）
      s.currentTurnId = undefined;
    }));
  },

  /** 追加深度思考（reasoning）增量（进本轮账本） */
  appendReasoning(text: string) {
    setChatState(produce((s) => {
      const led = s.turnLedger;
      if (!led.reasoningStartMs) led.reasoningStartMs = Date.now();
      // 结束时刻随每条增量推进（思考与工具执行交错，角标只算思考区间）
      led.reasoningEndMs = Date.now();
      led.reasoning += text;
      led.statusText = t('rp.streaming.reasoning');
    }));
  },

  /** 过程时间线：工具/操作开始（运行态条目进账本；args 为后端裁剪脱敏后的输入预览）。
   * 按 id upsert：存量同 id 条目就地更新（replay 与增量 tool_started 同源双达不双登） */
  toolStarted(id: string, name: string, summary: string, args?: Record<string, unknown>, detailMd?: string) {
    setChatState(produce((s) => {
      const existing = s.turnLedger.items.find((item) => item.id === id);
      if (existing) {
        existing.name = name;
        existing.summary = summary;
        existing.status = 'running';
        existing.started_at_ms = Date.now();
        existing.args = args;
        if (detailMd) existing.detail_md = detailMd;
      } else {
        const entry: TimelineToolEntry = {
          id, name, summary, status: 'running', started_at_ms: Date.now(), args,
        };
        if (detailMd) entry.detail_md = detailMd;
        s.turnLedger.items.push(entry);
      }
      // 状态文案走 i18n 键，不硬编码中文
      s.turnLedger.statusText = t('rp.streaming.executing', {
        n: s.turnLedger.items.length,
        summary: summary || name,
      });
    }));
  },

  /** 过程时间线：工具/操作完成（对勾/失败态；planning=规划级执行器标记） */
  toolFinished(id: string, ok: boolean, elapsedMs: number, resultSummary?: string, planning?: boolean, detailMd?: string) {
    setChatState(produce((s) => {
      // 参数名避开 i18n 惯用名 t，防止遮蔽外层 t 函数
      const entry = s.turnLedger.items.find((item) => item.id === id);
      if (entry) {
        entry.status = ok ? 'done' : 'failed';
        entry.elapsed_ms = elapsedMs;
        if (planning) entry.planning = true;
        entry.result_summary = resultSummary;
        if (detailMd) entry.detail_md = detailMd;
      }
    }));
  },

  /** 追加流式文本片段 */
  appendDelta(text: string) {
    setChatState('streamingText', (prev) => prev + text);
    setChatState('turnLedger', 'statusText', t('rp.streaming.replying'));
  },

  /** 设置状态提示 */
  setStatus(text: string) {
    setChatState('turnLedger', 'statusText', text);
  },

  /** 系统事实条目进本轮账本（假停机械续跑等机器判定事件）：statusText 只活到
   * 下一条 status 覆盖为止，而机器判定的事实需跨相位/刷新留痕，否则模型正文
   * 的自述就成了用户唯一可见的成果（文案走 noticeKind，本层不拼字面）。
   * id 幂等：同事件重复到达不双登（与 toolStarted upsert 同纪律）。 */
  systemNotice(
    id: string, noticeKind: LocaleKey, noticeParams?: Record<string, string | number>,
  ) {
    setChatState(produce((s) => {
      if (!id || s.turnLedger.items.some((item) => item.id === id)) return;
      s.turnLedger.items.push({
        id, name: SYSTEM_NOTICE, summary: '', status: 'done', noticeKind, noticeParams,
      });
    }));
  },

  /** 恢复流式状态（任务式传输重连：先回放服务端累计状态，再收实时增量）。
   * replay 快照经 ledgerFromLive 同一归一入口进账本（与 live 累积同模型） */
  restoreStreamingState(p: {
    reasoning?: string; text?: string; statusText?: string;
    tools?: TimelineToolEntry[]; model?: string;
  }) {
    setChatState(produce((s) => {
      s.isStreaming = true;
      s.streamingText = p.text || '';
      s.streamingModel = p.model || '';
      // 重连无原始思考起点：已有 reasoning 时以恢复时刻
      // 为起点继续计时（角标不再恒 0）——归一函数内统一处理
      s.turnLedger = ledgerFromLive({
        tools: p.tools || [],
        reasoning: p.reasoning || '',
        statusText: p.statusText || '',
      });
    }));
  },

  /** 清空流式状态（重连后发现任务已完成，直接收尾，不追加「已停止」消息） */
  clearStreaming() {
    // 重置语义与 done/错误/停止共用 lib/stream-finalize.resetStreamFields 单一实现
    setChatState(produce((s) => resetStreamFields(s)));
  },
};
