import { createSignal, For, Show } from 'solid-js';
import { FiMaximize2, FiMinimize2 } from 'solid-icons/fi';
import {
  sectionMeta, type SkillSection, type SkillStructure,
} from '@/lib/skill-structure';

/**
 * Skill 结构化行内编辑模式：名称输入框 / 描述 textarea（200 限）/
 * 各章节自适应 textarea（可展开）。修改经 onChange 上抛结构化草稿。
 */
export function SkillStructuredEdit(props: {
  struct: SkillStructure;
  onChange: (next: SkillStructure) => void;
}) {
  const set = (patch: Partial<SkillStructure>) =>
    props.onChange({ ...props.struct, ...patch });

  const setSectionBody = (idx: number, body: string) => {
    const sections = props.struct.sections.map((s, i) => (i === idx ? { ...s, body } : s));
    set({ sections });
  };

  return (
    <div class="skill-structured">
      <section class="sks-group">
        <h2 class="sks-h2">Skill调用规则</h2>
        <p class="sks-hint">当开启多个 Skill 时，告诉 AI 在什么情况下应该调用这个 Skill。</p>
        <div class="sks-label">Skill 名称</div>
        <input
          class="sks-input"
          value={props.struct.name}
          placeholder="Skill 名称"
          onInput={(e) => set({ name: e.currentTarget.value })}
        />
        <div class="sks-label">Skill调用规则</div>
        <div class="sks-edit-desc">
          <textarea
            class="sks-input sks-textarea"
            rows={2}
            maxLength={200}
            value={props.struct.description}
            placeholder="一句话说明何时使用本 Skill"
            onInput={(e) => set({ description: e.currentTarget.value })}
          />
          <span class="sks-count">{props.struct.description.length}/200</span>
        </div>
      </section>
      <For each={props.struct.sections}>
        {(sec, i) => (
          <SectionEditor sec={sec} onBody={(b) => setSectionBody(i(), b)} />
        )}
      </For>
    </div>
  );
}

/** 单章节编辑器：自适应行数 + 右上角展开/收起 */
function SectionEditor(props: { sec: SkillSection; onBody: (body: string) => void }) {
  const [expanded, setExpanded] = createSignal(false);
  const meta = () => sectionMeta(props.sec);
  const rows = () => {
    const lines = props.sec.body.split('\n').length + 1;
    return Math.min(Math.max(lines, 4), expanded() ? 40 : 14);
  };
  return (
    <section class="sks-group">
      <h2 class="sks-h2">{meta().label}</h2>
      <Show when={meta().hint}>
        <p class="sks-hint">（{meta().hint}）</p>
      </Show>
      <div class="sks-ta-wrap">
        <textarea
          class="sks-input sks-textarea"
          rows={rows()}
          value={props.sec.body}
          onInput={(e) => props.onBody(e.currentTarget.value)}
        />
        <button
          type="button"
          class="sks-expand"
          title={expanded() ? '收起' : '展开'}
          onClick={() => setExpanded(!expanded())}
        >
          {expanded() ? <FiMinimize2 size={12} /> : <FiMaximize2 size={12} />}
        </button>
      </div>
    </section>
  );
}
