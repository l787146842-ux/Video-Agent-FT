import { For, Show } from 'solid-js';
import { renderMarkdown } from '@/lib/markdown';
import { sectionMeta, type SkillStructure } from '@/lib/skill-structure';

/**
 * Skill 结构化阅读模式：分级大标题 + 正文 markdown 渲染。
 * 首组「Skill调用规则」含名称/描述只读盒（描述带 n/200 计数）。
 */
export function SkillStructuredRead(props: { struct: SkillStructure }) {
  return (
    <div class="skill-structured">
      <section class="sks-group">
        <h2 class="sks-h2">Skill调用规则</h2>
        <p class="sks-hint">当开启多个 Skill 时，告诉 AI 在什么情况下应该调用这个 Skill。</p>
        <div class="sks-label">Skill 名称</div>
        <div class="sks-box">{props.struct.name || '（未命名）'}</div>
        <div class="sks-label">Skill调用规则</div>
        <div class="sks-box sks-box-row">
          <span>{props.struct.description || '（未设置）'}</span>
          <span class="sks-count">{props.struct.description.length}/200</span>
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
