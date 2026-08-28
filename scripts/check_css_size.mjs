#!/usr/bin/env node
/**
 * CSS 体积棘轮（任务 #9）：构建产物 CSS 总体积只许减、不许增。
 *
 * 度量口径：解析 static/dist/index.html 的全部 <link rel="stylesheet" href=...>
 * 引用，汇总引用文件原始字节数（与 check_bundle_size.mjs 任务 #6 同口径：
 * 度量构建产物而非源码）。选产物侧的理由：源 index.css 已随 D-03 清欠拆为
 * 多个子文件，单文件口径失效；产物 CSS 才是用户实际加载的形态，约束力最强。
 *
 * 基线：首钉 153007 字节（2026-08-28 实测 149.42 kB），存
 * scripts/css_size_baseline.txt（与 cov_baseline 同风格）；只许减不许增，
 * 实测超过基线即失败。减重后须同批下调基线文件数值。
 *
 * 退役条件（§13.14(c)，单一归家另见 acceptance.py GATES 表）：
 * 产物 CSS 实测体积降至 100 kB 以下且连续两季无回弹时裁决下账；
 * 或样式体系迁离单文件汇总（按路由懒加载分包）致本口径失效时一并裁决。
 */
import { readFileSync, statSync } from 'node:fs';
import { resolve, dirname, basename } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dist = resolve(root, 'static/dist');
const baselineFile = resolve(root, 'scripts/css_size_baseline.txt');

const html = (() => {
  try {
    return readFileSync(resolve(dist, 'index.html'), 'utf8');
  } catch {
    console.error('[css-ratchet] static/dist/index.html 不存在，请先执行 npm run build');
    process.exit(1);
  }
})();

const baselineBytes = (() => {
  try {
    return parseInt(readFileSync(baselineFile, 'utf8').trim(), 10);
  } catch {
    console.error('[css-ratchet] 基线文件 scripts/css_size_baseline.txt 缺失，棘轮失效');
    process.exit(1);
  }
})();
if (!Number.isFinite(baselineBytes) || baselineBytes <= 0) {
  console.error('[css-ratchet] 基线文件内容非法（应为正整数字节数）');
  process.exit(1);
}

// 属性顺序无关：先抓 <link ...> 标签，再分别探测 rel="stylesheet" 与 href
const linkTags = html.match(/<link\b[^>]*>/g) ?? [];
const cssNames = linkTags
  .filter((tag) => /rel="stylesheet"/.test(tag))
  .map((tag) => tag.match(/href="([^"]+)"/))
  .filter(Boolean)
  .map((m) => basename(m[1]));
if (cssNames.length === 0) {
  console.error('[css-ratchet] 未在 index.html 找到 stylesheet 链接，构建产物可能不完整');
  process.exit(1);
}

let totalBytes = 0;
for (const name of cssNames) {
  try {
    totalBytes += statSync(resolve(dist, name)).size;
  } catch {
    console.error(`[css-ratchet] CSS 产物 ${name} 缺失，构建产物可能不完整，请重新执行 npm run build`);
    process.exit(1);
  }
}

if (totalBytes > baselineBytes) {
  console.error(
    `[css-ratchet] ✗ 产物 CSS 合计 ${(totalBytes / 1024).toFixed(2)} kB（${totalBytes} 字节，`
    + `${cssNames.join(', ')}），超过基线 ${(baselineBytes / 1024).toFixed(2)} kB（${baselineBytes} 字节，只许减不许增）`,
  );
  process.exit(1);
}
console.log(
  `[css-ratchet] ✓ 产物 CSS 合计 ${(totalBytes / 1024).toFixed(2)} kB`
  + `（基线 ${(baselineBytes / 1024).toFixed(2)} kB）`,
);
