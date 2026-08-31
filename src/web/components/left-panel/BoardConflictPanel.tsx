import { For, Show } from 'solid-js';
import { FiAlertTriangle } from 'solid-icons/fi';
import {
  conflictsState, conflictKey, chooseConflict, chooseAll,
  type BoardConflict,
} from '@/stores/studio/conflicts';
import { resolveBoardConflicts, cancelBoardConflicts } from '@/stores/studio/conflict-actions';

/** 冲突项摘要：挑可读字段展示（提示词/媒体地址/标题），超长截断 */
function summarize(v: Record<string, unknown> | null): string {
  if (!v) return '（Agent 已删除该项）';
  for (const k of ['prompt', 'title', 'label', 'imgUrl', 'videoUrl', 'audioUrl', 'desc']) {
    const s = String(v[k] || '').trim();
    if (s) return s.length > 80 ? `${s.slice(0, 80)}…` : s;
  }
  return '（内容已改动）';
}

function kindText(c: BoardConflict): string {
  if (c.kind === 'delete_vs_modify') return '你改过它，但 Agent 把它删了';
  if (c.kind === 'group') return '你和 Agent 改了同一分组的属性';
  return '你和 Agent 改了同一张草稿';
}

/**
 * G1 故事板冲突面板（对标 Flova 冲突面板）：用户编辑与 Agent 写入
 * 同改一处时弹出，逐项定夺「保留我的 / 采用 Agent」，或整批一键定夺。
 */
export function BoardConflictPanel() {
  const chosen = (c: BoardConflict) => conflictsState.choices[conflictKey(c)] || 'mine';

  return (
    <Show when={conflictsState.open}>
      <div class="board-conflict-overlay">
        <div class="board-conflict-panel">
          <div class="board-conflict-head">
            <FiAlertTriangle size={15} />
            <span>故事板改动冲突（{conflictsState.conflicts.length} 处）</span>
          </div>
          <div class="board-conflict-sub">
            你保存时 Agent 也更新了故事板。以下内容双方都改过，请逐项选择保留哪一版；
            其余不冲突的改动已自动合并。
          </div>
          <div class="board-conflict-list">
            <For each={conflictsState.conflicts}>
              {(c) => (
                <div class="board-conflict-item">
                  <div class="board-conflict-item-head">
                    <span class="board-conflict-cat">{c.category_label}</span>
                    <span class="board-conflict-title">
                      {c.group_title}{c.kind === 'draft' && c.label !== c.group_title ? ` · ${c.label}` : ''}
                    </span>
                  </div>
                  <div class="board-conflict-reason">{kindText(c)}</div>
                  <div class="board-conflict-versions">
                    <div class={`board-conflict-ver ${chosen(c) === 'mine' ? 'picked' : ''}`}>
                      <div class="board-conflict-ver-tag">我的版本</div>
                      <div class="board-conflict-ver-text">{summarize(c.mine)}</div>
                    </div>
                    <div class={`board-conflict-ver ${chosen(c) === 'theirs' ? 'picked' : ''}`}>
                      <div class="board-conflict-ver-tag">Agent 版本</div>
                      <div class="board-conflict-ver-text">{summarize(c.theirs)}</div>
                    </div>
                  </div>
                  <div class="board-conflict-btns">
                    <button
                      type="button"
                      class={`gate-override-btn ${chosen(c) === 'mine' ? 'active' : ''}`}
                      onClick={() => chooseConflict(conflictKey(c), 'mine')}
                    >
                      保留我的
                    </button>
                    <button
                      type="button"
                      class={`gate-override-btn ${chosen(c) === 'theirs' ? 'active' : ''}`}
                      onClick={() => chooseConflict(conflictKey(c), 'theirs')}
                    >
                      采用 Agent
                    </button>
                  </div>
                </div>
              )}
            </For>
          </div>
          <div class="board-conflict-foot">
            <button type="button" class="gate-override-btn" onClick={() => chooseAll('mine')}>
              全部保留我的
            </button>
            <button type="button" class="gate-override-btn" onClick={() => chooseAll('theirs')}>
              全部采用 Agent
            </button>
            <span class="board-conflict-spacer" />
            <button type="button" class="gate-override-btn" onClick={() => void cancelBoardConflicts()}>
              放弃编辑
            </button>
            <button
              type="button"
              class="gate-override-btn primary"
              disabled={conflictsState.resolving}
              onClick={() => void resolveBoardConflicts()}
            >
              {conflictsState.resolving ? '保存中…' : '保存决定'}
            </button>
          </div>
        </div>
      </div>
    </Show>
  );
}
