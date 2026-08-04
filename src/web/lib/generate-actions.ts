/**
 * 生成管线入口（图片/视频/音频）
 * 提交任务 → activeGenerations 计时 → 轮询模块写回草稿。
 */
import { state, findDraftRecord } from '@/stores/studio';
import { studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { submitImageTask, submitVideoTask, addGenerationLog } from '@/api/generate';
import { canvasLlm } from '@/api/agent';
import { studioImageSizeForRatio } from '@/lib/image-sizes';
import {
  patchDraft, pollAndPreviewImage, pollAndPreviewVideo,
} from '@/lib/generate-polling';
import { registerManualTask } from '@/lib/generation-events';
import { resolvePromptForGeneration } from '@/lib/prompt-mentions';

// ---------- 生图 ----------

export async function generateImage(): Promise<void> {
  const rec = findDraftRecord(state.selectedDraftId, state.selectedType);
  const draft = rec?.draft;
  if (!draft) { showToast('请先在左侧选中一个关键元素草稿卡片', 'warning'); return; }
  const draftType = rec?.type || 'keyElement';

  const providerId = draft.providerId || '';
  const model = draft.model || '';
  const ratioSelection = draft.aspectRatio || '1:1';
  const customWidth = draft.customRatioWidth || '';
  const customHeight = draft.customRatioHeight || '';
  const imageResolution = draft.imageResolution || '1K';
  const size = studioImageSizeForRatio(ratioSelection, customWidth, customHeight, imageResolution);
  const aspectRatio = ratioSelection === 'custom' ? `${customWidth}:${customHeight}` : ratioSelection;

  // @引用解析：提示词里的 @名称 重写为位置标记，被引用的素材自动纳入参考图
  // （最多 5 张，与后端/模型单次上传限制对齐）
  const resolved = resolvePromptForGeneration(draft.prompt || '', draft.refAssets || [], 5);
  const refs = resolved.refs.map((url) => ({ url, role: 'reference' }));

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
      reference_images: refs.slice(0, 5),
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
  const providerId = draft.providerId || '';
  const model = draft.model || '';
  const resolution = draft.resolution || '1080p';
  const duration = parseInt(draft.duration || '5s', 10) || 5;
  const aspectRatio = draft.aspectRatio || '16:9';
  // @引用解析：视频生成参考图上限 2（首帧/尾帧），@命中的素材自动纳入
  const resolved = resolvePromptForGeneration(draft.prompt || '', draft.refAssets || [], 2);
  const imageRefs = resolved.refs.map((url, index) => ({
    url,
    role: index === 0 ? 'first_frame' : index === 1 ? 'last_frame' : 'reference',
  }));

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
      images: imageRefs.slice(0, 2),
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

  const provider = draft.providerId || '';
  const model = draft.model || '';
  const mode = draft.mode || '多模态音频生成';
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
