import { createMemo, createSignal, Show, type JSX } from 'solid-js';
import { FiCode, FiCopy, FiEdit2, FiEye, FiMoreHorizontal } from 'solid-icons/fi';
import {
  parseSkillStructure, serializeSkillStructure, frontmatterMeta, type SkillStructure,
} from '@/lib/skill-structure';
import { saveSkillCopy } from '@/stores/skill-studio';
import { SkillStructuredRead } from './SkillStructuredRead';
import { SkillStructuredEdit } from './SkillStructuredEdit';

/**
 * Skill 结构化查看器壳（三处复用：文档面板/详情弹窗/工作台中间栏）。
 * - 易读（结构化阅读/行内编辑）↔ Markdown（源码查看/编辑）
 * - 非编辑态：编辑按钮 + … 菜单（另存为副本）
 * - 编辑态：取消/更新；更新经 onSave 落盘或 onCommit 上抛草稿
 */
export function SkillStructuredView(props: {
  /** 当前已提交的 raw markdown（单一数据源） */
  raw: string;
  /** 落盘回调（文档面板/详情弹窗）；与 onCommit 二选一 */
  onSave?: (raw: string) => Promise<void>;
  /** 草稿上抛回调（工作台：入撤销栈，不直接落盘） */
  onCommit?: (raw: string) => void;
  /** 工具栏右侧附加区（工作台放 undo/redo） */
  toolbarRight?: JSX.Element;
  /** 是否显示 … 菜单（另存为副本） */
  showCopy?: boolean;
}) {
  const [viewMode, setViewMode] = createSignal<'read' | 'md'>('read');
  const [editing, setEditing] = createSignal(false);
  const [struct, setStruct] = createSignal<SkillStructure | null>(null);
  const [rawDraft, setRawDraft] = createSignal('');
  const [menuOpen, setMenuOpen] = createSignal(false);
  const [saving, setSaving] = createSignal(false);

  const parsed = createMemo(() => parseSkillStructure(props.raw));
  // 名称/描述展示权威 = frontmatter 元数据（与后端 /api/skills 解析同口径，
  // 批 C）：正文无 `# ` 标题的文档不再显示「未命名」
  const meta = createMemo(() => frontmatterMeta(props.raw));

  function startEdit() {
    if (viewMode() === 'read') setStruct(parseSkillStructure(props.raw));
    else setRawDraft(props.raw);
    setEditing(true);
  }

  function cancelEdit() {
    setEditing(false);
    setStruct(null);
  }

  async function commit() {
    const next = viewMode() === 'read' && struct()
      ? serializeSkillStructure(struct()!)
      : rawDraft();
    setEditing(false);
    setStruct(null);
    if (next === props.raw) return;
    if (props.onSave) {
      setSaving(true);
      try { await props.onSave(next); } finally { setSaving(false); }
    } else {
      props.onCommit?.(next);
    }
  }

  return (
    <div class="sks-view">
      {/* 工具栏：易读/Markdown + 右侧附加 + 编辑/更新/取消 + … 菜单 */}
      <div class="sks-toolbar">
        <div class="sks-toggle">
          <button
            type="button"
            class={viewMode() === 'read' ? 'active' : ''}
            onClick={() => setViewMode('read')}
          >
            <FiEye size={12} /> 易读
          </button>
          <button
            type="button"
            class={viewMode() === 'md' ? 'active' : ''}
            onClick={() => setViewMode('md')}
          >
            <FiCode size={12} /> Markdown
          </button>
        </div>
        <div class="sks-spacer" />
        {props.toolbarRight}
        <Show when={!editing()}>
          <button type="button" class="sks-btn" onClick={startEdit}>
            <FiEdit2 size={12} /> 编辑
          </button>
          <Show when={props.showCopy !== false}>
            <div class="sks-menu-wrap">
              <button
                type="button"
                class="sks-btn"
                title="更多操作"
                onClick={() => setMenuOpen(!menuOpen())}
              >
                <FiMoreHorizontal size={14} />
              </button>
              <Show when={menuOpen()}>
                <div class="sks-menu">
                  <button
                    type="button"
                    onClick={() => { setMenuOpen(false); void saveSkillCopy(props.raw); }}
                  >
                    <FiCopy size={12} /> 另存为副本
                  </button>
                </div>
              </Show>
            </div>
          </Show>
        </Show>
        <Show when={editing()}>
          <button type="button" class="sks-btn" onClick={cancelEdit}>取消</button>
          <button
            type="button"
            class="sks-btn primary"
            disabled={saving()}
            onClick={() => void commit()}
          >
            更新
          </button>
        </Show>
      </div>

      {/* 内容区 */}
      <Show
        when={editing()}
        fallback={
          <Show
            when={viewMode() === 'read'}
            fallback={<pre class="sks-raw">{props.raw}</pre>}
          >
            <div class="sks-scroll">
              <SkillStructuredRead struct={parsed()} meta={meta()} />
            </div>
          </Show>
        }
      >
        <Show
          when={viewMode() === 'read'}
          fallback={
            <textarea
              class="sks-raw-edit"
              value={rawDraft()}
              onInput={(e) => setRawDraft(e.currentTarget.value)}
            />
          }
        >
          <div class="sks-scroll">
            <Show when={struct()}>
              <SkillStructuredEdit struct={struct()!} onChange={setStruct} meta={meta()} />
            </Show>
          </div>
        </Show>
      </Show>
    </div>
  );
}
