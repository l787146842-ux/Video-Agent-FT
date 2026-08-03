/**
 * 文档面板侧边栏（从 DocsPanel 拆出）：
 * 三段列表（项目文档 / 上传素材 / Skill 文档）+ 新建文档入口。
 */
import { createSignal, For, Show } from 'solid-js';
import { FiFileText, FiPlus, FiX, FiZap } from 'solid-icons/fi';
import { state } from '@/stores/studio';
import {
  visibleSkillDocs, current, selectDoc, closeDocsPanel, createDoc, setAssetContent,
} from '@/stores/docs';

export function DocsSidebar() {
  const [creating, setCreating] = createSignal(false);
  const [newName, setNewName] = createSignal('');

  const textAssets = () =>
    (state.assets || []).filter((a) => /\.(md|txt|pdf)$/i.test(a.name || ''));

  const isActive = (kind: 'project' | 'skill', key: string) =>
    current()?.kind === kind && current()?.key === key;

  function openAssetDoc(name: string) {
    const asset = (state.assets || []).find((a) => a.name === name);
    if (!asset?.url) return;
    // 在面板内显示素材文档内容（而非跳转新页面）
    fetch(asset.url)
      .then((r) => r.ok ? r.text() : Promise.reject(new Error('加载失败')))
      .then((text) => {
        setAssetContent(text);
        selectDoc('project', `__asset__:${name}`);
      })
      .catch(() => {
        window.open(asset.url, '_blank');
      });
  }

  const fileClass = (active: boolean) =>
    `docs-file ${active ? 'active' : ''}`;

  return (
    <div class="docs-sidebar">
      <div class="docs-sidebar-header">
        <FiFileText size={14} /> 文档
        <button
          type="button"
          class="docs-close"
          title="关闭"
          onClick={closeDocsPanel}
        >
          <FiX size={14} />
        </button>
      </div>

      <div class="docs-file-list">
        {/* 项目文档 */}
        <div class="docs-section-title">📁 项目文档</div>
        <For each={state.documents || []}>
          {(d) => (
            <button
              type="button"
              class={fileClass(isActive('project', d.name))}
              onClick={() => selectDoc('project', d.name)}
            >
              <FiFileText size={12} />
              <span class="docs-file-name">{d.name}</span>
            </button>
          )}
        </For>
        <Show when={!(state.documents || []).length}>
          <div class="docs-empty">暂无（Agent 拆解时会自动产出）</div>
        </Show>

        {/* 上传素材 */}
        <div class="docs-section-title">📎 上传素材</div>
        <For each={textAssets()}>
          {(a) => (
            <button
              type="button"
              class={fileClass(false)}
              onClick={() => openAssetDoc(a.name)}
            >
              <FiFileText size={12} />
              <span class="docs-file-name">{a.name}</span>
            </button>
          )}
        </For>
        <Show when={!textAssets().length}>
          <div class="docs-empty">暂无上传的文档素材</div>
        </Show>

        {/* Skill 文档（仅展示已随消息发送给 Agent 的；新建项目为空） */}
        <div class="docs-section-title">🧩 Skill 文档</div>
        <For each={visibleSkillDocs()}>
          {(d) => (
            <button
              type="button"
              class={fileClass(isActive('skill', d.slug))}
              onClick={() => selectDoc('skill', d.slug)}
            >
              <FiZap size={12} />
              <span class="docs-file-name">{d.name}</span>
            </button>
          )}
        </For>
        <Show when={!visibleSkillDocs().length}>
          <div class="docs-empty">在 Skill 下拉点「+」并发送后写入</div>
        </Show>
      </div>

      {/* 新建文档（旧版 docs-new-btn） */}
      <Show
        when={creating()}
        fallback={
          <button
            type="button"
            class="docs-new-btn"
            onClick={() => setCreating(true)}
          >
            <FiPlus size={12} /> 新建文档
          </button>
        }
      >
        <div class="docs-rename">
          <input
            type="text"
            class="docs-rename-input"
            placeholder="文档名称.md"
            value={newName()}
            onInput={(e) => setNewName(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                setCreating(false);
                void createDoc(newName());
                setNewName('');
              }
              if (e.key === 'Escape') setCreating(false);
            }}
            ref={(el) => setTimeout(() => el.focus())}
          />
        </div>
      </Show>
    </div>
  );
}
