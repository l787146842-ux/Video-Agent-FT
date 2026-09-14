import { createEffect, createSignal, Show } from 'solid-js';
import { FiChevronDown } from 'solid-icons/fi';
import { state, studioActions } from '@/stores/studio';
import { usePromptMention } from '@/hooks/use-prompt-mention';
import { PromptMentionPopup } from '@/components/middle-panel/PromptMentionPopup';
import { promptEditorKeyDown } from '@/components/middle-panel/prompt-editor-keys';
import {
  descChipNames, renderDescToDOM, serializeDescDOM, syncSceneRefsAfterEdit,
} from '@/lib/desc-ref-utils';
import type { ShotGroup } from '@/types';

/**
 * 分镜正文编辑器（对齐 Flova）：
 * - 读态：默认折叠两行，正文中本镜 sceneRefs 提及的关键元素渲染为内联块
 *   （块 = sceneRefs 在正文中的视图；点块跳转该元素）；单击展开/收起；
 * - 编辑态：双击进入（contenteditable 蓝框），块带 × 可删，打 @ 弹关键元素
 *   面板插回；失焦保存（desc 序列化回纯文本、sceneRefs 按「旧 − 正文已消失
 *   提及 + @ 插入」同步），Esc 放弃。存储格式不变（desc 纯文本）。
 */
export function ShotDescEditor(props: { group: ShotGroup }) {
  const [expanded, setExpanded] = createSignal(false);
  const [editing, setEditing] = createSignal(false);
  let bodyRef: HTMLParagraphElement | undefined;
  let editRef: HTMLDivElement | undefined;
  /** 本次编辑经 @ 插入的标题（保存时同步 sceneRefs 用） */
  let insertedTitles: string[] = [];
  /** 单击展开/收起的延迟计时器：双击时取消，避免第一击先切展开导致布局抖动、dblclick 配对失败 */
  let clickTimer: ReturnType<typeof setTimeout> | undefined;

  const desc = () => props.group.desc || '';
  const names = () => descChipNames(props.group, state.keyElements);

  /* 读态正文：desc / sceneRefs / 关键元素变化时重渲内联块 */
  createEffect(() => {
    if (editing() || !bodyRef) return;
    renderDescToDOM(bodyRef, desc(), names(), state.keyElements, false);
  });

  function enterEdit() {
    setExpanded(true);
    setEditing(true);
    insertedTitles = [];
    // 编辑 DOM 挂载后填入内容并聚焦末尾
    requestAnimationFrame(() => {
      if (!editRef) return;
      renderDescToDOM(editRef, desc(), names(), state.keyElements, true);
      const range = document.createRange();
      range.selectNodeContents(editRef);
      range.collapse(false);
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(range);
      editRef.focus();
    });
  }

  /* @ 提及：候选只要关键元素（含无概念图的——渲染纯名块）；无参考栏概念 */
  const mention = usePromptMention({
    editor: () => editRef,
    rec: () => undefined,
    refAssets: () => [],
    maxRefs: () => Infinity,
    cats: ['keyElement'],
    extraBoardItems: () => state.keyElements
      .filter((k) => !!k.title)
      .map((k) => ({
        url: '', name: k.title as string, type: 'image' as const, category: 'keyElement' as const,
      })),
    syncPrompt: () => {},
  });

  /** 失焦保存：desc 序列化回纯文本；sceneRefs 按事件同步（无增删不写库） */
  function commit() {
    mention.closeMention();
    if (!editRef) { setEditing(false); return; }
    const text = serializeDescDOM(editRef);
    const prevRefs = (props.group.sceneRefs || []).map(String);
    const nextRefs = syncSceneRefsAfterEdit(prevRefs, text, insertedTitles, state.keyElements);
    if (text !== desc()) {
      studioActions.renameGroupLocal('shot', props.group.id, { desc: text });
    }
    if (nextRefs) studioActions.setSceneRefsLocal(props.group.id, nextRefs);
    setEditing(false);
  }

  return (
    <Show when={!editing()} fallback={
      <>
        <div
          ref={editRef}
          class="sb-design-body sb-design-body--editing"
          contentEditable={true}
          onInput={() => mention.detectMention()}
          onKeyDown={(e) => {
            // @ 弹层导航/chip 整体删除先消费；其余 Esc = 放弃退出编辑
            if (promptEditorKeyDown(e, mention, () => {})) return;
            if (e.key === 'Escape') setEditing(false);
          }}
          onClick={(e) => {
            const x = (e.target as HTMLElement).closest('.desc-ref-remove');
            if (!x) return;
            e.preventDefault();
            e.stopPropagation();
            (x.closest('.mention-chip') as HTMLElement | null)?.remove();
          }}
          onBlur={() => {
            // 150ms 宽限：点 @ 弹层（搜索框/条目）不触发保存退出（同 GroupDescEditor 口径）
            setTimeout(() => {
              const active = document.activeElement as HTMLElement | null;
              if (active && active.closest('.mention-popup')) return;
              if (!editing()) return;
              commit();
            }, 150);
          }}
        />
        <Show when={mention.mentionActive() && mention.mentionPos()}>
          <PromptMentionPopup
            pos={mention.mentionPos()!}
            query={mention.mentionQuery()}
            onQuery={mention.setMentionQuery}
            boardItems={mention.boardItems}
            refItems={mention.refItems}
            hideRefSection
            isActive={(item) => {
              const cur = mention.mentionItems()[mention.mentionIdx()];
              return !!cur && cur.url === item.url && cur.name === item.name;
            }}
            onPick={(item) => {
              insertedTitles.push(item.name);
              mention.insertMentionChip(item);
            }}
          />
        </Show>
      </>
    }>
      <div class="sb-design">
        <p
          ref={bodyRef}
          class={`sb-design-body${expanded() ? '' : ' sb-design-body--collapsed'}`}
          title={expanded() ? '点击收起；双击编辑' : '点击展开；双击编辑'}
          onClick={(e) => {
            // 读态点内联块 = 跳转该关键元素（与顶部场景行同行为）；其余点击展开/收起
            const chip = (e.target as HTMLElement).closest('.mention-chip') as HTMLElement | null;
            if (chip) {
              studioActions.jumpToElementByTitle(chip.dataset.name || '');
              return;
            }
            // 延迟切换：给 dblclick 留出配对窗口（双击进编辑时不触发展开抖动）
            clearTimeout(clickTimer);
            clickTimer = setTimeout(() => setExpanded((v) => !v), 250);
          }}
          onDblClick={(e) => {
            clearTimeout(clickTimer);
            e.preventDefault();
            enterEdit();
          }}
        />
        <button type="button" class="sb-design-toggle" onClick={() => setExpanded((v) => !v)}>
          {expanded() ? '收起' : '展开'}
          <FiChevronDown size={11} class={`sb-design-arrow${expanded() ? ' expanded' : ''}`} />
        </button>
      </div>
    </Show>
  );
}
