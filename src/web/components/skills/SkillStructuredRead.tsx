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
  /** dsh 调用策略（由调用方经 frontmatterInvocation 解析后传入；缺省 = 双可用）。 */
  invocation?: { modelInvocable: boolean; userInvocable: boolean };
}) {
  const displayName = () => props.meta?.name || props.struct.name || '（未命名）';
  const displayDesc = () => props.meta?.description || props.struct.description || '（未设置）';
  /** dsh 四组合的人类可读标签（只读；改组合在源码 frontmatter 里改）。 */
  const invocationLabel = () => {
    const { modelInvocable, userInvocable } =
      props.invocation ?? { modelInvocable: true, userInvocable: true };
    if (modelInvocable && userInvocable) return '模型可调用 · 用户可调用';
    if (modelInvocable) return '模型可调用 · 用户不可调用';
    if (userInvocable) return '用户专用（模型不可调用）';
    return '内部技能（都不可调用）';
  };
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
        {/* dsh 调用策略两开关（只读展示）：权威判定在后端注册表，
            这里只让用户看到本技能属于哪种组合（2026-11-12 对齐批）。 */}
        <div class="sks-label">调用方式</div>
        <div class="sks-box sks-box-row">
          <span>{invocationLabel()}</span>
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
