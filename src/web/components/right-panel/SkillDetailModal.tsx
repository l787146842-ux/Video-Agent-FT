import { createSignal } from 'solid-js';
import { FiX, FiZap } from 'solid-icons/fi';
import { saveSkillDoc } from '@/api/docs';
import { refreshSkills, state } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { t } from '@/lib/locale';
import { useFocusTrap } from '@/lib/focus-trap';
import { SkillStructuredView } from '@/components/skills/SkillStructuredView';
import type { Skill } from '@/types';

/**
 * Skill 详情弹窗（内容统一为结构化视图：易读/Markdown + 行内编辑 + 更新落盘）。
 * 旧「简介/内容」双 tab 退役——描述在结构化视图首组行内编辑。
 */
export function SkillDetailModal(props: {
  skill: Skill;
  onClose: () => void;
  onUse: (skill: Skill) => void;
  /** 保存成功后同步父级预览对象（避免弹窗展示陈旧内容） */
  onSaved?: (skill: Skill) => void;
}) {
  // 焦点圈闭：打开圈闭、Esc 关闭、关闭还原焦点
  const [panelEl, setPanelEl] = createSignal<HTMLElement>();
  useFocusTrap(panelEl, { onEscape: () => props.onClose() });

  /** 更新落盘：保存 + lint 回显 + 刷新列表 + 同步父级 */
  async function persist(raw: string) {
    const slug = (props.skill.slug as string) || props.skill.id.replace(/^doc:/, '');
    try {
      const res = await saveSkillDoc(slug, raw);
      (res?.lint?.warnings || []).forEach((w) => showToast(`⚠ ${w}`, 'warning'));
      await refreshSkills();
      const fresh = state.skills.find((s) => s.id === props.skill.id);
      if (fresh) props.onSaved?.(fresh);
      showToast('已保存', 'success');
    } catch (err) {
      showToast(t('rp.skillDetail.saveFailed', { error: (err as Error).message }), 'error');
    }
  }

  return (
    <div class="skill-modal-backdrop" onClick={(e) => {
      if (e.target === e.currentTarget) props.onClose();
    }}>
      <div
        class="skill-modal"
        ref={setPanelEl}
        role="dialog"
        aria-modal="true"
        aria-label={`${t('rp.skillDetail.dialogAria')}：${props.skill.name}`}
      >
        {/* 顶部：标题 + 关闭 */}
        <div class="skill-modal-header">
          <div class="skill-modal-title" style={{ padding: 0 }}>{props.skill.name}</div>
          <button type="button" class="skill-modal-close" onClick={() => props.onClose()}>
            <FiX size={16} />
          </button>
        </div>

        {/* 内容：结构化视图（阅读/行内编辑/源码） */}
        <div class="skill-modal-body skill-modal-body-fill">
          <SkillStructuredView
            raw={props.skill.system_prompt || ''}
            onSave={persist}
          />
        </div>

        {/* 底部：去使用 */}
        <div class="skill-modal-footer">
          <button
            type="button"
            class="skill-use-btn"
            onClick={() => props.onUse(props.skill)}
          >
            <FiZap size={14} />
            {t('rp.skillDetail.use')}
          </button>
        </div>
      </div>
    </div>
  );
}
