/**
 * i18n — 中文错误提示映射（P2-17）
 * 后端错误事件/响应携带 error_code 时，前端统一翻译为中文友好提示。
 */

const ERROR_CODE_MESSAGES: Record<string, string> = {
  RATE_LIMITED: '操作太频繁，请稍后再试',
  UNAUTHORIZED: '访问被拒绝：缺少或无效的 API Key',
  ADAPTER_ERROR: '模型服务异常，请检查 API Key 与服务商状态',
  GENERATION_ERROR: '生成任务失败，请稍后重试',
  EXECUTION_ERROR: '操作执行失败',
  TIMEOUT: '请求超时，请稍后重试',
  NETWORK_ERROR: '网络连接异常，请检查网络后重试',
  INTERNAL_ERROR: '服务端内部错误，请稍后重试',
  FORBIDDEN_ORIGIN: '非本机来源的写请求被拒绝',
  EMPTY_MESSAGE: '消息不能为空',
  NO_ACTIVE_PROJECT: '没有打开的项目，请先创建或打开一个项目',
};

/** 将 error_code + 后端 detail 翻译为中文友好提示（未知 code 回退 detail） */
export function resolveErrorMessage(errorCode: string | null | undefined, detail?: string | null): string {
  const text = (detail ?? '').trim();
  // 模型服务错误直接透传上游原始错误（如 "LLM 返回 HTTP 529: Service overloaded"），
  // 不用笼统译文掩盖真实原因（与刷新后从历史记录还原的文案保持一致）。
  if (errorCode === 'ADAPTER_ERROR' && text) return text;
  if (errorCode && ERROR_CODE_MESSAGES[errorCode]) {
    return ERROR_CODE_MESSAGES[errorCode];
  }
  if (text) return text;
  return '未知错误';
}
