// 解码会话日志，提取外部工人派单的失败详情
import fs from 'node:fs';
import zlib from 'node:zlib';

const file = process.argv[2];
const raw = fs.readFileSync(file);
let text;
try {
  text = zlib.zstdDecompressSync(raw).toString('utf8');
} catch (e) {
  console.log('zstd 解码失败，尝试当纯文本:', e.message);
  text = raw.toString('utf8');
}
const lines = text.split('\n');
console.log('总行数:', lines.length);

const interesting = [];
for (const line of lines) {
  if (!line) continue;
  const low = line.toLowerCase();
  if ((low.includes('subagent') || low.includes('workflow')) &&
      (low.includes('"error"') || low.includes('stopreason') || low.includes('failed') || low.includes('provider'))) {
    interesting.push(line);
  }
}
console.log('相关行数:', interesting.length);
for (const line of interesting.slice(-12)) {
  try {
    const obj = JSON.parse(line);
    const t = obj.type ?? obj.event?.type ?? '?';
    let summary = JSON.stringify(obj.data ?? obj.params?.event?.data ?? {}).slice(0, 500);
    console.log(`--- [${t}] ${summary}`);
  } catch {
    console.log('--- (原始)', line.slice(0, 400));
  }
}
