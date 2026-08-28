import { For, Show } from 'solid-js';
import { FiEye, FiCheck } from 'solid-icons/fi';
import { state } from '@/stores/studio';
import { agentSkillId, isStyleLayerActive, toggleStyleLayer, skillSlugOf } from '@/stores/agent-prefs';
import { showToast } from '@/stores/toast';
import { isSkillEnabled } from '@/stores/skill-prefs';
import { t } from '@/lib/locale';
import type { Skill } from '@/types';

/**
 * 风格层多选区（任务 #11：1 pipeline 可选 + N style 层组合激活）。
 * 仅列 kind=style 且已加入可用集的 Skill；勾选经 toggleStyleLayer
 * 全量替换式写项目态清单（乐观写 + 失败回滚，见 stores/agent-prefs）。
 * 与主流程互斥：该 Skill 已是当前主流程时提示并拒绝勾选（后端同口径）。
 */
export function SkillStyleLayers(props: { onPreview: (skill: Skill) => void }) {
  const styleSkills = () =>
    state.skills.filter((s) => (s.kind || '') === 'style' && isSkillEnabled(skillSlugOf(s)));

  return (
    <Show when={styleSkills().length > 0}>
      <div class="skill-picker-style-header">
        <span class="skill-picker-style-title">{t('rp.skill.styleSection')}</span>
        <span class="skill-picker-style-hint">{t('rp.skill.styleSectionHint')}</span>
      </div>
      <For each={styleSkills()}>
        {(skill) => (
          <div
            class={`skill-picker-card skill-picker-style ${isStyleLayerActive(skill) ? 'active' : ''}`}
            onClick={() => {
              // 同一 Skill 不得双占主流程与风格层（后端同口径互斥）
              if (skill.id === agentSkillId()) {
                showToast(t('rp.skill.styleAsPrimaryTip', { name: skill.name }), 'info');
                return;
              }
              void toggleStyleLayer(skill);
            }}
          >
            <span class="skill-picker-check" title={t('rp.skill.styleCheck')}>
              <Show when={isStyleLayerActive(skill)}>
                <FiCheck size={12} />
              </Show>
            </span>
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
                props.onPreview(skill);
              }}
            >
              <FiEye size={14} />
            </button>
          </div>
        )}
      </For>
    </Show>
  );
}
