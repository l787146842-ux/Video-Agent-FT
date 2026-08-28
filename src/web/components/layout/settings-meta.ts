/**
 * API 配置页纯数据域（自 SettingsView.tsx 切出，零行为变更）。
 *
 * 类型定义 + 协议/平台常量 + 纯工厂函数——无 Solid 响应式依赖，
 * SettingsView 经具名导入消费，语义与切出前逐字一致。
 */
import type { ApiProvider } from '@/types';
import type { FetchModelsResponse } from '@/types/api.generated';

export interface EditableProvider extends ApiProvider {
  api_key?: string;
  has_key?: boolean;
  key_preview?: string;
  key_env?: string;
  has_wallet_key?: boolean;
  wallet_key_preview?: string;
  wallet_key_env?: string;
}

export const PROTOCOL_OPTIONS = [
  { value: 'openai', label: 'OpenAI 兼容 / 直连' },
  { value: 'apimart', label: '异步协议 (APIMart)' },
  { value: 'gemini', label: 'Gemini 协议' },
  { value: 'volcengine', label: '方舟/Ark 任务协议' },
  { value: 'runninghub', label: 'RunningHub OpenAPI' },
  { value: 'jimeng', label: '即梦 CLI' },
  { value: 'codex', label: 'OpenAI Codex CLI' },
  { value: 'gemini-cli', label: 'Antigravity CLI' },
];

export const CLI_PROTOCOLS = new Set(['jimeng', 'codex', 'gemini-cli']);
/** 图片接口模式（画布同款五档，持久化在 provider.image_request_mode） */
export const IMAGE_MODE_OPTIONS = [
  { value: 'openai', label: '图片: OpenAI 标准' },
  { value: 'openai-json', label: '图片: OpenAI JSON' },
  { value: 'openai-video-proxy', label: '图片: OpenAI 中转' },
  { value: 'openai-responses', label: '图片: OpenAI RS' },
  { value: 'tudou-async', label: '图片: 土豆 GPT-Image-2 异步' },
];
export const imageModeLabel = (v: string) => IMAGE_MODE_OPTIONS.find((o) => o.value === v)?.label || v;
/** 内置平台（画布不显示删除按钮） */
export const BUILTIN_IDS = new Set(['modelscope', 'runninghub', 'volcengine']);

export const CLI_ENTRIES = [
  { key: 'jimeng', label: '即梦 CLI', protocol: 'jimeng', statusPath: '/api/jimeng/status', helpPath: '/api/jimeng/help' },
  { key: 'codex', label: 'GPT CLI (Codex)', protocol: 'codex', statusPath: '/api/codex/status', helpPath: '/api/codex/help' },
  { key: 'agy', label: 'Antigravity CLI', protocol: 'gemini-cli', statusPath: '/api/gemini-cli/status', helpPath: '/api/gemini-cli/help' },
];

export const CLI_META: Record<string, { title: string; desc: string }> = {
  'gemini-cli': { title: 'Antigravity CLI 账户', desc: '使用本机 agy 登录态，无需在本项目保存 API Key。需要先安装 CLI 文件夹中的依赖。' },
  codex: { title: 'OpenAI CLI 账户', desc: '使用本机 codex 登录态，无需在本项目保存 API Key。' },
  jimeng: { title: '即梦 CLI 账户', desc: '使用本机 dreamina 登录态，无需 API Key。' },
};

/** 画布同款平台定制内容 */
export const PLATFORM_META: Record<string, {
  defaultUrls?: Array<[string, string]>;
  tokenLinks?: Array<[string, string]>;
  note?: string;
}> = {
  modelscope: {
    defaultUrls: [
      ['国内默认请求地址', 'https://api-inference.modelscope.cn/v1'],
      ['国外使用请求地址', 'https://api-inference.modelscope.ai/v1'],
    ],
    tokenLinks: [
      ['获取 Token · 国内', 'https://www.modelscope.cn/my/access/token'],
      ['获取 Token · 国外', 'https://www.modelscope.ai/my/access/token'],
    ],
  },
  volcengine: {
    defaultUrls: [['方舟默认请求地址', 'https://ark.cn-beijing.volces.com/api/v3']],
    note: 'Seedance 视频生成使用方舟 API Key，验证会请求 /api/v3/models。',
  },
};

export const RH_GUIDE = {
  title: 'RunningHub 新手引导',
  desc: 'RH 有 RH币和账户余额两种 Key：应用/工作流可用 RH币，标准模型只能走账户余额。',
  coinUrl: 'https://www.runninghub.ai/enterprise-api/consumerApi?inviteCode=rh-v1331',
  walletUrl: 'https://www.runninghub.ai/enterprise-api/sharedApi?inviteCode=rh-v1331',
};

export type ModelKind = 'chat_models' | 'image_models' | 'video_models';
export type ModelCat = 'image' | 'chat' | 'video';

/** fetch-models 读形态：以生成物为唯一来源（use-model-fetch 归一化补齐缺省字段） */
export type FetchedModels = FetchModelsResponse;

export function newProvider(id: string): EditableProvider {
  return {
    id, name: '', protocol: 'openai', base_url: '',
    enabled: true, chat_models: [], image_models: [], video_models: [],
    api_key: '', has_key: false,
  };
}

/** CLI 安装状态表（平台 key → 检测结果） */
export type CliStatusMap = Record<string, { installed: boolean; message: string }>;

/**
 * SettingsView 子组件共享 API（切分设立）：
 * 状态全部留在父组件，子组件经此对象消费 accessor 与动作——
 * 单一 prop 传入，避免 20+ 个离散 props 钻透。
 */
export interface SettingsApi {
  current: () => EditableProvider | undefined;
  providers: () => EditableProvider[];
  sel: () => number;
  proto: () => string;
  isCli: () => boolean;
  imageMode: () => string;
  keyInput: () => string;
  setKeyInput: (v: string) => void;
  rhCoin: () => string;
  setRhCoin: (v: string) => void;
  rhWallet: () => string;
  setRhWallet: (v: string) => void;
  verifyResult: () => { ok: boolean; text: string } | null;
  cliStatus: () => CliStatusMap;
  patch: (field: string, value: unknown) => void;
  saveAll: (overrides?: Record<string, unknown>) => Promise<boolean>;
  switchSel: (i: number) => void;
  addProvider: () => void;
  selectOrAddCli: (protocol: string, label: string) => void;
  removeCurrent: () => void;
  commitKey: () => void;
  clearKey: () => void;
  verifyAddress: () => void;
  verifyProtocol: () => void;
  patchModel: (kind: ModelKind, idx: number, value: string) => void;
  removeModel: (kind: ModelKind, idx: number) => void;
  addModel: (kind: ModelKind) => void;
  fetchModels: () => void;
  jimengLogin: () => void;
  jimengCredit: () => void;
  jimengLogout: () => void;
  refreshCliStatus: (key: string, statusPath: string) => Promise<boolean>;
  cliHelp: (title: string, helpPath: string) => void;
}
