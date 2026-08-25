#!/usr/bin/env node
/**
 * 构建体积预算（任务 #6）：入口 chunk（首包）超限即失败。
 *
 * 判定方式：解析 static/dist/index.html 的 <script type="module" src=...>
 * 引用（entryFileNames: 'studio-[hash].js'），取该文件原始字节数与上限比对。
 *
 * 上限依据（2026-08-25 实测）：入口 chunk studio-*.js = 50.05 kB（gzip 16.62 kB），
 * 取当前值上浮约 10% → 55 kB，防止体积无声回退。
 * 调整上限请同步更新本文件 ENTRY_LIMIT_KB 与注释。
 */
import { readFileSync, statSync } from 'node:fs';
import { resolve, dirname, basename } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dist = resolve(root, 'static/dist');

/** 入口 chunk 上限（kB，原始字节）= 实测 50.05 kB 上浮 ~10% */
const ENTRY_LIMIT_KB = 55;

const html = (() => {
  try {
    return readFileSync(resolve(dist, 'index.html'), 'utf8');
  } catch {
    console.error('[size-budget] static/dist/index.html 不存在，请先执行 npm run build');
    process.exit(1);
  }
})();
// 属性顺序无关：先抓 <script ...> 标签，再分别探测 type="module" 与 src
const scriptTags = html.match(/<script\b[^>]*>/g) ?? [];
const m = scriptTags
  .filter((tag) => /type="module"/.test(tag))
  .map((tag) => tag.match(/src="([^"]+)"/))
  .find(Boolean);
if (!m) {
  console.error('[size-budget] 未在 index.html 找到入口 module script');
  process.exit(1);
}
// src 形如 /static/dist/studio-[hash].js（base 前缀），映射回产物目录
const entryName = basename(m[1]);
const entryPath = resolve(dist, entryName);
let sizeKb;
try {
  sizeKb = statSync(entryPath).size / 1024;
} catch {
  console.error(`[size-budget] 入口产物 ${entryName} 缺失，构建产物可能不完整，请重新执行 npm run build`);
  process.exit(1);
}

if (sizeKb > ENTRY_LIMIT_KB) {
  console.error(
    `[size-budget] ✗ 入口 chunk ${entryName} = ${sizeKb.toFixed(2)} kB，`
    + `超出上限 ${ENTRY_LIMIT_KB} kB（实测基线 50.05 kB 上浮 ~10%）`,
  );
  process.exit(1);
}
console.log(`[size-budget] ✓ 入口 chunk ${entryName} = ${sizeKb.toFixed(2)} kB（上限 ${ENTRY_LIMIT_KB} kB）`);
