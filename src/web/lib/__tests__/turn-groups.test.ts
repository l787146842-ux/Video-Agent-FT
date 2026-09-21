import { describe, it, expect } from 'vitest';
import { groupTurns, suggestedTargetIndex, answeredValueFor, pauseQaFor, stabilizeGroups } from '../turn-groups';
import type { ChatMessage } from '@/types';

/** ：轮次分组纯函数（turnId 为主，相邻 agent 兜底） */

const u = (text: string): ChatMessage => ({ sender: 'user', text });
const a = (turnId?: string, extra?: Partial<ChatMessage>): ChatMessage => ({
  sender: 'agent', text: '', turnId, ...extra,
});

describe('groupTurns 轮次分组', () => {
  it('同 turnId 的正文/文档卡/图片卡聚合为一组', () => {
    const groups = groupTurns([
      u('开工'),
      a('t1', { text: '总结' }),
      a('t1', { docCard: '规格.md' }),
      a('t1', { imageCard: { image_urls: ['x.png'] } }),
    ]);
    expect(groups.length).toBe(2);
    expect(groups[0].kind).toBe('user');
    expect(groups[1].kind).toBe('turn');
    expect(groups[1].indices).toEqual([1, 2, 3]);
    expect(groups[1].turnId).toBe('t1');
  });

  it('不同 turnId 不相邻合并（即使中间无用户消息也不误并）', () => {
    const groups = groupTurns([a('t1'), a('t2')]);
    expect(groups.length).toBe(2);
    expect(groups[0].indices).toEqual([0]);
    expect(groups[1].indices).toEqual([1]);
  });

  it('无 turnId 的旧消息按相邻兜底合并', () => {
    const groups = groupTurns([u('q'), a(undefined, { text: '正文' }), a(undefined, { docCard: 'd' })]);
    expect(groups.length).toBe(2);
    expect(groups[1].indices).toEqual([1, 2]);
    expect(groups[1].turnId).toBeUndefined();
  });

  it('用户消息永远独立成组并切断相邻合并', () => {
    const groups = groupTurns([a(undefined), u('再改'), a(undefined)]);
    expect(groups.length).toBe(3);
    expect(groups.map((g) => g.kind)).toEqual(['turn', 'user', 'turn']);
  });

  it('新 turnId 消息与无 turnId 旧消息相邻时兜底合并（过渡期历史混排）', () => {
    const groups = groupTurns([a(undefined, { text: '旧' }), a('t9', { docCard: 'd' })]);
    expect(groups.length).toBe(1);
    expect(groups[0].turnId).toBe('t9');
  });

  it('即显 doc 卡携带事件 turn_id 与主消息严格同组（不依赖兜底）', () => {
    const groups = groupTurns([
      u('写文档'),
      a('t7', { docCard: '规格.md' }), // doc_written 事件打戳先到
      a('t7', { text: '总结' }),       // done 主消息后到
    ]);
    expect(groups.length).toBe(2);
    expect(groups[1].indices).toEqual([1, 2]);
    expect(groups[1].turnId).toBe('t7');
  });
});

/** ：建议动作按钮挂载边界（锐化后规则） */
const act = { kind: 'retry' as const, label: '重试', value: '' };

describe('suggestedTargetIndex 建议按钮挂载边界', () => {
  it('携带者其后无新消息 → 渲染（返回其下标）', () => {
    const msgs = [u('开工'), a('t1', { text: '空响应', suggestedActions: [act] }), a('t1', { docCard: 'd' })];
    expect(suggestedTargetIndex(msgs, false)).toBe(1);
  });

  it('携带者其后出现新用户消息 → 失效（返回 -1）', () => {
    const msgs = [a('t1', { text: 'x', suggestedActions: [act] }), u('我手动继续了')];
    expect(suggestedTargetIndex(msgs, false)).toBe(-1);
  });

  it('流式进行中 → 不渲染', () => {
    const msgs = [a('t1', { text: 'x', suggestedActions: [act] })];
    expect(suggestedTargetIndex(msgs, true)).toBe(-1);
  });
});

/** 暂停回应结构化派生（对标 AskUserQuestion：展示层状态从权威登记派生） */
describe('answeredValueFor 当时所选值', () => {
  it('结构化匹配：pauseAnsweredId 与暂停卡 pauseId 相等 → 返回登记值', () => {
    const msgs: ChatMessage[] = [
      a('t1', { text: '请确认', confirm: '请确认', pauseId: 'p1', confirmOptions: [{ label: '确认' }] }),
      { sender: 'user', text: '确认推进', pauseAnsweredId: 'p1', pauseAnsweredValue: '确认推进' },
    ];
    expect(answeredValueFor(msgs, 0)).toBe('确认推进');
  });

  it('自由打字回应（无结构化标记）回落文本匹配', () => {
    const msgs: ChatMessage[] = [
      a('t1', { text: '请确认', confirm: '请确认', pauseId: 'p1' }),
      u('我觉得第二个方案更好'),
    ];
    expect(answeredValueFor(msgs, 0)).toBe('我觉得第二个方案更好');
  });

  it('旧消息无 pauseId 时仍走文本回落（向后兼容）', () => {
    const msgs: ChatMessage[] = [
      a('t1', { text: '请确认', confirm: '请确认' }),
      u('确认，继续'),
    ];
    expect(answeredValueFor(msgs, 0)).toBe('确认，继续');
  });

  it('系统动作行不构成对暂停的回应（穿透到真实回应）', () => {
    const msgs: ChatMessage[] = [
      a('t1', { text: '请确认', confirm: '请确认', pauseId: 'p1' }),
      { sender: 'user', text: '放行本次拦截，继续任务', kind: 'system_action' },
      { sender: 'user', text: '确认', pauseAnsweredId: 'p1', pauseAnsweredValue: '确认' },
    ];
    expect(answeredValueFor(msgs, 0)).toBe('确认');
  });

  it('其后无用户消息 → 空串', () => {
    const msgs: ChatMessage[] = [a('t1', { text: '请确认', confirm: '请确认', pauseId: 'p1' })];
    expect(answeredValueFor(msgs, 0)).toBe('');
  });
});

/** 一问一答配对（2026-09-21 批K）：用户气泡内回执的数据源。
 *  **按问题 id 配对**，不再依赖「第几行 = 第几问」的位置约定。 */
describe('pauseQaFor 一问一答配对', () => {
  /** 一张两问的暂停卡 + 用户的回答（结构化） */
  const card = (pid = 'p1'): ChatMessage => a('t1', {
    text: '', confirm: '请确认', pauseId: pid,
    pauseQuestions: [
      { id: 'ratio', question: '画幅？', options: [{ label: '16:9' }, { label: '9:16' }] },
      { id: 'naming', question: '显名？', options: [{ label: '显名' }, { label: '不显名' }] },
    ],
  });
  const answer = (extra?: Partial<ChatMessage>): ChatMessage => ({
    sender: 'user', text: '16:9\n不显名',
    pauseAnsweredId: 'p1', pauseAnsweredValue: '16:9\n不显名', ...extra,
  });

  it('按 id 配对：问题原文 × 所选，逐问成对', () => {
    const msgs: ChatMessage[] = [card(), answer({
      pauseAnsweredAnswers: [
        { id: 'ratio', selected: ['16:9'] },
        { id: 'naming', selected: ['不显名'] },
      ],
    })];
    const qa = pauseQaFor(msgs, 1);
    expect(qa.map((p) => p.question)).toEqual(['画幅？', '显名？']);
    expect(qa.map((p) => p.selected)).toEqual([['16:9'], ['不显名']]);
    expect(qa.every((p) => !p.unanswered)).toBe(true);
  });

  it('同名选项不会互相串（旧文字匹配的病根）', () => {
    // 两问都有「写实」这个选项，但用户只在第①问选了它
    const msgs: ChatMessage[] = [
      a('t1', {
        text: '', confirm: '请确认', pauseId: 'p1',
        pauseQuestions: [
          { id: 'a', question: '角色风格？', options: [{ label: '写实' }] },
          { id: 'b', question: '场景风格？', options: [{ label: '写实' }, { label: '写意' }] },
        ],
      }),
      answer({
        text: '写实\n写意',
        pauseAnsweredValue: '写实\n写意',
        pauseAnsweredAnswers: [
          { id: 'a', selected: ['写实'] },
          { id: 'b', selected: ['写意'] },
        ],
      }),
    ];
    const qa = pauseQaFor(msgs, 1);
    expect(qa[0].selected).toEqual(['写实']);   // 第①问
    expect(qa[1].selected).toEqual(['写意']);   // 第②问没被第①问的「写实」污染
  });

  it('跳过的问显示未作答（不再靠缺行猜测）', () => {
    const msgs: ChatMessage[] = [card(), answer({
      pauseAnsweredAnswers: [{ id: 'ratio', selected: ['16:9'] }],
    })];
    const qa = pauseQaFor(msgs, 1);
    expect(qa[0].unanswered).toBe(false);
    expect(qa[1].unanswered).toBe(true);
    expect(qa[1].selected).toEqual([]);
  });

  it('自定义文本作答走 custom 槽（selected 为空但仍算已答）', () => {
    const msgs: ChatMessage[] = [card(), answer({
      pauseAnsweredAnswers: [{ id: 'ratio', selected: [], custom: '我自己定 4:3' }],
    })];
    const qa = pauseQaFor(msgs, 1);
    expect(qa[0].custom).toBe('我自己定 4:3');
    expect(qa[0].unanswered).toBe(false);
  });

  it('多选题的 selected 保留全部勾选', () => {
    const msgs: ChatMessage[] = [
      a('t1', {
        text: '', confirm: '请确认', pauseId: 'p1',
        pauseQuestions: [{ id: 'tone', question: '基调？', multi_select: true }],
      }),
      answer({
        pauseAnsweredAnswers: [{ id: 'tone', selected: ['冷调', '暖调'] }],
      }),
    ];
    expect(pauseQaFor(msgs, 1)[0].selected).toEqual(['冷调', '暖调']);
  });

  it('旧消息（无 pauseAnsweredAnswers）回落逐行按序补齐', () => {
    const msgs: ChatMessage[] = [card(), answer()];   // 只有扁平 value
    const qa = pauseQaFor(msgs, 1);
    expect(qa[0].selected).toEqual(['16:9']);
    expect(qa[1].selected).toEqual(['不显名']);
  });

  it('非问答消息 / 找不到暂停卡 → 空数组（不生成无主块）', () => {
    // 普通用户消息
    expect(pauseQaFor([card(), u('随便说点啥')], 1)).toEqual([]);
    // 有 pauseAnsweredId 但前面没有对应暂停卡（脏数据）
    expect(pauseQaFor([u('你好'), answer()], 1)).toEqual([]);
    // 暂停卡无 pauseQuestions（旧卡）
    const bare = a('t1', { text: '', confirm: '请确认', pauseId: 'p1' });
    expect(pauseQaFor([bare, answer()], 1)).toEqual([]);
  });

  it('header/question 双字段保留（R 批显示层以 question 优先，对齐 dsh）', () => {
    const msgs: ChatMessage[] = [
      a('t1', {
        text: '', confirm: '请确认', pauseId: 'p1',
        pauseQuestions: [{ id: 'x', header: '画幅', question: '成片画幅选哪个？' }],
      }),
      answer({ pauseAnsweredAnswers: [{ id: 'x', selected: ['16:9'] }] }),
    ];
    const qa = pauseQaFor(msgs, 1);
    expect(qa[0].header).toBe('画幅');
    expect(qa[0].question).toBe('成片画幅选哪个？');
  });

  it('所选选项带 description → notes 提取（R 批「查看说明」数据源）', () => {
    const msgs: ChatMessage[] = [
      a('t1', {
        text: '', confirm: '请确认', pauseId: 'p1',
        pauseQuestions: [{
          id: 'style', question: '影像风格基调选哪种？',
          options: [
            { label: '硬核写实科幻', description: '冷色调、NASA 质感' },
            { label: '赛博霓虹', description: '高饱和、夜间雨巷' },
          ],
        }],
      }),
      answer({ pauseAnsweredAnswers: [{ id: 'style', selected: ['硬核写实科幻'] }] }),
    ];
    expect(pauseQaFor(msgs, 1)[0].notes).toEqual({
      '硬核写实科幻': '冷色调、NASA 质感',
      '赛博霓虹': '高饱和、夜间雨巷',
    });
  });

  it('选项无 description → notes 缺省省略（「查看说明」按钮不出现）', () => {
    const msgs: ChatMessage[] = [
      card(),
      answer({ pauseAnsweredAnswers: [{ id: 'ratio', selected: ['16:9'] }] }),
    ];
    expect(pauseQaFor(msgs, 1)[0].notes).toBeUndefined();
  });
});


/** 组引用稳定化：Solid <For> 按 identity diff，引用复用保住既有节点 */
describe('stabilizeGroups 组引用稳定化', () => {
  it('同位同形态组复用旧引用（内容变化不触发整组拆建）', () => {
    const prev = groupTurns([u('问'), a('t1', { text: '旧正文' })]);
    const next = groupTurns([u('问'), a('t1', { text: '新正文（变长）' })]);
    const out = stabilizeGroups(prev, next);
    expect(out[0]).toBe(prev[0]);
    expect(out[1]).toBe(prev[1]);
  });

  it('尾部新增组：旧组引用保留，新组用新引用', () => {
    const prev = groupTurns([u('问'), a('t1', { text: '答' })]);
    const next = groupTurns([u('问'), a('t1', { text: '答' }), u('再问'), a('t2', { text: '再答' })]);
    const out = stabilizeGroups(prev, next);
    expect(out[0]).toBe(prev[0]);
    expect(out[1]).toBe(prev[1]);
    expect(out[2]).toBe(next[2]);
    expect(out[3]).toBe(next[3]);
  });

  it('组内追加消息 / turnId 变化 → 该组换新引用（diff 必须可见）', () => {
    const prev = groupTurns([a('t1', { text: '正文' })]);
    const grown = groupTurns([a('t1', { text: '正文' }), a('t1', { docCard: 'd.md' })]);
    expect(stabilizeGroups(prev, grown)[0]).toBe(grown[0]);
    const reid = groupTurns([a('t9', { text: '正文' })]);
    expect(stabilizeGroups(prev, reid)[0]).toBe(reid[0]);
  });

  it('prev 为空（首渲染）原样返回 next', () => {
    const next = groupTurns([u('问')]);
    expect(stabilizeGroups([], next)).toEqual(next);
  });
});
