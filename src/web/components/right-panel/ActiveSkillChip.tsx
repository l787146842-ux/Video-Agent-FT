import { Show } from 'solid-js';
import { FiX, FiZap } from 'solid-icons/fi';
import { state } from '@/stores/studio-core';
import {
  activateSkill, deactivateSkill, dismissSkillSuggestion, suggestedSkillId,
} from '@/stores/agent-prefs';
import type { Skill } from '@/types';

/**
 * 活跃 Skill 芯片（批 C）：输入框上方呈现项目态活跃 Skill 绑定
 * （含来源标注：用户选择/建议采纳），摘除 = 回到自由对话（写项目态 + 留痕）。
 * 未登记绑定但有全局建议值时以建议芯片呈现：一键采纳/忽略，
 * 建议不自动激活——新项目默认自由对话。
 */
export function ActiveSkillChip() {
  /** 项目态活跃绑定（含摘除态空 slug 与存量项目 null 三态） */
  const activeBinding = () => state.activeSkill;

  /** 活跃绑定的展示对象：优先文档清单名，清单未加载回落 slug */
  const activeMeta = () => {
    const a = activeBinding();
    if (!a || !a.slug) return null;
    const sk = state.skills.find((s) => s.id === `doc:${a.slug}`);
    return { name: sk?.name || a.slug, source: a.source };
  };

  /** 建议芯片：无绑定登记且全局建议值有效时呈现（不自动激活） */
  const suggested = (): Skill | null => {
    if (activeBinding()) return null;
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
            <button
              type="button"
              class="active-skill-chip-remove"
              title="摘除（回到自由对话）"
              aria-label="摘除活跃 Skill"
              onClick={() => void deactivateSkill()}
            >
              <FiX size={12} />
            </button>
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
