import { createSignal, Show } from 'solid-js';
import { FiX, FiUpload, FiZap, FiRefreshCw } from 'solid-icons/fi';
import { saveSkillDoc } from '@/api/docs';
import { showToast } from '@/stores/toast';
import { refreshSkills } from '@/stores/studio';

/**
 * Skill 导入弹窗
 * 支持粘贴 markdown 内容或上传 .md/.txt 文件，可选 AI 整理格式，保存后即时生效。
 */
export function SkillImportModal(props: {
  onClose: () => void;
}) {
  const [content, setContent] = createSignal('');
  const [slug, setSlug] = createSignal('');
  const [saving, setSaving] = createSignal(false);
  let fileRef: HTMLInputElement | undefined;

  /** 从内容中自动提取 slug（支持 # 标题 和 skill_name: "..." 两种格式） */
  function autoSlug(text: string): string {
    // 优先匹配 # 标题
    let raw = '';
    const headingMatch = text.match(/^#\s+(.+)$/m);
    if (headingMatch) {
      raw = headingMatch[1];
    } else {
      // 其次匹配 skill_name: "..." 或 skill_name: '...'
      const nameMatch = text.match(/skill_name\s*[:=]\s*["']?([^"'\n]+)/i);
      if (nameMatch) raw = nameMatch[1];
    }
    if (!raw) return '';
    return sanitizeSlug(raw);
  }

  /** 清理 slug：只保留中文/英文/数字/连字符 */
  function sanitizeSlug(raw: string): string {
    return raw
      .trim()
      .replace(/[\s_]+/g, '-')
      .replace(/[^\w\u4e00-\u9fff-]/g, '')
      .replace(/-{2,}/g, '-')
      .replace(/^-|-$/g, '')
      .slice(0, 48);
  }

  function onContentChange(val: string) {
    setContent(val);
    // 自动生成 slug（用户未手动修改时）
    const newSlug = autoSlug(val);
    if (newSlug && (!slug() || slug() === autoSlug(content()))) {
      setSlug(newSlug);
    }
  }

  function onFileSelect(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result || '');
      onContentChange(text);
      if (!slug()) setSlug(file.name.replace(/\.[^.]+$/, '').replace(/[\s_]+/g, '-'));
    };
    reader.readAsText(file);
    input.value = '';
  }

  async function handleSave() {
    const s = sanitizeSlug(slug());
    if (!s) {
      showToast('请填写有效的 Skill 标识（中文/英文/数字/连字符）', 'error');
      return;
    }
    setSlug(s);
    if (!content().trim()) {
      showToast('内容不能为空', 'error');
      return;
    }
    setSaving(true);
    try {
      await saveSkillDoc(s, content());
      await refreshSkills();
      showToast(`Skill「${s}」已导入`, 'success');
      props.onClose();
    } catch (err) {
      showToast(`保存失败：${(err as Error).message}`, 'error');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div class="skill-modal-backdrop" onClick={(e) => {
      if (e.target === e.currentTarget) props.onClose();
    }}>
      <div class="skill-modal skill-import-modal">
        {/* 顶部 */}
        <div class="skill-modal-header">
          <div class="skill-modal-title" style={{ padding: 0 }}>导入 Skill</div>
          <button type="button" class="skill-modal-close" onClick={props.onClose}>
            <FiX size={16} />
          </button>
        </div>

        {/* 内容区 */}
        <div class="skill-import-body">
          {/* 工具行：上传 */}
          <div class="skill-import-toolbar">
            <button
              type="button"
              class="skill-import-tool-btn"
              onClick={() => fileRef?.click()}
            >
              <FiUpload size={13} />
              上传文件
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".md,.txt,.markdown"
              class="hidden"
              onChange={onFileSelect}
            />
          </div>

          {/* Slug 输入 */}
          <div class="skill-import-field">
            <label class="skill-import-label">Skill 标识（文件名）</label>
            <input
              type="text"
              class="skill-import-input"
              placeholder="如 my-skill（英文/数字/连字符）"
              value={slug()}
              onInput={(e) => setSlug(e.currentTarget.value)}
            />
          </div>

          {/* 内容 textarea */}
          <div class="skill-import-field">
            <label class="skill-import-label">Skill 内容（Markdown）</label>
            <textarea
              class="skill-import-textarea"
              rows={12}
              placeholder={'粘贴 Skill 内容，或上传 .md 文件。\n\n标准格式：\n# Skill 名称\n> 调用规则：一句话说明\n## 流程规划\n...'}
              value={content()}
              onInput={(e) => onContentChange(e.currentTarget.value)}
            />
          </div>
        </div>

        {/* 底部 */}
        <div class="skill-modal-footer">
          <button
            type="button"
            class="skill-use-btn"
            disabled={saving()}
            onClick={handleSave}
          >
            <Show when={saving()} fallback={<FiZap size={14} />}>
              <FiRefreshCw size={14} class="spin" />
            </Show>
            保存 Skill
          </button>
        </div>
      </div>
    </div>
  );
}
