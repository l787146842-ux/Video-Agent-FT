import { createSignal, createEffect, Show, type JSX } from 'solid-js';
import {
  FiEdit2, FiSave, FiTrash2, FiX,
} from 'solid-icons/fi';
import {
  docsPanelOpen, closeDocsPanel, current,
  editing, viewMode, setViewMode, startEdit, cancelEdit,
  saveCurrentDoc, deleteDoc, currentContent, currentDisplayName,
  draftContent, setDraftContent, saveSkillDocFromPanel,
} from '@/stores/docs';
import { renderMarkdown } from '@/lib/markdown';
import { SkillStructuredView } from '@/components/skills/SkillStructuredView';
import { DocsSidebar } from './DocsSidebar';

/**
 * 文档面板（可拖拽浮窗）
 * - 非模态：无遮罩背板，打开后仍可正常操作影视工作台；只能点右上角 × 关闭
 * - 顶部栏（左栏头 + 右栏头）按住可用鼠标拖动整个窗口
 * 三段列表：项目文档 / 上传素材 / Skill 文档
 * 查看器：read（渲染）/ md（源码）切换 + 编辑保存
 */
export function DocsPanel() {
  // ===== 拖拽定位：null = 默认居中，拖动后记录窗口左上角坐标 =====
  const [pos, setPos] = createSignal<{ x: number; y: number } | null>(null);
  let panelEl: HTMLDivElement | undefined;
  let dragOffset: { dx: number; dy: number } | null = null;

  // 每次重新打开面板时回到默认居中位置
  createEffect(() => {
    if (docsPanelOpen()) setPos(null);
  });

  /** 顶部栏按下开始拖拽（忽略按钮/下拉等可交互元素上的按下） */
  const startDrag = (e: PointerEvent & { currentTarget: HTMLElement }) => {
    const target = e.target as HTMLElement;
    if (target.closest('button, select, input, textarea, a')) return;
    const el = panelEl;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    dragOffset = { dx: e.clientX - rect.left, dy: e.clientY - rect.top };
    e.preventDefault();
    const onMove = (ev: PointerEvent) => {
      if (!dragOffset || !panelEl) return;
      const w = panelEl.offsetWidth;
      const x = Math.min(
        Math.max(ev.clientX - dragOffset.dx, 8),
        Math.max(8, window.innerWidth - w - 8),
      );
      const y = Math.min(
        Math.max(ev.clientY - dragOffset.dy, 8),
        Math.max(8, window.innerHeight - 60),
      );
      setPos({ x, y });
    };
    const onUp = () => {
      dragOffset = null;
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };

  const panelStyle = (): JSX.CSSProperties | undefined => {
    const p = pos();
    return p ? { position: 'fixed', left: `${p.x}px`, top: `${p.y}px` } : undefined;
  };

  return (
    <Show when={docsPanelOpen()}>
      {/* 非模态浮窗容器：无背板，pointer-events 仅窗口本体生效 */}
      <div class="docs-panel">
        <div class="docs-panel-inner" ref={panelEl} style={panelStyle()}>
          {/* 文档列表（拆出子组件） */}
          <DocsSidebar onHeaderDrag={startDrag} />

          {/* 查看器 */}
          <div class="docs-content">
            {/* 头部：文件名 + 模式切换 + 编辑/保存 + 右上角关闭 */}
            <div class="docs-content-header" onPointerDown={startDrag}>
              <span class="docs-current-name">
                {currentDisplayName() || '未选择文档'}
              </span>
              <div class="docs-content-actions">
                <Show when={!editing() && current()?.kind === 'project'}>
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
                <Show when={current() && current()!.kind === 'project'}>
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
                {/* 关闭按钮：界面右上角，手动点 × 才关闭 */}
                <button
                  type="button"
                  class="docs-panel-close"
                  title="关闭"
                  onClick={closeDocsPanel}
                >
                  <FiX size={16} />
                </button>
              </div>
            </div>

            {/* 内容区（旧版 docs-rendered / docs-viewer / docs-editor） */}
            <Show
              when={current()}
              fallback={<div class="docs-empty centered">从左侧选择文档</div>}
            >
              <Show
                when={current()!.kind === 'skill'}
                fallback={
                  <Show
                    when={editing()}
                    fallback={
                      <Show
                        when={viewMode() === 'read'}
                        fallback={
                          <pre class="docs-viewer">{currentContent()}</pre>
                        }
                      >
                        <div
                          class="docs-rendered"
                          innerHTML={renderMarkdown(currentContent())}
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
                }
              >
                {/* Skill 文档：结构化视图（易读/Markdown + 行内编辑 + 另存为副本） */}
                <SkillStructuredView
                  raw={currentContent()}
                  onSave={(raw) => saveSkillDocFromPanel(current()!.key, raw)}
                />
              </Show>
            </Show>
          </div>
        </div>
      </div>
    </Show>
  );
}
