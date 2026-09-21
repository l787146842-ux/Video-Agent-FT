/**
 * PauseQaBlock — 用户气泡内的「一问一答」回执（2026-09-21 批K；R 批排版）。
 *
 * 背景（用户要求）：「直接在我回复的气泡那边就行」——以前回看时，agent 卡片
 * 下面会铺一块泛化的选项对勾区（AnsweredOptions：把整排选项重画、选中的打勾），
 * 多问题时会全部混在一起、且同名选项会互相串（匹配只认文字、不认属于第几问）。
 *
 * 现形态（R 批对齐 dsh `AskQuestionCard` 的 dl/dt/dd 上下结构）：逐问**纵向两层**——
 * 上行问题原文（`question` 优先，旧数据回落 `header`），下行「你的选择」；
 * 配对走**问题 id**（批J 落盘的 `pauseAnsweredAnswers`），不再靠文字或行序。
 *
 * 「查看说明」（dsh row.inspect 的轻量等价物）：回执主体只显示 label（dsh 口径）；
 * 所选选项的 description 经 `showNotes` 开关展开（开关在 AskQuestionReceipt）。
 *
 * 旧消息（无 `pauseAnsweredAnswers`）由 `pauseQaFor` 回落逐行按序补齐，
 * 保证历史可读；完全无问答数据时不渲染本块。
 */
import { For, Show } from 'solid-js';
import { t } from '@/lib/locale';
import type { PauseQaPair } from '@/lib/turn-groups';

export function PauseQaBlock(props: {
  pairs: PauseQaPair[];
  /** 展开所选选项的说明（「查看说明」开关；默认关闭 = 只显示 label，对齐 dsh） */
  showNotes?: boolean;
}) {
  return (
    <div class="pause-qa" data-testid="pause-qa-block">
      <For each={props.pairs}>
        {(p) => (
          <div class="pause-qa-row" data-testid="pause-qa-row">
            <div class="pause-qa-q">{p.question || p.header}</div>
            <Show
              when={!p.unanswered}
              fallback={<span class="pause-qa-none">{t('rp.qa.unanswered')}</span>}
            >
              <div class="pause-qa-a">
                <Show when={p.custom}>
                  <span class="pause-qa-custom">{p.custom}</span>
                </Show>
                <For each={p.selected}>
                  {(s) => (
                    <span class="pause-qa-pick-line">
                      <span class="pause-qa-pick">{s}</span>
                      <Show when={props.showNotes && p.notes?.[s]}>
                        <span class="pause-qa-note">{p.notes?.[s]}</span>
                      </Show>
                    </span>
                  )}
                </For>
              </div>
            </Show>
          </div>
        )}
      </For>
    </div>
  );
}
