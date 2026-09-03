#!/usr/bin/env node
/**
 * 构建体积预算（任务 #6；前端批次1 口径升级）：首屏关键路径总字节超限即失败。
 *
 * 口径新旧对照：
 *   旧口径：仅量 entry chunk（studio-[hash].js，55 kB 上限）——只统计入口脚本，
 *           漏掉浏览器首屏必然并行拉取的 modulepreload 依赖与 CSS，
 *           把真实首屏下载量（≈491 kB）严重低估为 53.8 kB。
 *   新口径：首屏关键路径 = entry module script + 全部 <link rel="modulepreload">
 *           + 全部 <link rel="stylesheet">，取三者原始字节之和（raw，未 gzip）。
 *           这才是首屏渲染阻塞/预载的真实关键路径体量。
 *
 * 上限依据（2026-09-03 实测）：SkillStructuredView（~127 kB）降级为交互触发的
 *   动态 import、移出 modulepreload 后，关键路径 ≈ 376 kB raw；取整上浮到
 *   400 kB 作为单一硬上限，防止首屏体量无声回退。
 * 调整上限请同步更新本文件 CRITICAL_PATH_LIMIT_KB 与本注释。
 */
import { readFileSync, statSync } from 'node:fs';
import { resolve, dirname, basename } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dist = resolve(root, 'static/dist');

/** 首屏关键路径上限（kB，原始字节）= 实测 ~376 kB 上浮取整 */
const CRITICAL_PATH_LIMIT_KB = 400;

const html = (() => {
  try {
    return readFileSync(resolve(dist, 'index.html'), 'utf8');
  } catch {
    console.error('[size-budget] static/dist/index.html 不存在，请先执行 npm run build');
    process.exit(1);
  }
})();

/** 从标签串中提取某属性值（属性顺序无关） */
function attr(tag, name) {
  const m = tag.match(new RegExp(`${name}="([^"]+)"`));
  return m ? m[1] : null;
}

// entry：<script type="module" src=...>
const scriptTags = html.match(/<script\b[^>]*>/g) ?? [];
const entrySrc = scriptTags
  .filter((tag) => /type="module"/.test(tag))
  .map((tag) => attr(tag, 'src'))
  .find(Boolean);
if (!entrySrc) {
  console.error('[size-budget] 未在 index.html 找到入口 module script');
  process.exit(1);
}

// 关键路径依赖：<link rel="modulepreload"> + <link rel="stylesheet">
const linkTags = html.match(/<link\b[^>]*>/g) ?? [];
const preloadHrefs = linkTags
  .filter((tag) => /rel="modulepreload"/.test(tag))
  .map((tag) => attr(tag, 'href'))
  .filter(Boolean);
const cssHrefs = linkTags
  .filter((tag) => /rel="stylesheet"/.test(tag))
  .map((tag) => attr(tag, 'href'))
  .filter(Boolean);

// src/href 形如 /static/dist/xxx-[hash].js（base 前缀），映射回产物目录并去重
const refs = [
  { kind: 'entry', name: basename(entrySrc) },
  ...preloadHrefs.map((h) => ({ kind: 'modulepreload', name: basename(h) })),
  ...cssHrefs.map((h) => ({ kind: 'css', name: basename(h) })),
];
const seen = new Set();
let totalKb = 0;
const lines = [];
for (const { kind, name } of refs) {
  if (seen.has(name)) continue; // 同名去重（entry 与 preload 理论上不重叠，稳妥兜底）
  seen.add(name);
  let sizeKb;
  try {
    sizeKb = statSync(resolve(dist, name)).size / 1024;
  } catch {
    console.error(`[size-budget] 关键路径产物 ${name}（${kind}）缺失，构建产物可能不完整，请重新执行 npm run build`);
    process.exit(1);
  }
  totalKb += sizeKb;
  lines.push(`  - [${kind}] ${name} = ${sizeKb.toFixed(2)} kB`);
}

if (totalKb > CRITICAL_PATH_LIMIT_KB) {
  console.error(
    `[size-budget] ✗ 首屏关键路径合计 = ${totalKb.toFixed(2)} kB，`
    + `超出上限 ${CRITICAL_PATH_LIMIT_KB} kB（entry + ${preloadHrefs.length} modulepreload + ${cssHrefs.length} CSS）:\n`
    + lines.join('\n'),
  );
  process.exit(1);
}
console.log(
  `[size-budget] ✓ 首屏关键路径合计 = ${totalKb.toFixed(2)} kB（上限 ${CRITICAL_PATH_LIMIT_KB} kB；`
  + `entry + ${preloadHrefs.length} modulepreload + ${cssHrefs.length} CSS）:\n`
  + lines.join('\n'),
);
