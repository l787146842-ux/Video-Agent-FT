/**
 * 建议动作 value 护栏（批1 审核整改）
 *
 * suggested_actions 的 value 由前端零解析直接发送进用户气泡与 LLM 历史，
 * 契约 = 与 label 同值的人类可读文本（宪法三通道契约：value 必须人类可读）。
 * 本护栏在消费面前端兜底：后端契约一旦漂移（下发机械 token/JSON 片段），
 * 不再直击穿用户气泡。
 */

/** true = 人类可读可发送；false = 疑似机械 token/注入，拒发 */
export function isHumanReadableSuggestedValue(value: string): boolean {
  const s = (value || '').trim();
  if (!s || s.length > 200) return false;
  // 控制符（含换行注入多指令）
  if (/[\u0000-\u001f]/.test(s)) return false;
  // 纯 ASCII 且含机械 token 特征字符（flow_continue / JSON 片段 / 管道类）
  if (/^[\x21-\x7e]+$/.test(s) && /[_{}[\]:;|<>]/.test(s)) return false;
  return true;
}
