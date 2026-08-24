/**
 * 流式收尾四处复用点一致性测试（E-2 前置：改消息数据源前钉住现行为）。
 *
 * done（finishStream）/ 错误（streamError）/ 停止（cancelStream）/
 * 重连收尾（restoreStreamingState + clearStreaming）四处复用
 * lib/stream-finalize.resetStreamFields 同一语义。本文件从 chatActions
 * 入口钉死四处收尾后的统一后置态：流式字段清零、忙态复位，
 * 且各自的痕迹消息按既有形态落库（重连已完成收尾除外）。
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { chatState, chatActions } from '../chat';
import type { ChatState } from '@/stores/chat';

/** 收尾后统一后置态断言（四处共用）：流式累积字段一律清零
 *（F2 阶段一：流式临时态已并入轮次账本，复位即账本原子清零） */
function expectStreamReset(s: ChatState) {
  expect(s.isStreaming).toBe(false);
  expect(s.streamingText).toBe('');
  expect(s.streamingModel).toBe('');
  expect(s.turnLedger.reasoning).toBe('');
  expect(s.turnLedger.items).toEqual([]);
  expect(s.turnLedger.statusText).toBe('');
  expect(s.turnLedger.reasoningStartMs).toBe(0);
  expect(s.roundStep).toBe(0);
  expect(s.roundMax).toBe(0);
}

/** 模拟流式进行中的中途状态（思考 + 工具 + 正文增量） */
function midStream() {
  chatActions.startStream('模型A');
  chatActions.appendReasoning('思考中');
  chatActions.toolStarted('t1', 'gen', '生图');
  chatActions.appendDelta('正文片段');
  chatActions.setRoundProgress(2, 5);
}

describe('四处收尾复用点后置态一致', () => {
  beforeEach(() => {
    chatActions.loadMessages([]);
    chatActions.clearStreaming();
  });

  it('done 收尾：结果消息落库 + 流式字段清零；本轮账本相位翻转随消息入库', () => {
    midStream();
    chatActions.finishStream({ text: '最终回复', elapsed_ms: 900, steps: 1, applied_actions: 0 });
    expectStreamReset(chatState);
    expect(chatState.messages).toHaveLength(1);
    expect(chatState.messages[0].text).toBe('最终回复');
    // 相位翻转：消息携带同一批 live 账目（settled），不从 trace 二次重建
    const led = chatState.messages[0].ledger;
    expect(led?.phase).toBe('settled');
    expect(led?.items).toHaveLength(1);
    expect(led?.items[0].summary).toBe('生图');
    expect(led?.items[0].status).toBe('done');
    expect(led?.reasoning).toBe('思考中');
  });

  it('错误收尾：错误气泡落库（带 errorKind）+ 流式字段清零', () => {
    midStream();
    chatActions.streamError({ code: 'err.network.timeout', kind: 'network', message: '网络超时' });
    expectStreamReset(chatState);
    expect(chatState.messages).toHaveLength(1);
    expect(chatState.messages[0].errorKind).toBe('network');
    expect(chatState.messages[0].text).toContain('网络超时');
  });

  it('停止收尾：停止气泡落库（带继续建议）+ 流式字段清零', () => {
    midStream();
    chatActions.cancelStream({ phase: 'streaming' });
    expectStreamReset(chatState);
    expect(chatState.messages).toHaveLength(1);
    expect(chatState.messages[0].text).toBe('正文片段');
    expect(chatState.messages[0].suggestedActions).toHaveLength(1);
  });

  it('重连收尾：restoreStreamingState 回放累计态 → 发现已完成时 clearStreaming 静默清零（不落消息）', () => {
    chatActions.restoreStreamingState({
      reasoning: '服务端累计思考', text: '服务端累计正文', statusText: '恢复中',
      tools: [{ id: 't1', name: 'gen', summary: '生图', status: 'running' }], model: '模型A',
    });
    expect(chatState.isStreaming).toBe(true);
    expect(chatState.streamingText).toBe('服务端累计正文');
    chatActions.clearStreaming();
    expectStreamReset(chatState);
    // 重连发现任务已完成：直接收尾，不追加「已停止」消息
    expect(chatState.messages).toHaveLength(0);
  });
});
