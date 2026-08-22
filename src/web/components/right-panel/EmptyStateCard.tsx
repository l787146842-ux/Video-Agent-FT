import { For } from 'solid-js';
import { t, type LocaleKey } from '@/lib/locale';
import { submitMessage } from '@/lib/submit-message';

/** 示例指令词条键（点击即作为新消息发送，走统一发送入口） */
const EXAMPLE_KEYS: LocaleKey[] = [
  'rp.empty.example1',
  'rp.empty.example2',
  'rp.empty.example3',
  'rp.empty.example4',
];

/**
 * 空状态引导卡（无消息且非流式时替代单行淡色提示）：
 * 能力提示 + 示例指令 chips——点击示例即走 submitMessage('new') 发送，
 * 冷启动不再只有一句淡色文字。
 */
export function EmptyStateCard() {
  const sendExample = (key: LocaleKey) => {
    void submitMessage('new', { input: t(key) });
  };

  return (
    <div class="empty-state-card" data-testid="empty-state-card">
      <div class="chat-feed-hint">{t('rp.feed.hint')}</div>
      <div class="empty-state-title">{t('rp.empty.title')}</div>
      <div class="empty-state-try">{t('rp.empty.try')}</div>
      <div class="empty-state-examples">
        <For each={EXAMPLE_KEYS}>
          {(key) => (
            <button
              type="button"
              class="empty-state-example"
              onClick={() => sendExample(key)}
            >
              {t(key)}
            </button>
          )}
        </For>
      </div>
    </div>
  );
}
