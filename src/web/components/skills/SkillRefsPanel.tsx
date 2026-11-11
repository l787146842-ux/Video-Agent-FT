import { For, Show, createSignal } from 'solid-js';
import { FiChevronDown, FiChevronRight, FiFilePlus, FiSave, FiTrash2, FiX } from 'solid-icons/fi';
import {
  refs, refOpen, refContent, refDirty, refBusy, setRefContent, setRefDirty,
  selectedSlug, openSkillRef, closeSkillRef,
  saveSkillRefDraft, newSkillRef, removeSkillRef,
} from '@/stores/skill-studio';

/**
 * 分册（references/）面板：Skill 工作台中间栏底部。
 *
 * 分册承载模板类长细节，主文档只留「读 references/xxx.md」的路由。
 * 此前工作台完全看不到分册，用户无法查看/编辑/新增（2026-11-11 裁决补入口）。
 * 折叠态只显示「N 本分册」一行，不干扰主文档阅读；展开后可逐本查看编辑。
 */
export function SkillRefsPanel() {
  const [expanded, setExpanded] = createSignal(true);
  // 新建分册的文件名输入态（点「新建分册」后才出现）
  const [creating, setCreating] = createSignal(false);
  const [newName, setNewName] = createSignal('');

  const confirmCreate = () => {
    const n = newName().trim();
    if (!n) { setCreating(false); return; }
    const name = n.endsWith('.md') ? n : `${n}.md`;
    setCreating(false);
    setNewName('');
    void newSkillRef(name);
  };

  return (
    <Show when={selectedSlug()}>
      <div class="skst-refs">
        <div class="skst-refs-header">
          <button
            type="button"
            class="skst-refs-toggle"
            onClick={() => setExpanded(!expanded())}
            title={expanded() ? '收起分册' : '展开分册'}
          >
            <Show when={expanded()} fallback={<FiChevronRight size={12} />}>
              <FiChevronDown size={12} />
            </Show>
            <span>分册（references/）</span>
            <span class="skst-refs-count">{refs().length}</span>
          </button>
          <div class="sks-spacer" />
          <Show when={expanded()}>
            <button
              type="button"
              class="sks-btn"
              title="新建分册"
              onClick={() => { setCreating(true); setNewName(''); }}
            >
              <FiFilePlus size={12} /> 新建分册
            </button>
          </Show>
        </div>

        <Show when={expanded()}>
          <Show when={creating()}>
            <div class="skst-refs-create">
              <input
                type="text"
                placeholder="分册文件名，如 媒体生成.md"
                value={newName()}
                onInput={(e) => setNewName(e.currentTarget.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') confirmCreate(); }}
              />
              <button type="button" class="sks-btn primary" onClick={confirmCreate}>创建</button>
              <button type="button" class="sks-btn" onClick={() => setCreating(false)}>取消</button>
            </div>
          </Show>

          <Show
            when={refs().length > 0}
            fallback={
              <div class="skst-refs-empty">
                本 Skill 没有分册。模板类长细节建议拆到 references/，主文档只留路由。
              </div>
            }
          >
            <For each={refs()}>
              {(r) => (
                <div class={`skst-refs-item ${refOpen() === r.name ? 'active' : ''}`}>
                  <button
                    type="button"
                    class="skst-refs-name"
                    onClick={() => void openSkillRef(r.name)}
                    title={`${r.name}（${r.chars} 字）`}
                  >
                    {r.name}
                    <span class="skst-refs-chars">{r.chars}</span>
                  </button>
                  <button
                    type="button"
                    class="skst-del"
                    title="删除分册"
                    onClick={() => void removeSkillRef(r.name)}
                  >
                    <FiTrash2 size={12} />
                  </button>
                </div>
              )}
            </For>
          </Show>

          {/* 分册编辑区：打开某本后替换列表下方 */}
          <Show when={refOpen()}>
            <div class="skst-refs-editor">
              <div class="skst-refs-editor-head">
                <span class="skst-refs-editor-name">{refOpen()}</span>
                <Show when={refDirty()}>
                  <span class="skst-dirty" title="未保存">●</span>
                </Show>
                <div class="sks-spacer" />
                <button
                  type="button"
                  class="sks-btn primary"
                  disabled={refBusy()}
                  onClick={() => void saveSkillRefDraft()}
                >
                  <FiSave size={12} /> 保存分册
                </button>
                <button type="button" class="sks-btn" title="关闭" onClick={closeSkillRef}>
                  <FiX size={12} />
                </button>
              </div>
              <textarea
                class="skst-refs-textarea"
                value={refContent()}
                onInput={(e) => {
                  setRefContent(e.currentTarget.value);
                  setRefDirty(true);
                }}
              />
            </div>
          </Show>
        </Show>
      </div>
    </Show>
  );
}
