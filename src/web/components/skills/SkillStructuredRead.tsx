import { For, Show } from 'solid-js';
import { renderMarkdown } from '@/lib/markdown';
import { sectionMeta, type SkillStructure } from '@/lib/skill-structure';

/**
 * Skill 结构化阅读模式：分级大标题 + 正文 markdown 渲染。
 * 首组「Skill调用规则」含名称/描述只读盒（描述带 n/200 计数）。
 * 名称/描述展示权威 = frontmatter 元数据（批 C，与后端解析同口径），
 * 正文 `# ` 标题/引用块仅作回落。
 */
export function SkillStructuredRead(props: {
  struct: SkillStructure;
  meta?: { name: string; description: string };
}) {
  const displayName = () => props.meta?.name || props.struct.name || '（未命名）';
  const displayDesc = () => props.meta?.description || props.struct.description || '（未设置）';
  return (
    <div class="skill-structured">
      <section class="sks-group">
        <h2 class="sks-h2">Skill调用规则</h2>
        <p class="sks-hint">当开启多个 Skill 时，告诉 AI 在什么情况下应该调用这个 Skill。</p>
        <div class="sks-label">Skill 名称</div>
        <div class="sks-box">{displayName()}</div>
        <div class="sks-label">Skill调用规则</div>
        <div class="sks-box sks-box-row">
          <span>{displayDesc()}</span>
          <span class="sks-count">{displayDesc().length}/200</span>
        </div>
      </section>
      <For each={props.struct.sections}>
        {(sec) => {
          const meta = () => sectionMeta(sec);
          return (
            <section class="sks-group">
              <h2 class="sks-h2">{meta().label}</h2>
              <Show when={meta().hint}>
                <p class="sks-hint">（{meta().hint}）</p>
              </Show>
              <div class="sks-body chat-markdown" innerHTML={renderMarkdown(sec.body)} />
            </section>
          );
        }}
      </For>
    </div>
  );
}
