/**
 * Job 面板 store — 视频批量生成任务管理（列表/详情/resume/cancel）。
 * 独立 store，不侵入既有 generation-log 或 studio。
 */
import { createSignal } from 'solid-js';
import {
  listVideoBatches, getVideoBatch, resumeVideoBatch, cancelVideoBatch,
  type BatchSummary, type BatchDetail,
} from '@/api/jobs';
import { state } from '@/stores/studio';
import { showToast } from '@/stores/toast';

const [jobsOpen, setJobsOpen] = createSignal(false);
const [jobs, setJobs] = createSignal<BatchSummary[]>([]);
const [jobsLoading, setJobsLoading] = createSignal(false);
const [selectedJob, setSelectedJob] = createSignal<BatchDetail | null>(null);
const [detailLoading, setDetailLoading] = createSignal(false);

/** 刷新任务列表（静默失败：后端未就绪不打扰） */
export async function refreshJobs(): Promise<void> {
  setJobsLoading(true);
  try {
    const data = await listVideoBatches(state.projectId || undefined);
    setJobs(Array.isArray(data.batches) ? data.batches : []);
  } catch { /* 静默 */ } finally {
    setJobsLoading(false);
  }
}

/** 打开面板并刷新列表 */
export function openJobs(): void {
  setJobsOpen(true);
  setSelectedJob(null);
  void refreshJobs();
}

export function closeJobs(): void {
  setJobsOpen(false);
  setSelectedJob(null);
}

export function toggleJobs(): void {
  if (jobsOpen()) closeJobs();
  else openJobs();
}

/** 查看批次详情 */
export async function viewJobDetail(batchId: string): Promise<void> {
  setDetailLoading(true);
  try {
    const detail = await getVideoBatch(batchId);
    setSelectedJob(detail);
  } catch (e) {
    showToast((e as Error).message || '加载批次详情失败', 'error');
  } finally {
    setDetailLoading(false);
  }
}

/** 返回列表（清空详情） */
export function backToList(): void {
  setSelectedJob(null);
  void refreshJobs();
}

/** 断点续跑 */
export async function resumeJob(batchId: string): Promise<void> {
  try {
    const detail = await resumeVideoBatch(batchId);
    setSelectedJob(detail);
    showToast('已续跑，后台逐镜提交中', 'success');
    void refreshJobs();
  } catch (e) {
    showToast((e as Error).message || '续跑请求失败', 'error');
  }
}

/** 取消批次 */
export async function cancelJob(batchId: string): Promise<void> {
  try {
    await cancelVideoBatch(batchId);
    showToast('批次已取消', 'success');
    void refreshJobs();
    if (selectedJob()?.batch_id === batchId) {
      void viewJobDetail(batchId);
    }
  } catch (e) {
    showToast((e as Error).message || '取消请求失败', 'error');
  }
}

export { jobsOpen, jobs, jobsLoading, selectedJob, detailLoading };
