import { createSignal, For, Show } from 'solid-js';
import { FiChevronsLeft, FiFilePlus, FiTrash2 } from 'solid-icons/fi';
import {
  allDocs, selectedSlug, selectSkill, newDraft, removeSkill, studioLoading,
} from '@/stores/skill-studio';
import { isSkillEnabled, toggleSkillEnabled } from '@/stores/skill-prefs';

/**
 * Skill 工作台左栏：全部 Skill 列表。
 * 每项：启停开关（批7/对齐外部标杆 卡片开关，写 runtime_settings.skills_disabled）
 * + 删除（内联二次确认）；点击卡片选中进中间预览；顶部「新建」空白草稿。
 */
export function SkillStudioList(props: { onCollapse: () => void }) {
  const [confirmingSlug, setConfirmingSlug] = createSignal<string | null>(null);

  return (
    <div class="skst-list">
      <div class="skst-list-header">
        <span>我的Skill</span>
        <div class="skst-list-header-actions">
          <button type="button" class="sks-btn" onClick={newDraft}>
            <FiFilePlus size={12} /> 新建
          </button>
          <button
            type="button"
            class="skst-collapse"
            title="收起列表"
            onClick={() => props.onCollapse()}
          >
            <FiChevronsLeft size={14} />
          </button>
        </div>
      </div>
      <div class="skst-list-body">
        <For each={allDocs()}>
          {(doc) => {
            const enabled = () => isSkillEnabled(doc.slug);
            return (
              <div
                class={`skst-item ${selectedSlug() === doc.slug ? 'active' : ''} ${enabled() ? '' : 'off'}`}
                onClick={() => selectSkill(doc.slug)}
              >
                <div class="skst-item-info">
                  <span class="skst-item-name">{doc.name}</span>
                  <Show when={doc.description}>
                    <span class="skst-item-desc">{doc.description}</span>
                  </Show>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={enabled()}
                  class={`skst-switch ${enabled() ? 'on' : ''}`}
                  title={enabled() ? '启用中：点击停用（不再进 Agent Skill 目录）' : '已停用：点击启用'}
                  onClick={(e) => {
                    e.stopPropagation();
                    void toggleSkillEnabled(doc.slug);
                  }}
                >
                  <span class="skst-knob" />
                </button>
                <Show
                  when={confirmingSlug() === doc.slug}
                  fallback={
                    <button
                      type="button"
                      class="skst-del"
                      title="删除"
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmingSlug(doc.slug);
                      }}
                    >
                      <FiTrash2 size={12} />
                    </button>
                  }
                >
                  <div class="skst-confirm">
                    <button
                      type="button"
                      class="yes"
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmingSlug(null);
                        void removeSkill(doc.slug);
                      }}
                    >
                      删
                    </button>
                    <button
                      type="button"
                      class="no"
                      onClick={(e) => { e.stopPropagation(); setConfirmingSlug(null); }}
                    >
                      否
                    </button>
                  </div>
                </Show>
              </div>
            );
          }}
        </For>
        <Show when={!allDocs().length}>
          <div class="empty-state">{studioLoading() ? '加载中…' : '暂无 Skill，点「新建」开始'}</div>
        </Show>
      </div>
    </div>
  );
}
