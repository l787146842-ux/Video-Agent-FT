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
  // 后端会再自动补充分镜 sceneRefs 元素图与音色参考音频（去重）
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

export async function generateAudio(): Promise<void> {
  const rec = findDraftRecord(state.selectedDraftId, state.selectedType);
  const draft = rec?.draft;
  if (!draft) { showToast('请先在左侧选中一个音频草稿卡片', 'warning'); return; }
  const draftType = rec?.type || 'audio';

  const provider = draft.audioProviderId || draft.providerId || '';
  const model = draft.audioModel || draft.model || '';
  const mode = draft.audioMode || draft.mode || '多模态音频生成';
  const timbre = draft.timbre || '深邃男声 (Deep Narrator)';
  if (!provider || !model) { showToast('请先选择音频规划 API 和对应模型', 'warning'); return; }
  showToast('正在生成音频规划...', 'info');
  const t0 = performance.now();

  try {
    const data = await canvasLlm({
      message: `请根据以下内容生成可执行的音频规划，生成模式：${mode}，目标音色：${timbre}。包含旁白、对白、环境音、音乐、时间点和音色建议。不要声称已经生成音频文件。\n\n${draft.prompt || ''}`,
      // 后端 system_prompt 字段已废弃不再使用（Skill 全文由服务端按 skill_name 硬注入），不再随请求携带
      provider,
      model,
      ms_model: provider === 'modelscope' ? model : '',
      messages: [],
      context_mode: 'none',
    });
    const elapsedSec = (performance.now() - t0) / 1000;
    // 0817：非流式响应的文档清单同样即显渲染（通道与流式轨对齐，§5.2）
    chatActions.applyNonStreamDocs(data.documents_written || []);
    patchDraft(draft.id, draftType, {
      mediaType: 'audio', genType: 'audio', imgUrl: '', videoUrl: '',
      prompt: String(data.text || draft.prompt), mode, timbre,
    });
    // 生成日志：音频规划无论成败都要有记录（未走后端任务通道，前端补录）
    void addGenerationLog({
      media_type: 'audio', status: 'succeeded', provider, model,
      prompt: draft.prompt || '', draft_id: draft.id,
      elapsed: Math.round(elapsedSec * 10) / 10, source: 'manual',
    });
    showToast(`音频规划已生成（耗时 ${elapsedSec.toFixed(1)}s）`, 'success');
  } catch (err) {
    void addGenerationLog({
      media_type: 'audio', status: 'failed', provider, model,
      prompt: draft.prompt || '', draft_id: draft.id,
      error: (err as Error).message || '音频规划失败',
      elapsed: Math.round(((performance.now() - t0) / 1000) * 10) / 10, source: 'manual',
    });
    showToast((err as Error).message || '音频规划失败', 'error');
  }
}
