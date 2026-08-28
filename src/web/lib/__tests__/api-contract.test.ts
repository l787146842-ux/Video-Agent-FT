/**
 * 契约桥接测试（契约门禁复活后补消费面，防回退）。
 *
 * 测试 A（消费覆盖防回退）：api.generated.ts 的每个导出 schema 必须在 src/web
 *   内（生成物自身与本测试除外）至少出现一次，或登记在 EXEMPT 白名单并附原因。
 *   消费面从此只升不降——新增 schema 无消费方即红。
 * 测试 B（防手写回潮）：src/web/api/*.ts 不得定义与生成物同名的 export interface
 *   （同名遮蔽会让漂移保护失效），确需保留的登记在 SHADOW_WHITELIST（与
 *   types/index.ts 豁免清单同源）。
 *
 * 语料获取走 vite 原生机制（?raw + import.meta.glob），不依赖 node 类型。
 */
import { describe, it, expect } from 'vitest';
import genRaw from '@/types/api.generated?raw';

/** src/web 全量源码语料（含本文件；断言目标名时不影响——EXEMPT/定义点已排除判定） */
const corpusModules = import.meta.glob('/src/web/**/*.{ts,tsx}', {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>;

const corpus = Object.entries(corpusModules)
  .filter(([p]) => !p.endsWith('api.generated.ts') && !p.endsWith('api-contract.test.ts'))
  .map(([, src]) => src)
  .join('\n');

/** api/ 层语料（测试 B 用） */
const apiModules = Object.entries(corpusModules)
  .filter(([p]) => /\/src\/web\/api\/[^/]+\.ts$/.test(p))
  .map(([, src]) => src);

/** 无前端消费路径的生成物（与 types/index.ts 豁免清单同源；新增需附原因） */
const EXEMPT: Record<string, string> = {
  ChatResponse: '前端 AgentChatResponse/ChatResponse 手写镜像（state 视图态）',
  ProjectStateResponse: '后端宽松 schema（Dict 对应）',
  ModelFallbackPatch: '前端 fallback 设置走 runtime PUT（RuntimeSettingsUpdate）',
  TimelinePushRequest: 'B9b 时间线回放由 Agent 任务流下发，前端暂无按钮消费',
  Body_upload_files_api_ai_upload_post: 'multipart 上传非 JSON 契约',
  DraftCreate: '草稿创建走手写保留通道（stores/studio 手写强类型）',
  DraftPatch: '同上',
  GroupPatch: '同上',
};

/** api/ 内与生成物同名、刻意保留的手写 interface（豁免清单登记项） */
const SHADOW_WHITELIST = new Set([
  'ProjectListResponse', 'OkWithStateResponse', 'ProvidersResponse',
]);

describe('契约桥接', () => {
  const schemaNames = Array.from(genRaw.matchAll(/^export interface (\w+)/gm)).map((m) => m[1]);

  it('生成物 schema 全部被消费或登记豁免（消费面只升不降）', () => {
    expect(schemaNames.length).toBeGreaterThan(0);
    const missing: string[] = [];
    for (const name of schemaNames) {
      if (EXEMPT[name]) continue;
      if (!new RegExp(`\\b${name}\\b`).test(corpus)) missing.push(name);
    }
    expect(missing, `未消费且未豁免的生成物 schema: ${missing.join(', ')}`).toEqual([]);
  });

  it('EXEMPT 白名单不含已长出消费方的过期条目', () => {
    const stale: string[] = [];
    for (const name of Object.keys(EXEMPT)) {
      // 豁免项一旦长出真实消费方（import 该名字），应移出白名单回归门禁
      const re = new RegExp(`import[^;]*\\b${name}\\b[^;]*from\\s+['"]@/types/api\\.generated`);
      if (re.test(corpus)) stale.push(name);
    }
    expect(stale, `豁免已过期（已有 import 消费）: ${stale.join(', ')}`).toEqual([]);
  });

  it('api/ 层无未登记的同名手写遮蔽', () => {
    const offenders: string[] = [];
    for (const src of apiModules) {
      for (const m of src.matchAll(/^export interface (\w+)/gm)) {
        if (schemaNames.includes(m[1]) && !SHADOW_WHITELIST.has(m[1])) {
          offenders.push(m[1]);
        }
      }
    }
    expect(offenders, `同名遮蔽未登记: ${offenders.join(', ')}`).toEqual([]);
  });
});
