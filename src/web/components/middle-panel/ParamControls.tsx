import { Show, Switch, Match, createEffect, untrack } from 'solid-js';
import { state, findDraftRecord, studioActions } from '@/stores/studio';
import {
  apiProvidersFor, providerModels, preferredProviderIdForKind,
} from '@/lib/providers';
import { ImageParams } from './params/ImageParams';
import { VideoParams } from './params/VideoParams';
import { AudioParams } from './params/AudioParams';
import type { DraftType } from '@/types';

/** 根据草稿类型与生成类型推导供应商种类（image/video/chat） */
function providerKindFor(type: DraftType, genType: string): 'image' | 'video' | 'chat' {
  if (type === 'shot') return 'video';
  if (type === 'audio') return 'chat';
  // 关键元素：跟随当前生成类型 genType（图片/视频/音频生成）
  if (genType === 'video') return 'video';
  if (genType === 'audio') return 'chat';
  return 'image';
}

/**
 * 参数控制栏：按 selectedType 分发到图片/视频/音频参数组件
 */
export function ParamControls() {
  const rec = () => findDraftRecord(state.selectedDraftId, state.selectedType);
  const draft = () => rec()?.draft;
  /** 关键元素当前生成类型：genType 优先，缺省回退 mediaType */
  const genType = () => {
    const d = draft();
    return d?.genType || d?.mediaType || 'image';
  };

  // 供应商/模型兌底：仅在切换草稿、切换类型或切换生成媒体类型时校正
  createEffect(() => {
    // 跟踪选中状态 + 生成媒体类型（mediaType）+ 供应商加载
    const draftId = state.selectedDraftId;
    const type = state.selectedType;
    const providers = state.apiProviders; // 供应商加载后触发校正
    if (!draftId || !type) return;
    const r0 = findDraftRecord(draftId, type);
    // 生成类型（genType 优先，回退 mediaType）决定供应商种类
    const genType = r0?.draft.genType || r0?.draft.mediaType || 'image';
  
    // 以下读取用 untrack 包裹，避免 effect 跟踪 draft 数据变更导致无限循环
    untrack(() => {
      const r = findDraftRecord(draftId, type);
      if (!r) return;
      const kind = providerKindFor(type, genType);
      let pid = r.draft.providerId || '';
      if (!providerModels(pid, kind).length) {
        pid = preferredProviderIdForKind(kind, apiProvidersFor(kind));
      }
      const models = providerModels(pid, kind);
      const currentModel = r.draft.model || '';
      const patch: Record<string, string> = {};
      if (pid && pid !== r.draft.providerId) patch.providerId = pid;
      if (!models.includes(currentModel)) patch.model = models[0] || '';
      if (Object.keys(patch).length) {
        studioActions.updateDraftLocal(type, r.draft.id, patch);
      }
    });
  });

  return (
    <Show when={draft()}>
      <div class="param-controls-bar">
        <Switch>
          <Match when={state.selectedType === 'shot'}>
            <VideoParams draft={draft()!} type="shot" />
          </Match>
          <Match when={state.selectedType === 'audio'}>
            <AudioParams draft={draft()!} type="audio" />
          </Match>
          {/* 关键元素：按生成类型（genType）分发图片/视频/音频参数栏 */}
          <Match when={state.selectedType === 'keyElement' && genType() === 'video'}>
            <VideoParams draft={draft()!} type="keyElement" />
          </Match>
          <Match when={state.selectedType === 'keyElement' && genType() === 'audio'}>
            <AudioParams draft={draft()!} type="keyElement" />
          </Match>
          <Match when={state.selectedType === 'keyElement'}>
            <ImageParams draft={draft()!} />
          </Match>
        </Switch>
      </div>
    </Show>
  );
}
