/**
 * Skill 启停开关（批7/对齐外部标杆 卡片开关）：
 * 数据源 = 后端 runtime_settings.skills_disabled（批5 通道；存被停用 slug，
 * 加入=停用 / 移除=启用；空 = 全启用）。Skill 工作台左栏开关写入；
 * SkillPicker / 风格层据此过滤展示。
 * GET/PUT 走 global-settings store（类型唯一源 api.generated.ts，
 * 乐观更新 + 失败回滚在内），不另开旁路存储。
 */
import { ensureGlobalSettings, globalSettings, updateGlobalSettings } from './global-settings';
import { showToast } from '@/stores/toast';

/** 某 slug 是否启用中（设置未加载时回落全启用——与后端默认空列表同口径） */
export function isSkillEnabled(slug: string): boolean {
  const disabled = globalSettings()?.skills_disabled ?? [];
  return !disabled.includes(slug);
}

/** 启停切换：PUT runtime_settings 更新 skills_disabled（加入=停用、移除=启用） */
export async function toggleSkillEnabled(slug: string): Promise<void> {
  const gs = await ensureGlobalSettings();
  if (!gs) {
    showToast('全局设置读取失败，开关暂不可用', 'error');
    return;
  }
  const next = new Set(gs.skills_disabled);
  if (next.has(slug)) next.delete(slug);
  else next.add(slug);
  await updateGlobalSettings({ skills_disabled: [...next] });
}
