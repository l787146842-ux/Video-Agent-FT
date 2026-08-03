import { FiImage, FiVideo } from 'solid-icons/fi';
import { batchImage } from '@/api/generate';
import { showToast } from '@/stores/toast';
import { confirmDialog } from '@/components/shared/ConfirmDialog';
import {
  apiProvidersFor, preferredProviderIdForKind, defaultModelFor,
} from '@/lib/providers';

/**
 * 批量生成按钮条
 * 概念图 = 所有关键元素草稿；关键帧 = 所有分镜草稿（自动注入元素参考图）。
 * 供应商/模型取当前首选的图片供应商。
 */
export function BatchGenBar() {
  async function run(target: 'all_keyElements' | 'all_shots') {
    const providers = apiProvidersFor('image');
    const providerId = preferredProviderIdForKind('image', providers);
    const model = defaultModelFor(providerId, 'image');
    if (!providerId || !model) {
      showToast('暂无可用图片 API，请先在 API 配置中添加供应商', 'warning');
      return;
    }
    const label = target === 'all_keyElements' ? '概念图' : '关键帧';
    const ok = await confirmDialog({
      title: `批量生成${label}`,
      message: `将为所有${label}草稿提交生图任务（消耗供应商额度）。`,
      confirmText: '开始生成',
    });
    if (!ok) return;
    try {
      const data = await batchImage({
        target,
        provider_id: providerId,
        model,
        size: '1280x720',
        aspect_ratio: '16:9',
      });
      if ((data.count || 0) > 0) {
        showToast(`已提交 ${data.count} 个${label}生成任务`, 'success');
      } else {
        showToast(data.detail || '没有可生成的草稿（需先有提示词）', 'warning');
      }
    } catch (e) {
      showToast((e as Error).message || '批量生成请求失败', 'error');
    }
  }

  return (
    <div class="batch-gen-bar">
      <button
        type="button"
        class="batch-gen-btn"
        title="为所有关键元素的概念图提交生图任务"
        onClick={() => run('all_keyElements')}
      >
        <FiImage size={13} />
        <span>批量生成概念图</span>
      </button>
      <button
        type="button"
        class="batch-gen-btn"
        title="为所有分镜的关键帧提交生图任务（自动注入元素参考图）"
        onClick={() => run('all_shots')}
      >
        <FiVideo size={13} />
        <span>批量生成关键帧</span>
      </button>
    </div>
  );
}
