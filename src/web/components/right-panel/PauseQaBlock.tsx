/**
 * PauseQaBlock — 用户气泡内的「一问一答」回执（2026-09-21 批K）。
 *
 * 背景（用户要求）：「直接在我回复的气泡那边就行」——以前回看时，agent 卡片
 * 下面会铺一块泛化的选项对勾区（AnsweredOptions：把整排选项重画、选中的打勾），
 * 多问题时会全部混在一起、且同名选项会互相串（匹配只认文字、不认属于第几问）。
 *
 * 现形态：问答**贴在用户自己的气泡里**，逐问一行「问题 → 你选的」，
 * 配对走**问题 id**（批J 落盘的 `pauseAnsweredAnswers`），不再靠文字或行序。
 *
 * 旧消息（无 `pauseAnsweredAnswers`）由 `pauseQaFor` 回落逐行按序补齐，
 * 保证历史可读；完全无问答数据时不渲染本块。
 */
import { For, Show } from 'solid-js';
import { t } from '@/lib/locale';
import type { PauseQaPair } from '@/lib/turn-groups';

export function PauseQaBlock(props: { pairs: PauseQaPair[] }) {
  return (
    <div class="pause-qa" data-testid="pause-qa-block">
      <For each={props.pairs}>
        {(p) => (
          <div class="pause-qa-row" data-testid="pause-qa-row">
            <span class="pause-qa-q" title={p.question}>
              {p.header || p.question}
            </span>
            <span class="pause-qa-arrow" aria-hidden="true">→</span>
            <Show
              when={!p.unanswered}
              fallback={<span class="pause-qa-none">{t('rp.qa.unanswered')}</span>}
            >
              <span class="pause-qa-a">
                <Show when={p.custom}>
                  <span class="pause-qa-custom">{p.custom}</span>
                </Show>
                <For each={p.selected}>
                  {(s) => <span class="pause-qa-pick">{s}</span>}
                </For>
              </span>
            </Show>
          </div>
        )}
      </For>
    </div>
  );
}
