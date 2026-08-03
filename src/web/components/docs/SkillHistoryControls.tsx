/**
 * Skill 文档历史版本控件（从 DocsPanel 拆出）：
 * 版本下拉（毫秒时间戳 → 可读日期）+ 「回滚」按钮。
 */
import { For, Show } from 'solid-js';
import { FiClock } from 'solid-icons/fi';
import type { SkillDocVersion } from '@/api/docs';

/** 版本标签：毫秒时间戳 → 可读日期时间 */
export function versionLabel(v: string): string {
  if (/^\d{13}$/.test(v)) {
    const d = new Date(Number(v));
    const p = (n: number) => String(n).padStart(2, '0');
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }
  return v;
}

export function SkillHistoryControls(props: {
  versions: SkillDocVersion[];
  selected: string;
  onSelect: (version: string) => void;
  onRollback: (version: SkillDocVersion) => void;
}) {
  const selectedVersionObj = () =>
    props.versions.find((v) => v.version === props.selected);

  return (
    <>
      <select
        class="docs-history-select"
        value={props.selected}
        onChange={(e) => props.onSelect(e.currentTarget.value)}
        title="历史版本"
      >
        <option value="">当前版本</option>
        <For each={props.versions}>
          {(v) => <option value={v.version}>历史 {versionLabel(v.version)}</option>}
        </For>
      </select>
      <Show when={selectedVersionObj()}>
        <button
          type="button"
          class="docs-save-btn"
          title="以该历史版本内容重新保存（当前版会自动备份）"
          onClick={() => {
            const v = selectedVersionObj();
            if (v) props.onRollback(v);
          }}
        >
          <FiClock size={11} /> 回滚
        </button>
      </Show>
    </>
  );
}
