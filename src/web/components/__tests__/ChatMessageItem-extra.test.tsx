/**
 * ChatMessageItem 渲染分支与 hover 动作补强。
 * 主交互契约见 ChatMessageItem.test.tsx（前端 250 行红线拆分）。
 *
 * 钉死契约：
 * ① 卡片/跳转/折叠分支：docCard 开文档面板、settingsHint 跳 /settings、
 *    errorDetail 技术详情折叠、hideChrome 轮次容器去重、system_action 行；
 * ② 用户气泡：纯 Skill 唤起同名隐藏正文；已回应暂停卡「当时所选」对勾；
 * ③ 复制/存为文档 hover 动作与 in-flight 双击守卫；
 * ④ 过程时间线数据源（F2 账本消费面）：翻转账本优先/空账本回落重建。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ChatMessageItem } from '../right-panel/ChatMessageItem';
import type { MessageAffordance } from '@/lib/message-affordances';
import type { ChatMessage } from '@/types';

// 本测试不触路由：useNavigate 以记录式跳转桩替代（避免 Router 上下文依赖）
const navigateMock = vi.fn();
vi.mock('@solidjs/router', () => ({ useNavigate: () => navigateMock }));

vi.mock('@/lib/agent-actions', () => ({
  sendUserMessage: () => Promise.resolve(true),
}));

// hover 动作副作用面桩：复制/存文档/toast 不发真实请求
const copyMock = vi.fn(async (_text: string) => true);
vi.mock('@/lib/code-copy', () => ({
  copyText: (text: string) => copyMock(text),
  handleCodeBlockClick: vi.fn(async () => {}),
}));
const openDocsPanelMock = vi.fn();
const saveDocMock = vi.fn(async (_text: string) => {});
vi.mock('@/stores/docs', () => ({
  openDocsPanel: (doc: string) => openDocsPanelMock(doc),
  saveMessageAsDoc: (text: string) => saveDocMock(text),
}));
const toastMock = vi.fn();
vi.mock('@/stores/toast', () => ({
  showToast: (msg: string, kind?: string) => toastMock(msg, kind),
  dismissToast: vi.fn(),
}));

/** affordance 对象构造器：默认全不挂，按需覆写（替代散落布尔 props） */
const AFF_DEFAULT: MessageAffordance = {
  confirmTarget: false, gateTarget: false, suggestedTarget: false,
  editable: false, regenerable: false, branchable: false, copyable: false,
  docSavable: false, confirmState: 'none', answeredValue: '',
    pauseQa: [],
};
const aff = (o: Partial<MessageAffordance> = {}): MessageAffordance => ({ ...AFF_DEFAULT, ...o });

describe('卡片与跳转分支（F0 安全绳扩围）', () => {
  beforeEach(() => {
    openDocsPanelMock.mockClear();
    navigateMock.mockClear();
  });

  it('docCard 渲染文档完成卡，点击打开文档面板', async () => {
    const msg: ChatMessage = { sender: 'agent', text: '', docCard: '剧本分析' };
    const { container } = render(() => <ChatMessageItem message={msg} affordance={aff({ confirmTarget: true })} />);
    const cardBtn = container.querySelector('.doc-card') as HTMLButtonElement;
    expect(cardBtn).toBeTruthy();
    expect(cardBtn.textContent).toContain('剧本分析');
    await fireEvent.click(cardBtn);
    expect(openDocsPanelMock).toHaveBeenCalledWith('剧本分析');
  });

  it('settingsHint 错误气泡附「检查 API 配置」跳转（导航 /settings）', async () => {
    const msg: ChatMessage = { sender: 'agent', text: '鉴权失败', settingsHint: true };
    const { container } = render(() => <ChatMessageItem message={msg} affordance={aff({ confirmTarget: true })} />);
    const btn = container.querySelector('.gate-override-btn') as HTMLButtonElement;
    expect(btn).toBeTruthy();
    await fireEvent.click(btn);
    expect(navigateMock).toHaveBeenCalledWith('/settings');
  });

  it('errorDetail 渲染可折叠技术详情（默认收起不干扰人话气泡）', () => {
    const msg: ChatMessage = { sender: 'agent', text: '出错了', errorDetail: 'HTTP 500 upstream' };
    const { container } = render(() => <ChatMessageItem message={msg} affordance={aff({ confirmTarget: true })} />);
    const details = container.querySelector('.msg-error-detail') as HTMLDetailsElement;
    expect(details).toBeTruthy();
    expect(container.querySelector('.msg-error-detail-body')?.textContent).toBe('HTTP 500 upstream');
  });

  it('hideChrome：轮次容器内不重复渲染作者名与 meta', () => {
    const msg: ChatMessage = { sender: 'agent', text: '正文', modelName: 'deepchat', meta: '耗时 3s' };
    const bare = render(() => <ChatMessageItem message={msg} affordance={aff()} />);
    expect(bare.container.querySelector('.msg-author')?.textContent).toBe('deepchat');
    expect(bare.container.querySelector('.msg-meta')?.textContent).toBe('耗时 3s');
    const grouped = render(() => <ChatMessageItem message={msg} affordance={aff()} hideChrome />);
    expect(grouped.container.querySelector('.msg-author')).toBeNull();
    expect(grouped.container.querySelector('.msg-meta')).toBeNull();
  });

  it('system_action 用户消息渲染系统动作行，不占用户气泡形态', () => {
    const msg: ChatMessage = { sender: 'user', text: '本次放行', kind: 'system_action' };
    const { container } = render(() => <ChatMessageItem message={msg} affordance={aff()} />);
    expect(container.querySelector('.system-action-line')?.textContent).toBe('本次放行');
    expect(container.querySelector('.chat-bubble')).toBeNull();
  });

  it('纯 Skill 唤起：正文与 Skill 块同名时隐藏正文只留块', () => {
    const msg: ChatMessage = { sender: 'user', text: '古风甜宠短剧', skillBlocks: ['古风甜宠短剧'] };
    const { container } = render(() => <ChatMessageItem message={msg} affordance={aff()} />);
    expect(container.querySelector('.user-bubble-text')).toBeNull();
  });

  it('正文与 Skill 块不同名时正文照常展示', () => {
    const msg: ChatMessage = { sender: 'user', text: '用这个风格再来一段', skillBlocks: ['古风甜宠短剧'] };
    const { container } = render(() => <ChatMessageItem message={msg} affordance={aff()} />);
    expect(container.querySelector('.user-bubble-text')?.textContent).toBe('用这个风格再来一段');
  });

  it('已回应暂停卡：agent 卡不再挂「当时所选」对勾区（批K 迁到用户气泡）', () => {
    const msg: ChatMessage = {
      sender: 'agent',
      text: '',
      confirm: '是否进入下一阶段？',
      confirmOptions: [{ label: '确认，继续' }, { label: '我要调整' }],
    };
    const { container } = render(() => (
      <ChatMessageItem message={msg} affordance={aff({ confirmState: 'answered', answeredValue: '确认，继续' })} />
    ));
    // 2026-09-21 批K（用户要求）：旧「整排选项重画 + 文字匹配打勾」已从 agent 卡移除，
    // 问答回执改在用户气泡内逐问呈现（PauseQaBlock）。
    expect(container.querySelector('.answered-options')).toBeNull();
    // 阶段完成卡本身照旧渲染（只摘掉对勾区）
    expect(container.querySelector('.stage-card')).toBeTruthy();
  });

  it('用户气泡内渲染一问一答回执（批K）：问题 → 你的选择', () => {
    const msg: ChatMessage = {
      sender: 'user',
      text: '16:9\n不显名',
    };
    const { container } = render(() => (
      <ChatMessageItem
        message={msg}
        affordance={aff({
          pauseQa: [
            { header: '', question: '画幅？', selected: ['16:9'], custom: '', unanswered: false },
            { header: '', question: '显名？', selected: ['不显名'], custom: '', unanswered: false },
            { header: '', question: '语调？', selected: [], custom: '', unanswered: true },
          ],
        })}
      />
    ));
    const rows = container.querySelectorAll('[data-testid="pause-qa-row"]');
    expect(rows).toHaveLength(3);
    expect(rows[0].textContent).toContain('画幅？');
    expect(rows[0].textContent).toContain('16:9');
    expect(rows[1].textContent).toContain('不显名');
    // 跳过的问显示「未作答」，不再靠缺行猜测
    expect(rows[2].textContent).toContain('未作答');
    // R 批（用户裁决，对齐 dsh 单点呈现）：回执存在 → 拼接正文隐藏
    expect(container.querySelector('.user-bubble-text')).toBeNull();
  });

  it('用户气泡内渲染提问回执卡（A 批 + R 批，对齐 dsh AskQuestionRow）：'
    + '完整问句 + 折叠行 +「查看说明」', () => {
    const msg: ChatMessage = { sender: 'user', text: '16:9 横屏' };
    const { container } = render(() => (
      <ChatMessageItem
        message={msg}
        affordance={aff({
          pauseQa: [
            {
              header: '画幅比例', question: '成片画幅比例？', selected: ['16:9 横屏'],
              custom: '', unanswered: false,
              notes: { '16:9 横屏': '横屏为主，电影院与电视通用' },
            },
            { header: '影像风格', question: '影像风格？', selected: [], custom: '', unanswered: true },
          ],
        })}
      />
    ));
    // 折叠行：「提问 · 1/2 已回答」；默认展开，逐问答对可见（未作答显式标注）
    const card = container.querySelector('[data-testid="ask-question-receipt"]');
    expect(card).toBeTruthy();
    expect(card?.textContent).toContain('提问');
    expect(card?.textContent).toContain('1/2 已回答');
    expect(container.querySelectorAll('[data-testid="pause-qa-row"]')).toHaveLength(2);
    // R 批：显示完整问句（question 优先）
    expect(card?.textContent).toContain('成片画幅比例？');
    expect(container.textContent).toContain('未作答');
    // R 批：回执存在 → 拼接正文（msg.text「16:9 横屏」）隐藏，回答只在回执呈现
    expect(container.querySelector('.user-bubble-text')).toBeNull();
    // 点头部 = 折叠/展开回执本体
    fireEvent.click(card!.querySelector('.ask-receipt-header') as HTMLButtonElement);
    expect(container.querySelector('[data-testid="pause-qa-row"]')).toBeNull();
    fireEvent.click(card!.querySelector('.ask-receipt-header') as HTMLButtonElement);
    expect(container.querySelectorAll('[data-testid="pause-qa-row"]')).toHaveLength(2);
    // R 批：「查看说明」展开所选选项的 description（dsh row.inspect 等价物）
    expect(card?.textContent).not.toContain('横屏为主');
    fireEvent.click(card!.querySelector('.ask-receipt-toggle') as HTMLButtonElement);
    expect(card?.textContent).toContain('横屏为主');
    fireEvent.click(card!.querySelector('.ask-receipt-toggle') as HTMLButtonElement);
    expect(card?.textContent).not.toContain('横屏为主');
  });
});

describe('复制与存为文档 hover 动作', () => {
  beforeEach(() => {
    copyMock.mockClear();
    toastMock.mockClear();
    saveDocMock.mockClear();
  });

  it('复制正文成功 → success toast（copyText 携带正文）', async () => {
    const msg: ChatMessage = { sender: 'agent', text: '待复制正文' };
    const { container } = render(() => <ChatMessageItem message={msg} affordance={aff({ confirmTarget: true, copyable: true })} />);
    await fireEvent.click(container.querySelector('[data-testid="msg-act-copy"]') as HTMLButtonElement);
    await Promise.resolve();
    expect(copyMock).toHaveBeenCalledWith('待复制正文');
    expect(toastMock).toHaveBeenCalledWith(expect.any(String), 'success');
  });

  it('存为文档携带正文调 saveMessageAsDoc；in-flight 期间按钮隐藏防双击', async () => {
    let resolveSave!: () => void;
    saveDocMock.mockImplementationOnce(() => new Promise<void>((r) => { resolveSave = r; }));
    const msg: ChatMessage = { sender: 'agent', text: '存为文档的正文' };
    const { container } = render(() => <ChatMessageItem message={msg} affordance={aff({ confirmTarget: true, docSavable: true })} />);
    const btn = container.querySelector('[data-testid="msg-act-save-doc"]') as HTMLButtonElement;
    expect(btn).toBeTruthy();
    await fireEvent.click(btn);
    // in-flight：按钮已隐藏（docSavable && !savingDoc）
    expect(container.querySelector('[data-testid="msg-act-save-doc"]')).toBeNull();
    resolveSave();
    await Promise.resolve();
    expect(saveDocMock).toHaveBeenCalledTimes(1);
    expect(saveDocMock).toHaveBeenCalledWith('存为文档的正文');
  });
});

describe('过程时间线数据源（F2 账本消费面：settledLedgerForMessage）', () => {
  it('消息携带翻转账本（ledger）：时间线直读账本账目，不从 trace 二次重建', () => {
    const msg: ChatMessage = {
      sender: 'agent',
      text: '完成',
      // 账本与 trace 故意不同源：断言渲染取自 ledger（唯一账目来源）
      ledger: {
        phase: 'settled',
        reasoning: '账本思考',
        items: [{ id: 't1', summary: '账本账目', status: 'done', elapsed_ms: 800 }],
        statusText: '',
        reasoningStartMs: 0,
        reasoningEndMs: 0,
      },
      trace: {
        steps: [{
          step: 1, timing_ms: 900, token_usage: 0, actions_applied: 0, finish_reason: 'stop',
          reasoning: 'trace 思考',
          actions: [{ name: 'x', summary: 'trace 账目', ok: true, elapsed_ms: 100 }],
        }],
      },
    };
    const { container } = render(() => <ChatMessageItem message={msg} affordance={aff({ confirmTarget: true })} />);
    const timeline = container.querySelector('.agent-timeline');
    expect(timeline?.textContent).toContain('账本账目');
    expect(timeline?.textContent).toContain('账本思考');
    expect(timeline?.textContent).not.toContain('trace 账目');
  });

  it('历史/刷新消息无本地账本：回落 ledgerFromSettled(trace) 同一归一入口重建', () => {
    const msg: ChatMessage = {
      sender: 'agent',
      text: '完成',
      trace: {
        steps: [{
          step: 1, timing_ms: 900, token_usage: 0, actions_applied: 0, finish_reason: 'stop',
          reasoning: '历史思考',
          actions: [{ name: 'script_analyze', summary: '分析剧本', ok: true, elapsed_ms: 800 }],
        }],
      },
    };
    const { container } = render(() => <ChatMessageItem message={msg} affordance={aff({ confirmTarget: true })} />);
    const timeline = container.querySelector('.agent-timeline');
    expect(timeline?.textContent).toContain('分析剧本');
    expect(timeline?.textContent).toContain('历史思考');
  });

  it('空账本（纯文本轮未走工具事件）：回落 trace/actionLog 重建，action_log 兜底不丢', () => {
    const msg: ChatMessage = {
      sender: 'agent',
      text: '规划已完成',
      // finishStream 无条件翻转的空账本（无工具事件轮）：不得遮蔽 actionLog 兜底
      ledger: {
        phase: 'settled', reasoning: '', items: [], statusText: '',
        reasoningStartMs: 0, reasoningEndMs: 0,
      },
      actionLog: ['新建关键元素分组「主角」'],
    };
    const { container } = render(() => <ChatMessageItem message={msg} affordance={aff({ confirmTarget: true })} />);
    const timeline = container.querySelector('.agent-timeline');
    expect(timeline?.textContent).toContain('新建关键元素分组「主角」');
  });
});
