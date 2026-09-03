/**
 * i18n key 校验：
 * 编译期由 LocaleKey 类型钉死静态调用点（拼错的 key 无法通过 tsc）；
 * 本测试补运行时侧的字典体检与后端动态键契约——
 * ① 键命名格式（前缀分组 + 点分层，无畸形键）；
 * ② 值非空且无未闭合占位符花括号残留；
 * ③ 后端 SSE status 事件可能下发的键全部已登记（动态键不回退原文）；
 * ④ 占位符声明与消费一致（{name} 成对出现）。
 */
import { describe, it, expect } from 'vitest';
import { LOCALE_KEYS, t, tDynamic, type LocaleKey } from '@/lib/locale';

/** 键命名格式：小写字母开头的前缀段，点分层，段内字母数字 */
const KEY_FORMAT = /^[a-z][a-zA-Z0-9]*(\.[a-zA-Z][a-zA-Z0-9]*)+$/;

/** 后端 status 事件固定文案键（planner/agent_loop status_event 下发；
 * 缺失即把 'agent.xxx' 原文直接显示给用户，故在此钉死全集） */
const BACKEND_STATUS_KEYS = [
  'agent.roundThinking',
  'agent.roundStart',
  'agent.badRetry',
  'agent.flowGatePause',
  'agent.opsDone',
  'agent.modelFallback',
  'agent.planning',
  'agent.actionsApplied',
];

describe('locale 字典 key 校验', () => {
  it('全部键符合命名格式（前缀分组 + 点分层）', () => {
    const bad = LOCALE_KEYS.filter((k) => !KEY_FORMAT.test(k));
    expect(bad).toEqual([]);
  });

  it('键无重复（对象键天然唯一，防 satisfies 迁移后意外退化）', () => {
    expect(new Set(LOCALE_KEYS).size).toBe(LOCALE_KEYS.length);
  });

  it('值均为非空字符串，且无未配对的占位符花括号', () => {
    const bad: string[] = [];
    for (const key of LOCALE_KEYS) {
      const value = t(key);
      if (!value.trim()) bad.push(`${key}: empty`);
      // 未插值模板本身允许 {name}，但不允许单边花括号残留
      const open = (value.match(/\{/g) || []).length;
      const close = (value.match(/\}/g) || []).length;
      if (open !== close) bad.push(`${key}: unbalanced braces`);
    }
    expect(bad).toEqual([]);
  });

  it('后端 status 事件键全部已登记（动态键通道不回退原文）', () => {
    const registered = new Set<string>(LOCALE_KEYS);
    const missing = BACKEND_STATUS_KEYS.filter((k) => !registered.has(k));
    expect(missing).toEqual([]);
    // 动态通道取出的文案不等于键本身（即真正命中字典）
    for (const k of BACKEND_STATUS_KEYS) {
      expect(tDynamic(k)).not.toBe(k);
    }
  });
});

describe('LocaleKey 类型面（编译期校验的静态样本）', () => {
  it('合法键可赋值给 LocaleKey（拼错键由 tsc 拒收，此处钉正向契约）', () => {
    const okKey: LocaleKey = 'rp.feed.hint';
    expect(t(okKey)).toBeTruthy();
  });
});
