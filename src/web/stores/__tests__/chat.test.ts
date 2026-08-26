import { describe, it, expect, beforeEach } from 'vitest';

/**
 * chat store 流式状态机测试
 * 覆盖：start -> append -> finish / error / cancel
 */

// 直接测试 chatActions 的状态转换逻辑（不依赖 DOM）
// 由于 solid-js store 在 node 环境可用，直接 import
import { chatState, chatActions } from '../chat';
import { t } from '@/lib/locale';
// 「继续刚才的任务」建议派生用例已拆出至 chat-continue-suggestion.test.ts（控制本文件行数）
// 排队消息持久化用例已拆出至 chat-queue-persist.test.ts（任务 #21 行数门禁清偿）

describe('chatActions 流式状态机', () => {
  beforeEach(() => {
    // 重置状态
    chatActions.loadMessages([]);
    chatActions.setInput('');
  });

  it('startStream 设置流式状态', () => {
    chatActions.startStream();
    expect(chatState.isStreaming).toBe(true);
    expect(chatState.streamingText).toBe('');
    expect(chatState.turnLedger.statusText).toBe('正在连接…');
  });

  it('appendDelta 累积文本', () => {
    chatActions.startStream();
    chatActions.appendDelta('你好');
    chatActions.appendDelta('世界');
    expect(chatState.streamingText).toBe('你好世界');
    expect(chatState.turnLedger.statusText).toBe('正在回复…');
  });

  it('finishStream 将结果写入消息列表并清除流式状态', () => {
    chatActions.startStream();
    chatActions.appendDelta('回复内容');
    chatActions.finishStream({
      text: '最终回复',
      elapsed_ms: 1500,
      steps: 2,
      applied_actions: 1,
    });
    expect(chatState.isStreaming).toBe(false);
    expect(chatState.streamingText).toBe('');
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].sender).toBe('agent');
    expect(chatState.messages[0].text).toBe('最终回复');
    expect(chatState.messages[0].meta).toContain('1.5s');
    expect(chatState.messages[0].meta).toContain('2 轮');
  });

  it('finishStream meta 走 locale 字典', () => {
    // 键存在于字典：t 返回文案而非 key 本身（缺失时 t 回退 key，可检出）
    expect(t('rp.msg.metaTime', { s: '1.0' })).toBe('耗时 1.0s');
    expect(t('rp.msg.metaRounds', { n: 3 })).toBe('3 轮');
    expect(t('rp.msg.metaUpdated', { n: 2 })).toBe('更新 2 项');
    chatActions.startStream();
    chatActions.finishStream({ text: 'ok', elapsed_ms: 2000, steps: 3, applied_actions: 2 });
    expect(chatState.messages[0].meta).toBe('耗时 2.0s · 3 轮 · 更新 2 项');
  });

  it('finishStream 同轮消息共用 turnId（轮次容器）', () => {
    chatActions.startStream();
    chatActions.finishStream({
      text: '正文',
      elapsed_ms: 1000,
      steps: 1,
      applied_actions: 0,
      turn_id: 'turn-abc',
      documents_written: ['规格.md'],
      image_urls: ['img.png'],
    });
    // 正文 + 文档卡 + 图片卡三条同轮消息均携带同一 turnId
    expect(chatState.messages.length).toBe(3);
    chatState.messages.forEach((m) => {
      expect(m.sender).toBe('agent');
      expect(m.turnId).toBe('turn-abc');
    });
  });

  it('finishStream 落账幂等：同 turn_id 终态帧重复派发不双落（审查修复）', () => {
    chatActions.startStream();
    const payload = {
      text: '正文', elapsed_ms: 1000, steps: 1, applied_actions: 0,
      turn_id: 'turn-dup', documents_written: ['规格.md'],
    };
    chatActions.finishStream(payload);
    const afterFirst = chatState.messages.length; // 主气泡 + 文档卡
    expect(afterFirst).toBe(2);
    // 交错场景：同一 done 再次到达（replay/增量同源双达）不得重复落账
    chatActions.finishStream(payload);
    expect(chatState.messages.length).toBe(afterFirst);
    // 无 turn_id 的旧帧不受幂等约束（行为与修复前一致）
    chatActions.startStream();
    chatActions.finishStream({ text: '无 turnId', elapsed_ms: 100, steps: 1, applied_actions: 0 });
    chatActions.startStream();
    chatActions.finishStream({ text: '无 turnId', elapsed_ms: 100, steps: 1, applied_actions: 0 });
    expect(chatState.messages.length).toBe(afterFirst + 2);
  });

  it('streamError 写入错误消息并清除流式状态', () => {
    chatActions.startStream();
    chatActions.streamError({ code: 'err.network.timeout', kind: 'network', message: '网络超时' });
    expect(chatState.isStreaming).toBe(false);
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].text).toContain('网络超时');
  });

  it('streamError/cancelStream turn_id 幂等：同轮终态帧重复派发不双落（审查修复）', () => {
    chatActions.startStream();
    chatActions.docWritten('规格.md', 'turn-term'); // 流式中唯一 turn_id 打戳源
    chatActions.streamError({ code: 'err.network.timeout', kind: 'network', message: '网络超时' });
    const afterFirst = chatState.messages.length; // 文档卡 + 错误气泡
    // replay 错误与增量错误同源双达：守卫命中跳过
    chatActions.streamError({ code: 'err.network.timeout', kind: 'network', message: '网络超时' });
    expect(chatState.messages.length).toBe(afterFirst);
    // 同轮停止终态帧双达：同样命中守卫跳过
    chatActions.cancelStream();
    expect(chatState.messages.length).toBe(afterFirst);
  });

  it('cancelStream turn_id 幂等：停止气泡同轮不双落（迟到 stopped 帧防重）', () => {
    chatActions.startStream();
    chatActions.docWritten('规格.md', 'turn-stop');
    chatActions.cancelStream();
    const afterStop = chatState.messages.length;
    expect(chatState.messages[afterStop - 1].turnId).toBe('turn-stop');
    chatActions.cancelStream(); // 迟到 stopped 帧/replay 补落
    expect(chatState.messages.length).toBe(afterStop);
    // 无 turn 上下文（未打戳）时不受守卫约束，行为与修复前一致
    chatActions.startStream();
    chatActions.cancelStream();
    expect(chatState.messages.length).toBe(afterStop + 1);
  });

  it('cancelStream 保留已有流式文本为消息', () => {
    chatActions.startStream();
    chatActions.appendDelta('部分内容');
    chatActions.cancelStream();
    expect(chatState.isStreaming).toBe(false);
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].text).toBe('部分内容');
    // 有文本默认推导为输出阶段，meta 措辞为阶段文案
    expect(chatState.messages[0].meta).toBe('已在输出阶段停止');
  });

  // ---------- 端到端中断协议（任何中断都有痕迹、都有出口） ----------

  it('cancelStream 无文本时也产生停止气泡 + 继续建议（思考阶段）', () => {
    chatActions.startStream();
    chatActions.cancelStream();
    expect(chatState.isStreaming).toBe(false);
    // 不变式：无文本停止不得静默丢弃——落轻量系统气泡
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].text).toContain('已在思考阶段停止（未产生内容）');
    const acts = chatState.messages[0].suggestedActions;
    expect(acts).toHaveLength(1);
    expect(acts?.[0].kind).toBe('retry');
    expect(acts?.[0].label).toBe('继续刚才的任务');
  });

  it('cancelStream 阶段标记影响措辞（显式 phase 优先）', () => {
    // 工具执行阶段（无文本）
    chatActions.startStream();
    chatActions.cancelStream({ phase: 'tool_executing' });
    expect(chatState.messages[0].text).toContain('已在工具执行阶段停止（未产生内容）');
    chatActions.loadMessages([]);
    // 输出阶段（有文本）
    chatActions.startStream();
    chatActions.appendDelta('正文');
    chatActions.cancelStream({ phase: 'streaming' });
    expect(chatState.messages[0].meta).toBe('已在输出阶段停止');
  });

  it('cancelStream 携带在途外部生成任务登记时附提醒文案', () => {
    chatActions.startStream();
    chatActions.cancelStream({ inflight: [{ task_id: 'g1', media_type: 'image' }] });
    expect(chatState.messages[0].text).toContain('在供应商侧继续');
    expect(chatState.messages[0].text).toContain('本次停止不会撤销');
  });

  it('addMessage 追加用户消息', () => {
    chatActions.addMessage({ sender: 'user', text: '你好' });
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].sender).toBe('user');
  });

  it('loadMessages 替换全部消息', () => {
    chatActions.addMessage({ sender: 'user', text: '旧消息' });
    chatActions.loadMessages([{ sender: 'agent', text: '新消息' }]);
    expect(chatState.messages.length).toBe(1);
    expect(chatState.messages[0].text).toBe('新消息');
  });

  // ---------- ：docCard 双通道去重 ----------

  it('docWritten 即显后 finishStream 不重复渲染同名文档卡', () => {
    chatActions.startStream();
    chatActions.docWritten('大纲.md');
    chatActions.finishStream({
      text: '完成',
      elapsed_ms: 1000,
      steps: 1,
      applied_actions: 0,
      documents_written: ['大纲.md', '规格.md'],
    });
    const docs = chatState.messages.filter((m) => m.docCard);
    expect(docs.map((m) => m.docCard)).toEqual(['大纲.md', '规格.md']);
  });

  it('docWritten 同轮重复名称只渲染一次', () => {
    chatActions.startStream();
    chatActions.docWritten('大纲.md');
    chatActions.docWritten('大纲.md');
    expect(chatState.messages.filter((m) => m.docCard).length).toBe(1);
  });

  // ---------- ：非流式响应 documents_written 即显（通道补齐，§5.2） ----------

  it('applyNonStreamDocs 非流式响应文档卡即显：批内去重、批间按新轮次重新展示', () => {
    chatActions.applyNonStreamDocs(['规格.md', '规格.md']);
    let docs = chatState.messages.filter((m) => m.docCard);
    expect(docs.map((m) => m.docCard)).toEqual(['规格.md']);
    // 新一次响应 = 新轮次（与 startStream 每轮清零同语义），全量清单重新渲染
    chatActions.applyNonStreamDocs(['规格.md', '大纲.md']);
    docs = chatState.messages.filter((m) => m.docCard);
    expect(docs.map((m) => m.docCard)).toEqual(['规格.md', '规格.md', '大纲.md']);
  });

  it('applyNonStreamDocs 空清单/空名不产生消息', () => {
    chatActions.applyNonStreamDocs([]);
    chatActions.applyNonStreamDocs(['']);
    expect(chatState.messages.filter((m) => m.docCard).length).toBe(0);
  });
});
