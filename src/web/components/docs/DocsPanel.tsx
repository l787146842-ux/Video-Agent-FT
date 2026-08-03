import { createSignal, createEffect, Show } from 'solid-js';
import {
  FiEdit2, FiSave, FiTrash2,
} from 'solid-icons/fi';
import {
  docsPanelOpen, closeDocsPanel, current,
  editing, viewMode, setViewMode, startEdit, cancelEdit,
  saveCurrentDoc, deleteDoc, currentContent, currentDisplayName,
  draftContent, setDraftContent, rollbackSkillDoc,
} from '@/stores/docs';
import { getSkillDocHistory, type SkillDocVersion } from '@/api/docs';
import { renderMarkdown } from '@/lib/markdown';
import { SkillHistoryControls } from './SkillHistoryControls';
import { DocsSidebar } from './DocsSidebar';

/**
 * 文档面板（右侧覆盖层）
 * 三段列表：项目文档 / 上传素材 / Skill 文档
 * 查看器：read（渲染）/ md（源码）切换 + 编辑保存
 */
export function DocsPanel() {
  // ===== Skill 文档历史版本（查看/回滚） =====
  const [historyVersions, setHistoryVersions] = createSignal<SkillDocVersion[]>([]);
  const [selectedVersion, setSelectedVersion] = createSignal('');

  // 切换到 Skill 文档时加载历史版本；其他文档清空
  createEffect(() => {
    const cur = current();
    setSelectedVersion('');
    if (cur?.kind === 'skill') {
      getSkillDocHistory(cur.key)
        .then(setHistoryVersions)
        .catch(() => setHistoryVersions([]));
    } else {
      setHistoryVersions([]);
    }
  });

  /** 当前展示内容：选中历史版本时展示旧版，否则展示当前版 */
  const displayContent = () => {
    const sel = selectedVersion();
    if (sel) {
      const hit = historyVersions().find((v) => v.version === sel);
      if (hit) return hit.content;
    }
    return currentContent();
  };

  return (
    <Show when={docsPanelOpen()}>
      {/* 旧版 docs-panel：居中模态（点击背板关闭） */}
      <div
        class="docs-panel"
        onClick={(e) => e.target === e.currentTarget && closeDocsPanel()}
      >
        <div class="docs-panel-inner">
          {/* 文档列表（拆出子组件） */}
          <DocsSidebar />

          {/* 查看器 */}
          <div class="docs-content">
            {/* 头部：文件名 + 模式切换 + 编辑/保存 */}
            <div class="docs-content-header">
              <span class="docs-current-name">
                {currentDisplayName() || '未选择文档'}
              </span>
              <div class="docs-content-actions">
                {/* Skill 文档历史版本（查看/回滚，后端保存时自动备份最近 10 版） */}
                <Show when={!editing() && current()?.kind === 'skill' && historyVersions().length > 0}>
                  <SkillHistoryControls
                    versions={historyVersions()}
                    selected={selectedVersion()}
                    onSelect={setSelectedVersion}
                    onRollback={(v) => {
                      if (current()) {
                        void rollbackSkillDoc(current()!.key, v.content).then(() => setSelectedVersion(''));
                      }
                    }}
                  />
                </Show>
                <Show when={!editing()}>
                  <div class="docs-mode-toggle">
                    <button
                      type="button"
                      class={viewMode() === 'read' ? 'active' : ''}
                      onClick={() => setViewMode('read')}
                    >
                      阅读
                    </button>
                    <button
                      type="button"
                      class={viewMode() === 'md' ? 'active' : ''}
                      onClick={() => setViewMode('md')}
                    >
                      源码
                    </button>
                  </div>
                </Show>
                <Show when={current()}>
                  <Show
                    when={editing()}
                    fallback={
                      <>
                        <button
                          type="button"
                          class="docs-edit-btn"
                          onClick={startEdit}
                        >
                          <FiEdit2 size={11} /> 编辑
                        </button>
                        <Show when={current()!.kind === 'project'}>
                          <button
                            type="button"
                            class="docs-delete-btn"
                            title="删除文档"
                            onClick={() => { if (confirm('确定删除此文档？')) void deleteDoc(current()!.key); }}
                          >
                            <FiTrash2 size={11} />
                          </button>
                        </Show>
                      </>
                    }
                  >
                    <button
                      type="button"
                      class="docs-save-btn"
                      onClick={() => void saveCurrentDoc()}
                    >
                      <FiSave size={11} /> 保存
                    </button>
                    <button
                      type="button"
                      class="docs-edit-btn"
                      onClick={cancelEdit}
                    >
                      取消
                    </button>
                  </Show>
                </Show>
              </div>
            </div>

            {/* 内容区（旧版 docs-rendered / docs-viewer / docs-editor） */}
            <Show
              when={current()}
              fallback={<div class="docs-empty centered">从左侧选择文档</div>}
            >
              <Show
                when={editing()}
                fallback={
                  <Show
                    when={viewMode() === 'read'}
                    fallback={
                      <pre class="docs-viewer">{displayContent()}</pre>
                    }
                  >
                    <div
                      class="docs-rendered"
                      innerHTML={renderMarkdown(displayContent())}
                    />
                  </Show>
                }
              >
                <textarea
                  class="docs-editor"
                  value={draftContent()}
                  onInput={(e) => setDraftContent(e.currentTarget.value)}
                />
              </Show>
            </Show>
          </div>
        </div>
      </div>
    </Show>
  );
}
