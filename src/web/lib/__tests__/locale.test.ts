import { describe, it, expect, afterEach } from 'vitest';
import { t, setLocale, getLocale } from '@/lib/locale';

describe('lib/locale（P2-4 i18n 基础）', () => {
  afterEach(() => setLocale('zh-CN'));

  it('zh-CN 为默认语言，直接命中字典', () => {
    expect(getLocale()).toBe('zh-CN');
    expect(t('rp.feed.empty')).toBe('和 Agent 聊聊，让它帮你规划故事板');
  });

  it('占位符插值（多处同名占位不残留）', () => {
    expect(t('rp.input.added', { name: '图A' })).toBe('已添加：图A');
    expect(t('rp.msg.appliedOps', { count: 3 })).toBe('已执行 3 个操作');
    expect(t('rp.asset.cardToggle', { name: 'x.png', action: '选中' }))
      .toBe('x.png — 点击选中');
  });

  it('缺失 key 回退为 key 本身（便于排查漏抽取）', () => {
    expect(t('rp.not.exists')).toBe('rp.not.exists');
  });

  it('未提供的语言（en 未补齐）回退 zh-CN', () => {
    setLocale('en');
    expect(t('rp.feed.empty')).toBe('和 Agent 聊聊，让它帮你规划故事板');
  });
});
