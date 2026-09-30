/**
 * 生成管线入口（图片/视频/音频）
 * 提交任务 → activeGenerations 计时 → 轮询模块写回草稿。
 */
import { state, findDraftRecord } from '@/stores/studio';
import { studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { chatActions } from '@/stores/chat';
import { submitImageTask, submitVideoTask, addGenerationLog } from '@/api/generate';
import { canvasLlm } from '@/api/agent';
import { studioImageSizeForRatio } from '@/lib/image-sizes';
import {
  patchDraft, pollAndPreviewImage, pollAndPreviewVideo,
} from '@/lib/generate-polling';
import { registerManualTask } from '@/lib/generation-events';
import { resolvePromptForGeneration } from '@/lib/prompt-mentions';
import { IMAGE_GEN_LIMIT, VIDEO_GEN_LIMITS } from '@/lib/ref-limits';
import { normalizeDisplayTitle } from '@/lib/desc-ref-utils';
import type { AnyGroup, DraftType } from '@/types';

// ---------- 生图 ----------

export async function generateImage(): Promise<void> {
  const rec = findDraftRecord(state.selectedDraftId, state.selectedType);
  const draft = rec?.draft;
  if (!draft) { showToast('请先在左侧选中一个关键元素草稿卡片', 'warning'); return; }
  const draftType = rec?.type || 'keyElement';

  const providerId = draft.imageProviderId || draft.providerId || '';
  const model = draft.imageModel || draft.model || '';
  const ratioSelection = draft.aspectRatio || '1:1';
  const customWidth = draft.customRatioWidth || '';
  const customHeight = draft.customRatioHeight || '';
  const imageResolution = draft.imageResolution || '1K';
  const size = studioImageSizeForRatio(ratioSelection, customWidth, customHeight, imageResolution);
  const aspectRatio = ratioSelection === 'custom' ? `${customWidth}:${customHeight}` : ratioSelection;

  // @引用解析：提示词里的 @名称 重写为位置标记，被引用的素材自动纳入参考图
  // （上限 IMAGE_GEN_LIMIT，与后端/模型单次上传限制对齐）
  const resolved = resolvePromptForGeneration(draft.prompt || '', draft.refAssets || [], IMAGE_GEN_LIMIT);
  const allRefs = resolved.refs.map((url) => ({ url, role: 'reference' }));
  if (allRefs.length > IMAGE_GEN_LIMIT) {
    showToast(`参考图超出上限，仅前 ${IMAGE_GEN_LIMIT} 张生效`, 'warning');
  }
  const refs = allRefs.slice(0, IMAGE_GEN_LIMIT);

  if (!providerId || !model) { showToast('请先选择图片 API 和对应模型', 'warning'); return; }
  if (!size || (ratioSelection === 'custom' && (!Number(customWidth) || !Number(customHeight)))) {
    showToast('请输入有效的自定义图片比例', 'warning');
    return;
  }

  patchDraft(draft.id, draftType, {
    aspectRatio: ratioSelection, customRatioWidth: customWidth,
    customRatioHeight: customHeight, imageResolution, size,
  });
  showToast('正在提交生图任务...', 'info');

  try {
    const data = await submitImageTask({
      prompt: resolved.prompt,
      provider_id: providerId,
      model,
      size,
      aspect_ratio: aspectRatio,
      resolution: imageResolution,
      reference_images: refs,
      draft_id: draft.id,
      draft_type: draftType,
    });
    if (data.task_id) {
      registerManualTask(data.task_id); // 手动路径自行轮询写回，全局事件总线跳过
      studioActions.startGeneration(draft.id, 'image');
      patchDraft(draft.id, draftType, { genType: 'image', tag: '生成中' });
      void pollAndPreviewImage(data.task_id, draft.id);
    } else if (data.images?.length) {
      patchDraft(draft.id, draftType, { mediaType: 'image', genType: 'image', imgUrl: data.images[0], videoUrl: '', audioUrl: '', tag: '已生成' });
      showToast('图片已生成！', 'success');
    } else {
      showToast('提交成功，等待异步生成', 'info');
    }
  } catch (err) {
    showToast((err as Error).message || '生图请求失败，请检查 API 配置', 'error');
  }
}

// ---------- 生视频 ----------

export async function generateVideo(): Promise<void> {
  const rec = findDraftRecord(state.selectedDraftId, state.selectedType);
  const draft = rec?.draft;
  if (!draft) { showToast('请先在左侧选中一个分镜草稿卡片', 'warning'); return; }
  const draftType = rec?.type || 'shot';

  const mode = draft.mode || '全能参考';
  const providerId = draft.videoProviderId || draft.providerId || '';
  const model = draft.videoModel || draft.model || '';
  const resolution = draft.resolution || '1080p';
  const duration = parseInt(draft.duration || '5s', 10) || 5;
  const aspectRatio = draft.videoAspectRatio || draft.aspectRatio || '16:9';
  // @引用解析（C3）：参考素材对齐 Seedance 2.5 能力（图30/视频10/音频10，共50）；
  // 后端会再自动补充分镜 shotRefs 元素图与音色参考音频（去重）
  const resolved = resolvePromptForGeneration(draft.prompt || '', draft.refAssets || [], VIDEO_GEN_LIMITS.total);
  const imageRefs: Array<{ url: string; role: string }> = [];
  const videoRefs: Array<{ url: string; role: string }> = [];
  const audioRefs: Array<{ url: string; role: string }> = [];
  resolved.refs.forEach((url, index) => {
    const kind = resolved.refKinds[index] || 'image';
    if (kind === 'audio') {
      audioRefs.push({ url, role: 'reference_audio' });
    } else if (kind === 'video') {
      // 修复：视频类参考原先被塞进图片列表/后端静默丢弃，现走独立视频参考通道
      videoRefs.push({ url, role: 'reference_video' });
    } else {
      // 图片角色按图片自身序号：第一/二张兼容首/尾帧模式，其余为多参考图
      const role = imageRefs.length === 0 ? 'first_frame' : imageRefs.length === 1 ? 'last_frame' : 'reference';
      imageRefs.push({ url, role });
    }
  });
  // 超限按类型取前 N，明示用户哪类被截断（栏存储本身已无上限）
  const imgs = imageRefs.slice(0, VIDEO_GEN_LIMITS.image);
  const vids = videoRefs.slice(0, VIDEO_GEN_LIMITS.video);
  const auds = audioRefs.slice(0, VIDEO_GEN_LIMITS.audio);
  const overNotes: string[] = [];
  if (imageRefs.length > imgs.length) overNotes.push(`图 ${imgs.length}/${imageRefs.length}`);
  if (videoRefs.length > vids.length) overNotes.push(`视频 ${vids.length}/${videoRefs.length}`);
  if (audioRefs.length > auds.length) overNotes.push(`音频 ${auds.length}/${audioRefs.length}`);
  if (overNotes.length) showToast(`参考素材超出上限，仅前 N 个生效（${overNotes.join('、')}）`, 'warning');

  if (!providerId || !model) { showToast('请先选择视频 API 和对应模型', 'warning'); return; }
  showToast('正在提交视频生成任务...', 'info');

  try {
    const data = await submitVideoTask({
      prompt: resolved.prompt,
      provider_id: providerId,
      model,
      duration,
      resolution,
      aspect_ratio: aspectRatio,
      images: imgs,
      videos: vids,
      audios: auds,
      enhance_prompt: mode === '全能参考',
      multimodal: mode === '对口型数字人',
      draft_id: draft.id,
      draft_type: draftType,
    });
    const videoUrl = data.video_url || data.videos?.[0] || data.images?.[0];
    if (videoUrl) {
      patchDraft(draft.id, draftType, { mediaType: 'video', genType: 'video', videoUrl, imgUrl: '', audioUrl: '', tag: '已生成' });
      showToast('视频已生成！', 'success');
    } else if (data.task_id) {
      registerManualTask(data.task_id); // 手动路径自行轮询写回，全局事件总线跳过
      studioActions.startGeneration(draft.id, 'video');
      patchDraft(draft.id, draftType, { genType: 'video', tag: '生成中' });
      void pollAndPreviewVideo(data.task_id, draft.id);
    } else {
      showToast('视频任务已提交', 'info');
    }
  } catch (err) {
    showToast((err as Error).message || '视频生成请求失败，请检查 API 配置', 'error');
  }
}

// ---------- 音频规划 ----------

/** 音频组的层描述（唯一载体 = `desc`）。
 *  2026-09-25 用户裁决：「音频也要给 desc。写的地方和看的地方要对的上。」
 *  存量数据回落读 `prompt`（历史前端写口留下的第二事实源）。 */
function audioLayerDesc(group: unknown): string {
  const g = group as { desc?: string; prompt?: string } | undefined;
  return String(g?.desc || g?.prompt || '').trim();
}

/** 找当前选中卡所属的音频组（生成规划要读**组级描述**，不是卡片自己的 prompt）。 */
function selectedAudioGroup(): { group: AnyGroup; type: DraftType } | null {
  const rec = findDraftRecord(state.selectedDraftId, state.selectedType);
  if (rec?.type === 'audio') return { group: rec.group as AnyGroup, type: 'audio' };
  // 未选中卡片时：若当前页签在音频，取第一个音频组（允许"先选组再规划"）
  if (state.subTab === 'audio' || state.selectedType === 'audio') {
    const first = (state.audioItems || [])[0];
    if (first) return { group: first as unknown as AnyGroup, type: 'audio' };
  }
  return null;
}

/**
 * 音频层规划（2026-09-25 用户裁决重做）。
 *
 * 裁决原文：「设计阶段只规划音频，只在提示词撰写才建卡」「音频阶段可以先打通，
 * 我后面会接入音频模型」。
 *
 * 旧实现的两个病：
 *   ① 入口要求**先有卡**（`if (!draft) 请先选中一张音频草稿卡片`）——而设计阶段
 *      已按裁决**不建卡**（只写组 desc），于是永远进不来（承接断链）；
 *   ② 读的是 `draft.prompt`，**完全不读组 desc** ⇒ 设计期写下的层描述（覆盖镜头/
 *      情绪/配器）根本不参与规划。
 *
 * 新口径：**以音频组的 desc 为输入**；组内没有卡时自动建一张承接卡（承载规划结果
 * 与后续音频模型产出），已有卡则写回该卡。生成通道打通后（用户将接入音频模型），
 * 只需把 `canvasLlm` 换成真实音频生成调用，本条链路的输入输出契约不变。
 */
export async function generateAudio(): Promise<void> {
  const target = selectedAudioGroup();
  if (!target) {
    showToast('请先在左侧「音频」页签选中一个音频组', 'warning');
    return;
  }
  const { group } = target;
  const layerDesc = audioLayerDesc(group);
  if (!layerDesc) {
    showToast('该音频组还没有描述：请先在故事板设计阶段写入音频层设计（内容见 Skill 音频章节）', 'warning');
    return;
  }

  // 已有卡 → 写回该卡（沿用其供应商/模型配置）；没有卡 → 自动建一张承接卡
  // （设计阶段不建卡，故此处必须有承接，否则规划结果无处落账）。
  const existing = (group.drafts || [])[0];
  const provider = existing?.audioProviderId || existing?.providerId || '';
  const model = existing?.audioModel || existing?.model || '';
  const mode = existing?.audioMode || existing?.mode || '多模态音频生成';
  const timbre = existing?.timbre || '深邃男声 (Deep Narrator)';
  if (!provider || !model) {
    showToast('请先选择音频规划 API 和对应模型（在音频卡片参数栏或全局设置）', 'warning');
    return;
  }
  showToast('正在生成音频规划...', 'info');
  const t0 = performance.now();

  try {
    const data = await canvasLlm({
      // 输入 = 组级层描述（设计期成果）+ 组标题（层 ID），不再依赖卡片 prompt
      message: `请根据以下音频层设计生成可执行的音频规划，生成模式：${mode}，目标音色：${timbre}。`
        + '包含旁白、对白、环境音、音乐、时间点和音色建议。不要声称已经生成音频文件。\n\n'
        + `【音频层】${String((group as { title?: string }).title || '')}\n`
        + `【层设计】${layerDesc}`,
      // 后端 system_prompt 字段已废弃不再使用（Skill 正文不注入，由 read_skill 按需读取），不再随请求携带
      provider,
      model,
      ms_model: provider === 'modelscope' ? model : '',
      messages: [],
      context_mode: 'none',
    });
    const elapsedSec = (performance.now() - t0) / 1000;
    // 非流式响应的文档清单同样即显渲染（通道与流式轨对齐，§5.2）
    chatActions.applyNonStreamDocs(data.documents_written || []);
    const planText = String(data.text || '').trim();
    if (existing) {
      patchDraft(existing.id, 'audio', {
        mediaType: 'audio', genType: 'audio', imgUrl: '', videoUrl: '',
        prompt: planText || existing.prompt, mode, timbre,
      });
    } else {
      // 承接卡：label 取层标题（去掉 Audio_ 前缀），交由 store 落进该组
      const label = normalizeDisplayTitle(String((group as { title?: string }).title || '音频'));
      studioActions.addDraftLocalWith('audio', group.id, {
        label, tag: 'Agent', mediaType: 'audio', audioType: 'bgm',
        prompt: planText, mode, timbre,
      });
    }
    // 生成日志：音频规划无论成败都要有记录（未走后端任务通道，前端补录）
    void addGenerationLog({
      media_type: 'audio', status: 'succeeded', provider, model,
      prompt: layerDesc, draft_id: existing?.id || '', elapsed: Math.round(elapsedSec * 10) / 10,
      source: 'manual',
    });
    showToast(`音频规划已生成（耗时 ${elapsedSec.toFixed(1)}s）`, 'success');
  } catch (err) {
    void addGenerationLog({
      media_type: 'audio', status: 'failed', provider, model,
      prompt: layerDesc, draft_id: existing?.id || '',
      error: (err as Error).message || '音频规划失败',
      elapsed: Math.round(((performance.now() - t0) / 1000) * 10) / 10, source: 'manual',
    });
    showToast((err as Error).message || '音频规划失败', 'error');
  }
}
