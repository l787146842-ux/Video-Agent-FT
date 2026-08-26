import { showToast } from '@/stores/toast';

/**
 * LayoutShell 启动降级可观测信号（P1-3）：
 * 启动期数据拉取失败时逐项 console.warn + 既有 toast 通道提示一次
 * （多项共失败只弹一条），并返回 null 保持既有降级行为不变。
 */
let bootToastShown = false;

export function bootFail(source: string) {
  return (err: unknown): null => {
    console.warn(`[boot] ${source} 初始化失败`, err);
    if (!bootToastShown) {
      bootToastShown = true;
      showToast('后端未就绪：启动数据加载失败，已降级为默认空状态', 'warning', 5000);
    }
    return null;
  };
}

/** 后台任务订阅恢复失败：降级行为不变（不阻塞启动），仅加可观测信号 */
export function warnBootTaskResume(err: unknown): void {
  console.warn('[boot] agent-tasks 恢复订阅失败', err);
  showToast('后台任务恢复失败（后端可能未就绪）', 'warning', 5000);
}
