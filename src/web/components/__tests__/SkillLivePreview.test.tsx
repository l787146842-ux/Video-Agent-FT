/**
 * 中间实时预览：生成中的部分文档按 Markdown 标题分节出现，
 * 顶部横幅显示生成状态与字数。
 */
import { render } from '@solidjs/testing-library';
import { describe, it, expect } from 'vitest';
import { SkillLivePreview } from '../skills/SkillLivePreview';

const PARTIAL = [
  '---',
  'name: 甲',
  'description: 乙',
  '---',
  '# 甲',
  '',
  '## 制作流程',
  '',
  '流程正文',
  '',
  '## 组装导出',
  '',
  '还没写完',
].join('\n');

describe('SkillLivePreview 生成中预览', () => {
  it('显示生成横幅与标题章节', () => {
    const { container } = render(() => <SkillLivePreview raw={PARTIAL} />);
    expect(container.textContent).toContain('AI 正在生成 Skill 草稿');
    expect(container.textContent).toContain(PARTIAL.length.toLocaleString());
    expect(container.textContent).toContain('制作流程');
    expect(container.textContent).toContain('流程正文');
    expect(container.textContent).toContain('组装导出');
  });

  it('空内容显示等待提示', () => {
    const { container } = render(() => <SkillLivePreview raw="" />);
    expect(container.textContent).toContain('正在等待模型输出文档');
  });
});
