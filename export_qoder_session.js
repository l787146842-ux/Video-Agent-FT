import fs from 'node:fs';
import path from 'node:path';

const workspace = process.cwd();
const sessionId = 'a5c458b7-543b-4cf7-99ad-8ffb0177a837';
const secondSessionId = 'dedb0286-f994-4f59-802e-4bea54ebad7c';
const expertDir = 'C:\\Users\\ASUS\\.Qoder\\cache\\experts\\' + sessionId;
const oldProjectTranscript = 'C:\\Users\\ASUS\\.Qoder\\cache\\projects\\自己做agent-683f701d\\conversation-history\\a5c458b7\\a5c458b7.jsonl';
const secondTranscript = 'C:\\Users\\ASUS\\.Qoder\\cache\\projects\\9router-master-dfe62866\\conversation-history\\dedb0286\\dedb0286.jsonl';
const planDir = 'C:\\Users\\ASUS\\AppData\\Roaming\\Qoder\\SharedClientCache\\cache\\plans';
const outputPath = path.join(workspace, 'Qoder-上一个账号-Quest会话导出.md');

function exists(file) {
  try { return fs.existsSync(file); } catch { return false; }
}

function read(file) {
  if (!exists(file)) return `[文件不存在：${file}]`;
  return fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
}

function jsonPretty(file) {
  const raw = read(file);
  try { return JSON.stringify(JSON.parse(raw), null, 2); }
  catch { return raw; }
}

function fence(text, language = '') {
  const runs = [...String(text).matchAll(/`+/g)].map(m => m[0].length);
  const size = Math.max(3, ...(runs.length ? runs : [0]) + 1);
  const mark = '`'.repeat(size);
  return `${mark}${language}\n${text.replace(/\n?$/, '\n')}${mark}`;
}

function listFiles(dir, extension) {
  if (!exists(dir)) return [];
  return fs.readdirSync(dir)
    .filter(name => !extension || name.toLowerCase().endsWith(extension))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
    .map(name => path.join(dir, name));
}

function transcriptAsMarkdown(file) {
  const raw = read(file);
  if (raw.startsWith('[文件不存在')) return raw;
  const rows = [];
  for (const line of raw.split('\n')) {
    if (!line.trim()) continue;
    try {
      const item = JSON.parse(line);
      const role = item.role || item.type || 'unknown';
      const content = item.content;
      let body = '';
      if (Array.isArray(content)) {
        body = content.map(part => {
          if (typeof part === 'string') return part;
          if (part && typeof part.text === 'string') return part.text;
          return JSON.stringify(part, null, 2);
        }).join('\n');
      } else if (typeof content === 'string') {
        body = content;
      } else {
        body = JSON.stringify(content ?? item, null, 2);
      }
      rows.push(`### ${role}\n\n${body.trim() || '(空内容)'}`);
    } catch {
      rows.push(`### 原始行\n\n${line}`);
    }
  }
  return rows.join('\n\n');
}

const lines = [];
const add = value => lines.push(String(value));
add('# Qoder（全球版）上一个账号 Quest 会话恢复材料');
add('');
add('> 导出时间：2026-08-21（Asia/Shanghai）。这是从本机旧账号缓存整理出的只读恢复材料，目标是保留最近结束的 Quest 任务内容，便于继续阅读或人工迁移。');
add('');
add('## 恢复结论');
add('');
add('- 已找到旧账号最近结束的 Quest 任务及其本地专家缓存。');
add('- 未将旧账号数据写入或覆盖当前 Qoder 账号数据库，也未修改登录状态。');
add('- `local.db` 的 `chat_message.content` 是加密字段；本文件不把加密密文冒充正文，也不复制 `secret://...` 状态项。');
add('- 因当前账号认证隔离，尚未验证能否把旧任务真正挂载到当前 Quest 窗口；下面的 Markdown 是可用的离线恢复副本。');
add('');
add('## 账号与数据位置');
add('');
add('| 项目 | 值 |');
add('| --- | --- |');
add('| 旧账号本地用户 ID | `01a0229f-aa1b-79bd-86eb-37cdb5817bfd` |');
add('| 当前账号本地用户 ID | `01a0241b-479a-72ad-8c11-1d28afb18e2d` |');
add('| Quest 会话数据库 | `C:\\Users\\ASUS\\AppData\\Roaming\\Qoder\\SharedClientCache\\cache\\db\\local.db` |');
add('| 全局状态备份（仅记录，不覆盖） | `C:\\Users\\ASUS\\AppData\\Roaming\\Qoder\\User\\globalStorage\\state.vscdb.backup` |');
add('| 旧账号专家缓存 | `' + expertDir + '` |');
add('');
add('## 最近结束的任务（优先恢复）');
add('');
add('| 字段 | 值 |');
add('| --- | --- |');
add('| 标题 | 全面架构与Agent体验深度审核 |');
add('| 会话 ID | `' + sessionId + '` |');
add('| 工作区 | `e:\\07 天问\\自己做agent` |');
add('| 模式 | `experts` |');
add('| 状态 | `Stopped` |');
add('| 创建时间 | `2026-08-21 17:38:24` |');
add('| 最后修改/停止时间 | `2026-08-21 19:31:13` |');
add('| 消息数 | `141`（user 19 / assistant 44 / tool 78） |');
add('| request ID | `16c0b30b-dcda-478d-9129-d37cd87a3c0a` |');
add('| 关联计划 | `C:\\Users\\ASUS\\AppData\\Roaming\\Qoder\\SharedClientCache\\cache\\plans\\飞天全面审核改进计划_a5c458b7.md` |');
add('');
add('## 另一个旧任务');
add('');
add('| 字段 | 值 |');
add('| --- | --- |');
add('| 标题 | 项目深度审核与正向重构 |');
add('| 会话 ID | `' + secondSessionId + '` |');
add('| 工作区 | `e:\\09 Github上的实用工具\\9router-master` |');
add('| 模式 | `experts` |');
add('| 状态 | `Stopped` |');
add('| 创建时间 | `2026-08-21 17:37:59` |');
add('| 最后修改/停止时间 | `2026-08-21 17:38:12` |');
add('| 消息数 | `1`（仅 user） |');
add('');

const planFiles = listFiles(planDir).filter(file => path.basename(file).includes('a5c458b7'));
add('## 关联计划文件');
add('');
if (!planFiles.length) {
  add('未找到文件名包含 `a5c458b7` 的计划文件。');
} else {
  for (const file of planFiles) {
    add(`### ${path.basename(file)}`);
    add(`来源：\`${file}\``);
    add('');
    add(fence(read(file), 'markdown'));
  }
}
add('');

add('## 主专家会话：metadata.json');
add('');
add(`来源：\`${path.join(expertDir, 'metadata.json')}\``);
add('');
add(fence(jsonPretty(path.join(expertDir, 'metadata.json')), 'json'));
add('');

const inboxFiles = listFiles(path.join(expertDir, 'inboxes'), '.json');
add('## 协作收件箱（完整原始 JSON）');
add('');
for (const file of inboxFiles) {
  add(`### ${path.basename(file)}`);
  add(`来源：\`${file}\``);
  add('');
  add(fence(jsonPretty(file), 'json'));
  add('');
}

const agentFiles = listFiles(path.join(expertDir, 'agents'), '.output');
add('## 专家输出（完整明文）');
add('');
for (const file of agentFiles) {
  add(`### ${path.basename(file)}`);
  add(`来源：\`${file}\``);
  add('');
  add(fence(read(file), 'text'));
  add('');
}

const taskFiles = listFiles(path.join(expertDir, 'tasks'), '.json');
add('## 任务状态（完整原始 JSON）');
add('');
for (const file of taskFiles) {
  add(`### ${path.basename(file)}`);
  add(`来源：\`${file}\``);
  add('');
  add(fence(jsonPretty(file), 'json'));
  add('');
}

add('## 普通对话 transcript（可读部分）');
add('');
add(`### ${path.basename(oldProjectTranscript)}`);
add(`来源：\`${oldProjectTranscript}\``);
add('');
add(transcriptAsMarkdown(oldProjectTranscript));
add('');
add(`### ${path.basename(secondTranscript)}`);
add(`来源：\`${secondTranscript}\``);
add('');
add(transcriptAsMarkdown(secondTranscript));
add('');

add('## 原始缓存索引');
add('');
add('- 专家缓存目录：`' + expertDir + '`');
add('- 主收件箱：`' + path.join(expertDir, 'inboxes', 'leader.json') + '`');
add('- 专家明文目录：`' + path.join(expertDir, 'agents') + '`');
add('- 任务状态目录：`' + path.join(expertDir, 'tasks') + '`');
add('- 普通 transcript：`' + oldProjectTranscript + '`');
add('- 第二个任务 transcript：`' + secondTranscript + '`');
add('');
add('> 说明：如果以后要尝试窗口接管，应先备份当前账号状态，并在确认认证上下文后使用 Qoder 自身的会话加载流程；不要用旧的 `state.vscdb.backup` 直接覆盖当前 `state.vscdb`。');

fs.writeFileSync(outputPath, lines.join('\n') + '\n', 'utf8');
console.log(`Wrote ${outputPath} (${fs.statSync(outputPath).size} bytes)`);
