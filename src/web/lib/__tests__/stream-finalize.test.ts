/**
 * stream-finalize 纯函数回归防护（E-2 前置：改消息数据源前钉住现行为）。
 *
 * lib/stream-finalize.ts 是流式收尾的单一实现，供 done/错误/停止/重连
 * 四处收尾复用（chatActions.finishStream / streamError / cancelStream /
 * clearStreaming 均经 resetStreamFields 收口）。本文件钉死：
 * 1. resetStreamFields 的重置面（哪些字段清零、哪些字段不得触碰）；
 * 2. buildStopMessages 的停止气泡构造不变式（任何中断都有痕迹、都有出口）；
 * 3. continueLastTaskSuggestion 的派生形态（kind=retry 机械重发通道）。
 */
import { describe, it, expect } from 'vitest';
import {
  resetStreamFields, continueLastTaskSuggestion, buildStopMessages,
} from '@/lib/stream-finalize';
import type { ChatState } from '@/stores/chat';

/** 构造一个「流式进行中」的完整 ChatState（镜像 stores/chat defaultChatState） */
function streamingState(extra?: Partial<ChatState>): ChatState {
  return {
    messages: [{ sender: 'user', text: '旧消息', ts: 1 }],
    streamingText: '累积正文',
    isStreaming: true,
    inputText: '输入框内容',
    streamingModel: '模型A',
    // F2 阶段一：流式临时态已并入轮次账本（phase=live）
    turnLedger: {
      phase: 'live',
      turnId: undefined,
      reasoning: '累积思考',
      items: [{ id: 't1', name: 'gen', summary: '生图', status: 'running' }],
      statusText: '正在回复…',
      reasoningStartMs: 1000,
      reasoningEndMs: 2000,
      thinkingMs: undefined,
    },
    queuedMessages: [{ id: 'q1', text: '排队', displayText: '排队', parts: [] }],
    renderedDocCards: ['规格.md'],
    ...extra,
  };
}

describe('resetStreamFields（done/错误/停止/重连收尾四处同语义）', () => {
  it('清零全部流式累积字段（含本轮账本整体复位）', () => {
    const s = streamingState();
    resetStreamFields(s);
    expect(s.isStreaming).toBe(false);
    expect(s.streamingText).toBe('');
    expect(s.streamingModel).toBe('');
    // 账本原子复位：reasoning/items/状态文案/思考计时一次清零
    expect(s.turnLedger.reasoning).toBe('');
    expect(s.turnLedger.items).toEqual([]);
    expect(s.turnLedger.statusText).toBe('');
    expect(s.turnLedger.reasoningStartMs).toBe(0);
    expect(s.turnLedger.reasoningEndMs).toBe(0);
  });

  it('不触碰消息列表/输入框/排队/文档去重表（收尾重置面钉死，防误扩面）', () => {
    const s = streamingState();
    resetStreamFields(s);
    expect(s.messages).toHaveLength(1);
    expect(s.inputText).toBe('输入框内容');
    expect(s.queuedMessages).toHaveLength(1);
    expect(s.renderedDocCards).toEqual(['规格.md']);
  });

  it('重复调用幂等（重连多次收尾不漂移）', () => {
    const s = streamingState();
    resetStreamFields(s);
    const once = { ...s };
    resetStreamFields(s);
    expect(s).toEqual(once);
  });
});

describe('continueLastTaskSuggestion（停止/报错气泡共用派生）', () => {
  it('恒为单项 retry 建议（点击走机械重发通道）', () => {
    const acts = continueLastTaskSuggestion();
    expect(acts).toHaveLength(1);
    expect(acts[0].kind).toBe('retry');
    expect(acts[0].label).toBe('继续刚才的任务');
    expect(acts[0].value).toBe('');
  });
});

describe('buildStopMessages（不变式：任何中断都有痕迹、都有出口）', () => {
  it('有文本停止：正文落气泡 + meta 阶段标记 + 继续建议', () => {
    const msgs = buildStopMessages({ text: '半截正文', model: '模型A', hasRunningTool: false });
    expect(msgs).toHaveLength(1);
    expect(msgs[0].text).toBe('半截正文');
    expect(msgs[0].meta).toBe('已在输出阶段停止');
    expect(msgs[0].modelName).toBe('模型A');
    expect(msgs[0].suggestedActions).toHaveLength(1);
  });

  it('无文本停止（思考阶段）：轻量系统气泡，痕迹不缺席', () => {
    const msgs = buildStopMessages({ text: '', model: '', hasRunningTool: false });
    expect(msgs).toHaveLength(1);
    expect(msgs[0].text).toContain('已在思考阶段停止（未产生内容）');
    expect(msgs[0].modelName).toBeUndefined();
    expect(msgs[0].suggestedActions).toHaveLength(1);
  });

  it('阶段推导：无显式 phase 时按本地流状态推断（有运行中工具=工具执行阶段）', () => {
    const msgs = buildStopMessages({ text: '', model: '', hasRunningTool: true });
    expect(msgs[0].text).toContain('已在工具执行阶段停止（未产生内容）');
  });

  it('显式 phase 优先于推导（有文本也按阶段键取措辞）', () => {
    // 现行为钉死：thinking 阶段键带「未产生内容」后缀（与无文本通道共用同一 locale 键）
    const msgs = buildStopMessages({ phase: 'thinking', text: '正文', model: '', hasRunningTool: false });
    expect(msgs[0].meta).toBe('已在思考阶段停止（未产生内容）');
    const tool = buildStopMessages({ phase: 'tool_executing', text: '正文', model: '', hasRunningTool: false });
    expect(tool[0].meta).toBe('已在工具执行阶段停止');
    const stream = buildStopMessages({ phase: 'streaming', text: '正文', model: '', hasRunningTool: false });
    expect(stream[0].meta).toBe('已在输出阶段停止');
  });

  it('在途外部生成任务登记：附「供应商侧继续/不撤销」提醒（有文本进 meta，无文本进正文）', () => {
    const inflight = [{ task_id: 'g1', media_type: 'image' }];
    const withText = buildStopMessages({ text: '正文', model: '', hasRunningTool: false, inflight });
    expect(withText[0].meta).toContain('在供应商侧继续');
    expect(withText[0].meta).toContain('本次停止不会撤销');
    const noText = buildStopMessages({ text: '', model: '', hasRunningTool: false, inflight });
    expect(noText[0].text).toContain('在供应商侧继续');
  });
});
