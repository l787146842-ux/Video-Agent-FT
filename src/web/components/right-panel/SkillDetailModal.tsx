import { createSignal, Show, untrack } from 'solid-js';
import { FiX, FiZap, FiEye, FiCode, FiCheck, FiCopy } from 'solid-icons/fi';
import { renderMarkdown } from '@/lib/markdown';
import { saveSkillDoc } from '@/api/docs';
import { refreshSkills } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { t } from '@/lib/locale';
import type { Skill } from '@/types';

/** 从 skill 内容中解析 skill_description 字段（简介用） */
function extractDescription(skill: Skill): string {
  const content = skill.system_prompt || '';
  // 匹配 skill_description: "..." 或 skill_description: '...'
  const match = content.match(/skill_description\s*[:=]\s*["']([^"']+)["']/i);
  if (match) return match[1];
  // 回退到 skill.description
  return skill.description || t('rp.skillDetail.noIntro');
}

/** skill_manifest 声明块（机器读的系统配置，888 事故：对外封装时不该让人看到） */
const MANIFEST_BLOCK_RE = /```(?:json|js)?\s*skill_manifest\s*\n[\s\S]*?```/i;

/** 提取 skill_manifest 声明块原文（无则返回空串） */
function extractManifest(content: string): string {
  const m = content.match(MANIFEST_BLOCK_RE);
  return m ? m[0] : '';
}

/** 从 skill 内容中提取纯流程规划部分（去掉 skill_name/skill_description/<planner> 等元数据，
 * 并隐藏 skill_manifest 声明块——它是给系统读的参数铭牌，正文视图默认折叠） */
function extractPlannerContent(skill: Skill): string {
  const content = (skill.system_prompt || '').replace(MANIFEST_BLOCK_RE, '');
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
  // 初始值只取打开时的 skill，不需响应式跟踪（untrack 显式声明非跟踪读取）
  const [introDraft, setIntroDraft] = createSignal(untrack(() => extractDescription(props.skill)));
  const [savingIntro, setSavingIntro] = createSignal(false);
  // manifest 声明块（打开时快照）：默认折叠，只在展开时可见
  const manifestBlock = untrack(() => extractManifest(props.skill.system_prompt || ''));

  /** 复制 Skill 全文到剪贴板（优先 Clipboard API，降级 execCommand） */
  async function copyContent() {
    const text = props.skill.system_prompt || '';
    if (!text) {
      showToast(t('rp.skillDetail.noContent'), 'warning');
      return;
    }
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
      }
      showToast(t('rp.skillDetail.copied'), 'success');
    } catch {
      showToast(t('rp.skillDetail.copyFailed'), 'error');
    }
  }

  /** 保存简介编辑：更新 skill 文档中的 > 引用行 */
  async function saveIntro() {
    const slug = (props.skill.slug as string) || props.skill.id.replace(/^doc:/, '');
    const content = props.skill.system_prompt || '';
    const newDesc = introDraft().trim();
    if (!newDesc) {
      showToast(t('rp.skillDetail.introEmpty'), 'error');
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
      const res = await saveSkillDoc(slug, newContent);
      await refreshSkills();
      showToast(t('rp.skillDetail.introSaved'), 'success');
      // 保存时 lint：注册断点前移到编辑时（执行器缺失/规则非法等显式告知）
      (res?.lint?.warnings || []).forEach((w) => showToast(`⚠ ${w}`, 'warning'));
    } catch (err) {
      showToast(t('rp.skillDetail.saveFailed', { error: (err as Error).message }), 'error');
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
              {t('rp.skillDetail.tabIntro')}
            </button>
            <button
              type="button"
              class={`skill-modal-tab ${tab() === 'content' ? 'active' : ''}`}
              onClick={() => setTab('content')}
            >
              {t('rp.skillDetail.tabContent')}
            </button>
          </div>
          <button type="button" class="skill-modal-close" onClick={() => props.onClose()}>
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
                {t('rp.skillDetail.saveIntro')}
              </button>
            </div>
          </Show>
          <Show when={tab() === 'content'}>
            <div class="skill-modal-view-toggle">
              <button
                type="button"
                class="skill-modal-copy-btn"
                title={t('rp.skillDetail.copy')}
                onClick={() => void copyContent()}
              >
                <FiCopy size={13} />
                {t('rp.skillDetail.copy')}
              </button>
              <button
                type="button"
                class={`skill-modal-view-btn ${!rawView() ? 'active' : ''}`}
                title={t('rp.skillDetail.renderPreview')}
                onClick={() => setRawView(false)}
              >
                <FiEye size={13} />
              </button>
              <button
                type="button"
                class={`skill-modal-view-btn ${rawView() ? 'active' : ''}`}
                title={t('rp.skillDetail.source')}
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
              {/* 高级声明折叠区（888 事故）：机器读的配置铭牌，默认隐藏，文件内容不受影响 */}
              <Show when={manifestBlock}>
                <details class="skill-modal-manifest">
                  <summary>{t('rp.skill.manifestHint')}</summary>
                  <div class="skill-modal-content-raw">{manifestBlock}</div>
                </details>
              </Show>
            </Show>
            <Show when={rawView()}>
              <div class="skill-modal-content-raw">
                {props.skill.system_prompt || t('rp.skillDetail.noContent')}
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
            {t('rp.skillDetail.use')}
          </button>
        </div>
      </div>
    </div>
  );
}
