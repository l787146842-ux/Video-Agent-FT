import { createSignal, For, Show, onCleanup } from 'solid-js';
import { FiEye, FiZap, FiChevronDown, FiPlus, FiTrash2 } from 'solid-icons/fi';
import { state, refreshSkills } from '@/stores/studio';
import { agentSkillId, setAgentSkill } from '@/stores/agent-prefs';
import { deleteSkillDoc } from '@/api/docs';
import { showToast } from '@/stores/toast';
import { requestInsertSkill } from '@/lib/chat-input-bridge';
import { t } from '@/lib/locale';
import { SkillDetailModal } from './SkillDetailModal';
import { SkillImportModal } from './SkillImportModal';
import type { Skill } from '@/types';

/**
 * Skill 选择器（替代 PillDropdown）
 * 点击工具栏按钮弹出列表面板，每个卡片：标题/描述 + 右侧眼睛图标 + 加号按钮。
 * 点击卡片 / 加号 → 激活 Skill 并把 Skill 名称插入对话输入框，
 * 用户随消息发送后 Skill 才会真正生效并写入文档面板；点击眼睛 → 预览详情弹窗。
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
    if (ref && !ref.contains(e.target as Node)) setOpen(false);
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
      if (left + panelW > window.innerWidth - 12) {
        left = window.innerWidth - panelW - 12;
      }
      if (left < 12) left = 12;
      setPanelStyle({
        left: `${left}px`,
        bottom: `${window.innerHeight - rect.top + 6}px`,
      });
    }
    setOpen(!open());
  }

  /**
   * 「+」/ 卡片点击：激活 Skill 并把名称以引用块（图标+名称 chip）插入对话输入框。
   * 只有随消息发送给 Agent 后，Skill 才会真正生效并写入文档面板（图4）。
   */
  function insertSkillToInput(skill: Skill) {
    setAgentSkill(skill.id);
    requestInsertSkill(skill.name);
    setOpen(false);
    showToast(t('rp.skill.inserted', { name: skill.name }), 'success');
  }

  /** 是否为文档类 Skill（只有 doc 来源可删除） */
  function isDocSkill(skill: Skill): boolean {
    return skill.id.startsWith('doc:') || (skill.source as string) === 'doc';
  }

  async function doDeleteSkill(skill: Skill) {
    const slug = (skill.slug as string) || skill.id.replace(/^doc:/, '');
    setConfirmingId(null);
    try {
      await deleteSkillDoc(slug);
      await refreshSkills();
      if (agentSkillId() === skill.id) setAgentSkill('');
      showToast(t('rp.skill.deleted', { name: skill.name }), 'success');
    } catch (err) {
      showToast(t('rp.skill.deleteFailed', { error: (err as Error).message }), 'error');
    }
  }

  return (
    <div class="pill-anchor" ref={ref}>
      <button
        type="button"
        class="toolbar-pill-btn max-w-36"
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
          <For each={state.skills}>
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
