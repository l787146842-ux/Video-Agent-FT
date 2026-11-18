import { createMemo, Show } from 'solid-js';
import {
  frontmatterInvocation, frontmatterMeta, parseSkillStructure,
} from '@/lib/skill-structure';
import { SkillStructuredRead } from './SkillStructuredRead';

/**
 * AI 生成中的只读草稿预览（中间栏）：
 * 文档增量实时解析，已完成章节随流出现；工具条/编辑/保存在生成期收起，
 * 完成后由 SkillStudioView 换回正式结构化视图（content 权威覆盖草稿）。
 */
export function SkillLivePreview(props: { raw: string }) {
  const parsed = createMemo(() => parseSkillStructure(props.raw));
  const meta = createMemo(() => frontmatterMeta(props.raw));
  const hasBody = () => props.raw.trim().length > 0;
  return (
    <div class="sks-view sks-live">
      <div class="skst-live-banner">
        <span class="skst-live-dot" />
        AI 正在生成 Skill 草稿…（{props.raw.length.toLocaleString()} 字）
      </div>
      <Show
        when={hasBody()}
        fallback={<div class="skst-live-empty">正在等待模型输出文档…</div>}
      >
        <div class="sks-scroll">
          <SkillStructuredRead
            struct={parsed()}
            meta={meta()}
            invocation={frontmatterInvocation(props.raw)}
          />
        </div>
      </Show>
    </div>
  );
}
