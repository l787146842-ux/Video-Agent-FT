import { createEffect, createSignal, For, onCleanup, Show } from 'solid-js';
import { FiPlus, FiX } from 'solid-icons/fi';
import { state, studioActions } from '@/stores/studio';
import type { ShotGroup } from '@/types';

/**
 * 场景引用 chips（仅分镜组）。
 * 点击跳转；× 删除与 + 添加（为 LLM 写提示词提供依据，
 * 并决定出图/出视频时自动挂哪些元素概念图）。
 */
export function SceneRefsChips(props: { group: ShotGroup }) {
  const sceneRefs = () => props.group.sceneRefs || [];
  const [refPickerOpen, setRefPickerOpen] = createSignal(false);

  /** sceneRefs 存储的是关键元素 id（ke-xxx）或标题；展示时解析为元素标题，
   * 解析不到才显示原值（卡片上直接显示 ke-xxx 看不懂）。
   * 归一来源指向 lib/desc-ref-utils 的 stripCategoryPrefix（此处仅按 id/标题直查，
   * 类别前缀剥离的详细合并留给 P2-J，本处不改逻辑） */
  const refLabel = (ref: string) => {
    const el = state.keyElements.find((k) => k.id === ref || k.title === ref);
    return el?.title || String(ref);
  };

  /** 尚未引用的关键元素标题（添加候选） */
  const availableElements = () => {
    const have = new Set(sceneRefs().map((r) => refLabel(String(r))));
    return state.keyElements
      .map((k) => k.title)
      .filter((t): t is string => !!t && !have.has(t));
  };

  function removeSceneRef(ref: string) {
    studioActions.setSceneRefsLocal(
      props.group.id,
      sceneRefs().filter((r) => String(r) !== ref).map(String),
    );
  }

  function addSceneRef(title: string) {
    studioActions.setSceneRefsLocal(props.group.id, [...sceneRefs().map(String), title]);
    setRefPickerOpen(false);
  }

  /** 点选单外区域关闭添加候选弹层 */
  createEffect(() => {
    if (!refPickerOpen()) return;
    const onDown = (e: PointerEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && el.closest('.scene-ref-add-wrap')) return;
      setRefPickerOpen(false);
    };
    document.addEventListener('pointerdown', onDown, true);
    onCleanup(() => document.removeEventListener('pointerdown', onDown, true));
  });

  return (
    <div class="scene-refs">
      <Show when={sceneRefs().length > 0}>
        <span class="scene-refs-label">场景:</span>
        <For each={sceneRefs()}>
          {(ref) => (
            <span class="scene-ref-chip scene-ref-editable">
              <button
                type="button"
                class="scene-ref-jump"
                title="点击跳转到该关键元素"
                onClick={() => studioActions.jumpToElementByTitle(String(ref))}
              >
                {refLabel(String(ref))}
              </button>
              <button
                type="button"
                class="scene-ref-remove"
                title="移除场景引用（出视频时不再自动挂该元素概念图）"
                onClick={() => removeSceneRef(String(ref))}
              >
                <FiX size={10} />
              </button>
            </span>
          )}
        </For>
      </Show>
      <span class="scene-ref-add-wrap">
        <button
          type="button"
          class="scene-ref-chip scene-ref-add"
          title="添加场景引用（本镜头出场的关键元素）"
          onClick={() => setRefPickerOpen((v) => !v)}
        >
          <FiPlus size={10} /> 添加
        </button>
        <Show when={refPickerOpen()}>
          <div class="scene-ref-picker">
            <Show when={availableElements().length} fallback={
              <div class="scene-ref-picker-empty">没有可添加的关键元素</div>
            }>
              <For each={availableElements()}>
                {(t) => (
                  <button type="button" class="scene-ref-picker-item" onClick={() => addSceneRef(t)}>
                    {t}
                  </button>
                )}
              </For>
            </Show>
          </div>
        </Show>
      </span>
    </div>
  );
}
