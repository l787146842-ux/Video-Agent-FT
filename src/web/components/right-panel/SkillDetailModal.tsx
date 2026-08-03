import { createSignal, Show } from 'solid-js';
import { FiX, FiZap, FiEye, FiCode, FiCheck } from 'solid-icons/fi';
import { renderMarkdown } from '@/lib/markdown';
import { saveSkillDoc } from '@/api/docs';
import { refreshSkills } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import type { Skill } from '@/types';

/** 从 skill 内容中解析 skill_description 字段（简介用） */
function extractDescription(skill: Skill): string {
  const content = skill.system_prompt || '';
  // 匹配 skill_description: "..." 或 skill_description: '...'
  const match = content.match(/skill_description\s*[:=]\s*["']([^"']+)["']/i);
  if (match) return match[1];
  // 回退到 skill.description
  return skill.description || '暂无简介';
}

/** 从 skill 内容中提取纯流程规划部分（去掉 skill_name/skill_description/<planner> 等元数据） */
function extractPlannerContent(skill: Skill): string {
  const content = skill.system_prompt || '';
  // 去掉 skill_name: ... 和 skill_description: ... 行
  const cleaned = content
    .replace(/^\s*skill_name\s*[:=].*$/gim, '')
    .replace(/^\s*skill_description\s*[:=].*$/gim, '')
    .replace(/<\/?planner>/gi, '')
    .trim();
  // 如果清理后为空，回退到原文
  return cleaned || content;
}

/**
 * Skill 详情弹窗（对齐 Flova AI 风格）
 * 双标签页："简介"（description）/ "内容"（system_prompt markdown 渲染）
 * 底部"去使用 Skill"渐变按钮 → 激活该 Skill
 */
export function SkillDetailModal(props: {
  skill: Skill;
  onClose: () => void;
  onUse: (skill: Skill) => void;
}) {
  const [tab, setTab] = createSignal<'intro' | 'content'>('intro');
  const [rawView, setRawView] = createSignal(false);
  const [introDraft, setIntroDraft] = createSignal(extractDescription(props.skill));
  const [savingIntro, setSavingIntro] = createSignal(false);

  /** 保存简介编辑：更新 skill 文档中的 > 引用行 */
  async function saveIntro() {
    const slug = (props.skill.slug as string) || props.skill.id.replace(/^doc:/, '');
    const content = props.skill.system_prompt || '';
    const newDesc = introDraft().trim();
    if (!newDesc) {
      showToast('简介不能为空', 'error');
      return;
    }
    // 替换原文中的 > 引用行（描述行）
    const lines = content.split('\n');
    const firstQuoteIdx = lines.findIndex((l) => l.trimStart().startsWith('>'));
    if (firstQuoteIdx >= 0) {
      // 找到连续的 > 行范围
      let endIdx = firstQuoteIdx;
      while (endIdx + 1 < lines.length && lines[endIdx + 1].trimStart().startsWith('>')) endIdx++;
      // 用新描述替换
      const newLines = newDesc.split('\n').map((l) => `> ${l}`);
      lines.splice(firstQuoteIdx, endIdx - firstQuoteIdx + 1, ...newLines);
    } else {
      // 没有 > 行，在标题后插入
      const titleIdx = lines.findIndex((l) => l.startsWith('# '));
      const insertAt = titleIdx >= 0 ? titleIdx + 1 : 0;
      lines.splice(insertAt, 0, '', `> ${newDesc}`);
    }
    const newContent = lines.join('\n');
    setSavingIntro(true);
    try {
      await saveSkillDoc(slug, newContent);
      await refreshSkills();
      showToast('简介已保存', 'success');
    } catch (err) {
      showToast(`保存失败：${(err as Error).message}`, 'error');
    } finally {
      setSavingIntro(false);
    }
  }

  return (
    <div class="skill-modal-backdrop" onClick={(e) => {
      if (e.target === e.currentTarget) props.onClose();
    }}>
      <div class="skill-modal">
        {/* 顶部：标签页 + 关闭按钮 */}
        <div class="skill-modal-header">
          <div class="skill-modal-tabs">
            <button
              type="button"
              class={`skill-modal-tab ${tab() === 'intro' ? 'active' : ''}`}
              onClick={() => setTab('intro')}
            >
              简介
            </button>
            <button
              type="button"
              class={`skill-modal-tab ${tab() === 'content' ? 'active' : ''}`}
              onClick={() => setTab('content')}
            >
              内容
            </button>
          </div>
          <button type="button" class="skill-modal-close" onClick={props.onClose}>
            <FiX size={16} />
          </button>
        </div>

        {/* 标题 */}
        <div class="skill-modal-title">{props.skill.name}</div>

        {/* 内容区 */}
        <div class="skill-modal-body">
          <Show when={tab() === 'intro'}>
            <div class="skill-modal-intro">
              <textarea
                class="skill-modal-intro-editor"
                rows={4}
                value={introDraft()}
                onInput={(e) => setIntroDraft(e.currentTarget.value)}
              />
              <button
                type="button"
                class="skill-modal-intro-save"
                disabled={savingIntro()}
                onClick={() => void saveIntro()}
              >
                <FiCheck size={12} />
                保存简介
              </button>
            </div>
          </Show>
          <Show when={tab() === 'content'}>
            <div class="skill-modal-view-toggle">
              <button
                type="button"
                class={`skill-modal-view-btn ${!rawView() ? 'active' : ''}`}
                title="渲染预览"
                onClick={() => setRawView(false)}
              >
                <FiEye size={13} />
              </button>
              <button
                type="button"
                class={`skill-modal-view-btn ${rawView() ? 'active' : ''}`}
                title="源码"
                onClick={() => setRawView(true)}
              >
                <FiCode size={13} />
              </button>
            </div>
            <Show when={!rawView()}>
              <div
                class="skill-modal-content chat-markdown"
                innerHTML={renderMarkdown(extractPlannerContent(props.skill))}
              />
            </Show>
            <Show when={rawView()}>
              <div class="skill-modal-content-raw">
                {props.skill.system_prompt || '暂无内容'}
              </div>
            </Show>
          </Show>
        </div>

        {/* 底部按钮 */}
        <div class="skill-modal-footer">
          <button
            type="button"
            class="skill-use-btn"
            onClick={() => props.onUse(props.skill)}
          >
            <FiZap size={14} />
            去使用 Skill
          </button>
        </div>
      </div>
    </div>
  );
}
