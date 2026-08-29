import { createSignal, For, Show, onCleanup } from 'solid-js';
import { FiEye, FiZap, FiChevronDown, FiPlus, FiTrash2 } from 'solid-icons/fi';
import { state, refreshSkills } from '@/stores/studio';
import { agentSkillId, activateSkill, deactivateSkill, setAgentSkill } from '@/stores/agent-prefs';
import { chatActions } from '@/stores/chat';
import { editorToPlainText } from '@/lib/rich-input';
import { deleteSkillDoc } from '@/api/docs';
import { showToast } from '@/stores/toast';
import { requestInsertSkill } from '@/lib/chat/chat-input-bridge';
import { isSkillEnabled } from '@/stores/skill-prefs';
import { t } from '@/lib/locale';
import { SkillDetailModal } from './SkillDetailModal';
import { SkillImportModal } from './SkillImportModal';
import { SkillStyleLayers } from './SkillStyleLayers';
import type { Skill } from '@/types';

/**
 * Skill 选择器（替代 PillDropdown）：卡片列表 + 眼睛预览 + 加号/卡片点击
 * 激活并插入输入框（随消息发送后生效）；风格层多选区见 SkillStyleLayers。
 */
export function SkillPicker() {
  const [open, setOpen] = createSignal(false);
  const [previewSkill, setPreviewSkill] = createSignal<Skill | null>(null);
  const [importOpen, setImportOpen] = createSignal(false);
  const [panelStyle, setPanelStyle] = createSignal<Record<string, string>>({});
  /** 正在确认删除的 skill id（内联二次确认，替代原生 confirm） */
  const [confirmingId, setConfirmingId] = createSignal<string | null>(null);
  let ref: HTMLDivElement | undefined;
  let btnRef: HTMLButtonElement | undefined;

  function onDocClick(e: MouseEvent) {
    if (!ref) return;
    // （审核）：composedPath 取派发瞬间路径——删除按钮点击会同步换卡重渲染，
    // 旧 e.target 脱 DOM 后 ref.contains 误判「面板外」导致面板误关
    const path = e.composedPath();
    if (path.includes(ref)) return;
    if (confirmingId()) return; // 双保险：确认删除态不关面板
    setOpen(false);
  }
  document.addEventListener('click', onDocClick);
  onCleanup(() => document.removeEventListener('click', onDocClick));

  const currentLabel = () => t('rp.toolbar.skill');

  function toggleOpen() {
    if (!open() && btnRef) {
      const rect = btnRef.getBoundingClientRect();
      // 面板在按钮上方展开，水平左对齐按钮，且不超出视口
      const panelW = 300;
      let left = rect.left;
      if (left + panelW > window.innerWidth - 12) left = window.innerWidth - panelW - 12;
      if (left < 12) left = 12;
      setPanelStyle({ left: `${left}px`, bottom: `${window.innerHeight - rect.top + 6}px` });
    }
    setOpen(!open());
  }

  /** 「+」/卡片点击：激活（写项目态 + 后端留痕，批 C）并把名称以引用块插入输入框 */
  function insertSkillToInput(skill: Skill) {
    void activateSkill(skill.id, 'user');
    requestInsertSkill(skill.name);
    setOpen(false);
    showToast(t('rp.skill.inserted', { name: skill.name }), 'success');
  }

  /** 是否为文档类 Skill（只有 doc 来源可删除） */
  function isDocSkill(skill: Skill): boolean {
    return skill.id.startsWith('doc:') || (skill.source as string) === 'doc';
  }

  /** 仅展示已启用的 Skill（启停开关见 Skill 工作台左栏，批7） */
  const visibleSkills = () => state.skills.filter((s) => isSkillEnabled((s.slug as string) || s.id.replace(/^doc:/, '')));

  /** 任务 #11 组合激活：主流程候选（风格型另走风格层多选区；未声明 kind 按流程型） */
  const pipelineSkills = () => visibleSkills().filter((s) => (s.kind || '') !== 'style');

  async function doDeleteSkill(skill: Skill) {
    const slug = (skill.slug as string) || skill.id.replace(/^doc:/, '');
    setConfirmingId(null);
    try {
      await deleteSkillDoc(slug);
      await refreshSkills();
      if (agentSkillId() === skill.id) void deactivateSkill();
      // 已删文档不再可作建议（建议值与文档清单同源校验）
      setAgentSkill('');
      showToast(t('rp.skill.deleted', { name: skill.name }), 'success');
    } catch (err) {
      showToast(t('rp.skill.deleteFailed', { error: (err as Error).message }), 'error');
    }
  }

  return (
    <div class="pill-anchor" ref={ref}>
      <button
        type="button"
        class="toolbar-pill-btn pill-bounded"
        title={t('rp.skill.title')}
        ref={btnRef}
        onClick={toggleOpen}
      >
        <FiZap size={11} />
        <span class="pill-option-label">{currentLabel()}</span>
        <FiChevronDown size={10} class="pill-chevron" />
      </button>

      <Show when={open()}>
        <div class="skill-picker" style={panelStyle()}>
          {/* B4/F28·D2：「不使用技能」卡——摘除项目态绑定回到自由对话（批 C）。
              同时清空输入框里已插入的 Skill 引用块（防正文匹配回退重新绑定） */}
          <div
            class={`skill-picker-card skill-picker-none ${agentSkillId() === '' ? 'active' : ''}`}
            onClick={() => {
              void deactivateSkill();
              const editor = document.getElementById('chatInputTextarea');
              if (editor) {
                editor.querySelectorAll('.skill-chip').forEach((n) => n.remove());
                chatActions.setInput(editorToPlainText(editor as HTMLDivElement));
              }
              setOpen(false);
            }}
          >
            <div class="skill-picker-info">
              <span class="skill-picker-name">{t('rp.skill.noneOption')}</span>
              <span class="skill-picker-desc">{t('rp.skill.noneOptionHint')}</span>
            </div>
          </div>
          <For each={pipelineSkills()}>
            {(skill) => (
              <div
                class={`skill-picker-card ${skill.id === agentSkillId() ? 'active' : ''}`}
                onClick={() => insertSkillToInput(skill)}
              >
                <Show when={confirmingId() === skill.id}
                  fallback={
                    <>
                      <div class="skill-picker-info">
                        <span class="skill-picker-name">{skill.name}</span>
                        {/* 含规划级执行器（不产真实媒体）的 Skill 据实标注 */}
                        <Show when={(skill.planning_executors || []).length > 0}>
                          <span class="skill-planning-badge" title="含规划级执行器：该阶段只产出规划/方案文本，不产生真实媒体文件">含规划级阶段</span>
                        </Show>
                        <Show when={skill.description}>
                          <span class="skill-picker-desc">{skill.description}</span>
                        </Show>
                      </div>
                      <button
                        type="button"
                        class="skill-picker-eye"
                        title={t('rp.skill.preview')}
                        onClick={(e) => {
                          e.stopPropagation();
                          setPreviewSkill(skill);
                        }}
                      >
                        <FiEye size={14} />
                      </button>
                      <button
                        type="button"
                        class="skill-picker-add"
                        title={t('rp.skill.insertTip')}
                        onClick={(e) => {
                          e.stopPropagation();
                          insertSkillToInput(skill);
                        }}
                      >
                        <FiPlus size={14} />
                      </button>
                      <Show when={isDocSkill(skill)}>
                        <button
                          type="button"
                          class="skill-picker-delete"
                          title={t('rp.skill.delete')}
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirmingId(skill.id);
                          }}
                        >
                          <FiTrash2 size={13} />
                        </button>
                      </Show>
                    </>
                  }
                >
                  {/* 内联删除确认 */}
                  <div class="skill-picker-confirm">
                    <span class="skill-picker-confirm-text">{t('rp.skill.confirmDelete', { name: skill.name })}</span>
                    <button
                      type="button"
                      class="skill-picker-confirm-yes"
                      onClick={(e) => { e.stopPropagation(); void doDeleteSkill(skill); }}
                    >
                      {t('rp.skill.confirm')}
                    </button>
                    <button
                      type="button"
                      class="skill-picker-confirm-no"
                      onClick={(e) => { e.stopPropagation(); setConfirmingId(null); }}
                    >
                      {t('rp.skill.cancel')}
                    </button>
                  </div>
                </Show>
              </div>
            )}
          </For>
          <Show when={!state.skills.length}>
            <div class="empty-state">{t('rp.skill.none')}</div>
          </Show>
          <Show when={state.skills.length > 0 && visibleSkills().length === 0}>
            <div class="empty-state">暂无已加入的 Skill，请到顶栏「Skill 工作台」加入</div>
          </Show>
          {/* 任务 #11：风格层多选区（1 pipeline 可选 + N style 层，拆分组件守行数红线） */}
          <SkillStyleLayers onPreview={setPreviewSkill} />
          {/* 导入按钮 */}
          <div
            class="skill-picker-import"
            onClick={(e) => {
              e.stopPropagation();
              setOpen(false);
              setImportOpen(true);
            }}
          >
            <FiPlus size={13} />
            <span>{t('rp.skill.import')}</span>
          </div>
        </div>
      </Show>

      {/* Skill 详情预览弹窗 */}
      <Show when={previewSkill()}>
        <SkillDetailModal
          skill={previewSkill()!}
          onClose={() => setPreviewSkill(null)}
          onSaved={(s) => setPreviewSkill(s)}
          onUse={(skill) => {
            insertSkillToInput(skill);
            setPreviewSkill(null);
          }}
        />
      </Show>

      {/* Skill 导入弹窗 */}
      <Show when={importOpen()}>
        <SkillImportModal onClose={() => setImportOpen(false)} />
      </Show>
    </div>
  );
}
