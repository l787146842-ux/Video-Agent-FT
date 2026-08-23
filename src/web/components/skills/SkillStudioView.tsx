import { createMemo, createSignal, onCleanup, onMount, Show } from 'solid-js';
import {
  FiChevronRight, FiCornerUpLeft, FiCornerUpRight, FiSave,
} from 'solid-icons/fi';
import {
  allDocs, selectedSlug, draftRaw, dirty, commitDraft, saveDraft,
  undoDraft, redoDraft, canUndo, canRedo, loadAllDocs, newDraft, resetAssistant,
  selectSkill, studioLoading,
} from '@/stores/skill-studio';
import { parseSkillStructure } from '@/lib/skill-structure';
import { useSplitter } from '@/hooks/use-splitter';
import { Splitter } from '@/components/layout/Splitter';
import { SkillStructuredView } from './SkillStructuredView';
import { SkillStudioList } from './SkillStudioList';
import { SkillAssistantPanel } from './SkillAssistantPanel';

const KEY_LEFT_COLLAPSED = 'skstLeftCollapsed';

/**
 * Skill 工作台（/skills 路由）三栏：
 * 左 全部 Skill 列表（加入/删除/新建）｜ 中 结构化预览/编辑（撤销/保存）｜
 * 右 优化助手对话（会话级）。
 */
export default function SkillStudioView() {
  // 助手栏宽：280-650px，向左拖变宽（对齐影视工作台右栏手感，持久化）
  const assistantSplit = useSplitter(360, {
    min: 280, max: 650, invert: true, storageKey: 'splitSkillAssistant',
  });
  // 左栏收起态（持久化）：收起后以窄条按钮展开
  const [leftCollapsed, setLeftCollapsed] = createSignal(
    localStorage.getItem(KEY_LEFT_COLLAPSED) === '1',
  );
  function toggleLeft() {
    const next = !leftCollapsed();
    setLeftCollapsed(next);
    localStorage.setItem(KEY_LEFT_COLLAPSED, next ? '1' : '0');
  }

  onMount(async () => {
    await loadAllDocs();
    // 首次进入：默认选中第一个 Skill；空库则新建草稿
    if (!selectedSlug() && !draftRaw()) {
      const first = allDocs()[0];
      if (first) {
        selectSkill(first.slug);
      } else {
        newDraft();
      }
    }
  });
  // 离开路由清空助手会话（会话级不持久化）
  onCleanup(() => resetAssistant());

  const draftName = createMemo(() => {
    if (studioLoading()) return '…';
    // 草稿改名未保存时面包屑跟随草稿（左栏列表仍展示落盘名）
    if (dirty()) return parseSkillStructure(draftRaw()).name || '未命名';
    if (selectedSlug()) {
      return allDocs().find((d) => d.slug === selectedSlug())?.name || '';
    }
    return parseSkillStructure(draftRaw()).name || '新建草稿';
  });

  return (
    <div class="skill-studio">
      <Show
        when={!leftCollapsed()}
        fallback={
          <button
            type="button"
            class="panel-reopen-col"
            title="展开 Skill 列表"
            onClick={toggleLeft}
          >
            <FiChevronRight size={14} />
          </button>
        }
      >
        <SkillStudioList onCollapse={toggleLeft} />
      </Show>

      {/* 中间：面包屑 + 保存/撤销 + 结构化视图 */}
      <div class="skst-center">
        <div class="skst-center-header">
          <span class="skst-crumb">我的Skill</span>
          <span class="skst-crumb-sep">›</span>
          <span class="skst-crumb-name">
            {draftName()}
            <Show when={dirty()}>
              <span class="skst-dirty" title="未保存">●</span>
            </Show>
          </span>
          <div class="sks-spacer" />
          <button
            type="button"
            class="sks-btn primary"
            disabled={!dirty() && !!selectedSlug()}
            onClick={() => void saveDraft()}
          >
            <FiSave size={12} /> 保存
          </button>
        </div>
        <SkillStructuredView
          raw={draftRaw()}
          onCommit={commitDraft}
          toolbarRight={
            <div class="skst-undo-redo">
              <button
                type="button"
                class="sks-btn"
                title="撤销"
                disabled={!canUndo()}
                onClick={undoDraft}
              >
                <FiCornerUpLeft size={12} />
              </button>
              <button
                type="button"
                class="sks-btn"
                title="重做"
                disabled={!canRedo()}
                onClick={redoDraft}
              >
                <FiCornerUpRight size={12} />
              </button>
            </div>
          }
        />
      </div>

      {/* 中栏与助手栏拖拽分界（同影视工作台） */}
      <Splitter split={assistantSplit} />
      <div class="skst-assistant" style={{ width: `${assistantSplit.size()}px` }}>
        <SkillAssistantPanel />
      </div>
    </div>
  );
}
