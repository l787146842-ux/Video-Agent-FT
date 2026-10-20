import { Show } from 'solid-js';
import { FiX, FiZap } from 'solid-icons/fi';
import { state } from '@/stores/studio-core';
import {
  activateSkill, agentSkillId, dismissSkillSuggestion, suggestedSkillId,
} from '@/stores/agent-prefs';
import type { Skill } from '@/types';

/**
 * 活跃 Skill 芯片：输入框上方呈现项目态活跃 Skill 绑定
 * （含来源标注：用户选择/建议采纳）。
 *
 * 2026-10-16 用户裁决：**移除「摘除」入口**（原右侧 ✕ 按钮）——Skill 文档在
 * 文档区就是唯一权威，项目登记过的 Skill 一律生效，「关掉技能」不再是一个
 * 可用状态。该入口可被误触，且触发后十数处 Skill 门控静默失效（9999 事故）。
 * 芯片自此只作只读状态展示；未登记绑定但有全局建议值时仍以建议芯片呈现
 * （一键采纳/忽略，建议不自动激活）。
 */
export function ActiveSkillChip() {
  /** 当前**生效**的 Skill（文档区唯一权威口径，见 agentSkillId）；
   *  空 = 真正的自由对话（新项目、或项目内无任何已登记 Skill）。 */
  const effectiveId = () => agentSkillId();

  /** 生效 Skill 的展示对象：名称取文档清单，来源取项目态绑定（缺省按用户选择） */
  const activeMeta = () => {
    const id = effectiveId();
    if (!id) return null;
    const sk = state.skills.find((s) => s.id === id);
    return { name: sk?.name || id.replace(/^doc:/, ''), source: state.activeSkill?.source };
  };

  /** 建议芯片：无生效 Skill 且全局建议值有效时呈现（不自动激活） */
  const suggested = (): Skill | null => {
    if (effectiveId()) return null;
    const id = suggestedSkillId();
    if (!id) return null;
    return state.skills.find((s) => s.id === id) || null;
  };

  return (
    <>
      <Show when={activeMeta()}>
        {(meta) => (
          <div class="active-skill-chip">
            <FiZap size={11} class="active-skill-chip-icon" />
            <span class="active-skill-chip-name" title={meta().name}>{meta().name}</span>
            <span class="active-skill-chip-source">
              {meta().source === 'suggested' ? '建议采纳' : '用户选择'}
            </span>
          </div>
        )}
      </Show>
      <Show when={suggested()}>
        {(sk) => (
          <div class="active-skill-chip active-skill-chip-suggested">
            <span class="active-skill-chip-name" title={sk().name}>
              推荐技能：{sk().name}
            </span>
            <button
              type="button"
              class="active-skill-chip-adopt"
              onClick={() => void activateSkill(sk().id, 'suggested')}
            >
              采纳
            </button>
            <button
              type="button"
              class="active-skill-chip-remove"
              title="忽略建议"
              aria-label="忽略 Skill 建议"
              onClick={dismissSkillSuggestion}
            >
              <FiX size={12} />
            </button>
          </div>
        )}
      </Show>
    </>
  );
}
