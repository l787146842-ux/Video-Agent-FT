/* eslint-disable */
// 临时脚本：按目录聚合 coverage-final.json 语句覆盖率
const fs = require('fs');
const d = JSON.parse(fs.readFileSync('coverage/coverage-final.json', 'utf8'));
const agg = {};
for (const [f, m] of Object.entries(d)) {
  const norm = f.split('\\').join('/');
  const dir = (norm.match(/src\/web\/([^/]+)/) || [])[1] || 'root';
  agg[dir] = agg[dir] || { s: 0, st: 0 };
  for (const c of Object.values(m.s)) {
    agg[dir].st++;
    if (c > 0) agg[dir].s++;
  }
}
for (const [k, v] of Object.entries(agg)) {
  console.log(k.padEnd(14), (100 * v.s / v.st).toFixed(1) + '%', `(${v.s}/${v.st})`);
}
