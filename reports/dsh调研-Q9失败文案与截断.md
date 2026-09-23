# dsh 调研 Q9：工具失败文案的回喂构造与截断策略

> **调研对象**：`E:\07 天问\deepseek-harness-master`（只读，未修改任何文件）
> **调研目的**：为修正本项目 `src/video_agent/core/fc_feedback.py:447` 等「错误文案硬编码 `[:120]`」缺陷提供对照依据
> **方法**：全部结论均来自实际读文件，逐条带 `文件:行号` 与原文摘录。推测部分单独标注。
> **调研日期**：本会话

---

## 结论速览（先读这段）

**dsh 不对失败文案做 120 字截断。** 仓内确实存在唯一的 `120` 常量，但它截的是**消息折叠行摘要元数据**（`source.summary`），不是模型可见正文（`content`）。两者是不同字段，正文始终完整。

**dsh 对错误/指引类文本与大块工具输出用的是同一条超限策略**——不按 `isError` 分流，但按 `PostToolDecision.kind` 分流：`block`（后置纠正反馈）完全不碰，`accept`+`isError`（执行失败）与 `deny`（前置闸机拒收）都会被约束，而约束方式是**保头+保尾+外置全文+省略量声明**，不是"砍掉尾部只留前 N 字"。**任何路径都不做固定字符数硬截断。**

**关键取向差异**：本项目 `[:120]` 是「丢弃信息、无省略标记、无长度说明、无恢复指引」；dsh 是「不丢信息（全文落盘）、保留头尾、显式声明省略多少、给出取回路径」。

**⭐ 全仓唯一的「模型可见错误文本故意不截断」**：`packages/hooks/hook-protocol/src/codec.ts:66-69` —— 阻塞原因 `output.reason` = **完整未截断的 stderr**，而 500 字符上限（`events.ts:53`）**只作用于持久化审计摘要** `stderrSummary`。**同一份 stderr，模型读的那份不设限、存档的那份才设限**——与本项目把 `[:120]` 砍在回喂正文上**恰好相反**（见 §3.9(1)）。

---

## ① 失败信息如何构造

### 1.1 唯一入口：`toolErrorResult()` —— 「Error: 」前缀信封

`packages/core/tools/src/index.ts:1879-1887`

```ts
function toolErrorResult(error: unknown): ToolExecutionResult {
  const info = errorInfo(error)
  const message = errorMessage(error)
  return {
    content: [{ type: 'text', text: `Error: ${message}` }],
    isError: true,
    error: { message, ...info ? { info } : {} },
  }
}
```

**要点**：模型看到的是 `Error: ${message}`（纯文本块）；结构化信息另放 `error` 字段。**此处无任何长度限制**。

### 1.2 消息提取：`errorMessage()` —— 兜底不可失败

`packages/core/tools/src/index.ts:610-624`

```ts
function errorMessage(error: unknown): string {
  try {
    if (error instanceof Error) return error.message
    if (typeof error === 'object' && error !== null
      && 'message' in error && typeof error.message === 'string') {
      return error.message
    }
    return String(error)
  } catch {
    // A hostile thrown value can trap `instanceof`, property access, or string
    // coercion. Error normalization is the outermost safety boundary, so its
    // fallback must itself be total.
    return '<unprintable thrown value>'
  }
}
```

**要点**：`message` 原样保留，不截断、不摘要。

### 1.3 结构化错误身份：`errorInfo()` —— 仅 HarnessError 才有

`packages/core/tools/src/index.ts:643-650`

```ts
function errorInfo(error: unknown): ToolErrorInfo | undefined {
  try {
    return error instanceof HarnessError ? { name: error.name, code: error.code } : undefined
  } catch {
    return undefined
  }
}
```

### 1.4 失败结果的类型契约

`packages/core/tools/src/index.ts:471-485`

```ts
/** Structured error metadata for a failed tool call (alongside the model-facing text). */
export interface ToolErrorInfo {
  name: string
  code: string
  /** Optional raw user-facing detail; durable projections preserve it but model-facing content does not include it. */
  reason?: string
}

/** Canonical failure detail; internal routing information remains optional. */
export interface ToolFailure {
  /** Human-readable failure message without the Native `Error: ` envelope. */
  message: string
  /** Internal error class/code used by policy and durable diagnostics. */
  info?: ToolErrorInfo
}
```

**要点**：注释明确区分「model-facing content」与「durable projections」。`message` 是「不带 `Error: ` 信封的人类可读失败消息」。

`packages/core/tools/src/index.ts:567-576` 定义失败结果类型：

```ts
/** Failed canonical tool execution; failures never carry a successful value. */
export interface ToolExecutionFailure {
  readonly isError: true
  readonly error: ToolFailure
  readonly value?: never
  readonly content: ContentBlock[]
  readonly meta?: JsonValue
  readonly additionalContexts?: UserMessage[]
  readonly concludesTurn?: never
}
```

### 1.5 失败结果如何进入模型上下文（回喂链路）

调用链完整路径：

1. `packages/core/tools/src/index.ts:1563-1564` —— 工具体抛异常 → `catch (error: unknown) { return toolErrorResult(error) }`
2. `packages/core/tools/src/index.ts:1751-1765` —— `postExecute()` 跑 `tools/post-execute` waterfall；`block` 决策把纠正反馈转成 `isError`
3. `packages/core/agent-loop/src/tool-calls.ts:277-289` —— 结果落成 `tool/result` 会话事件：

```ts
const message = createToolResultMessage({
  callId: block.id,
  content: result.content,
  isError: result.isError,
})
session.append('tool/result', {
  turn, step,
  message,
  ...result.error?.info ? { error: result.error.info } : {},
  ...result.meta !== undefined ? { meta: result.meta } : {},
}, { surfaceOp: 'append', sourceEventSeqs: [callSeq] })
```

4. `packages/core/tools/src/index.ts:169` —— 扩展点签名：

```ts
'tools/post-execute'(this: Scoped<ToolRuntime>, exec: ToolExecution, result: Readonly<ToolExecutionResult>, next: () => Promise<PostToolDecision>): Promise<PostToolDecision>
```

### 1.6 block 决策的反馈文本推导

`packages/core/tools/src/index.ts:626-632`

```ts
/** Derive one failure message from policy feedback without changing its rendered blocks. */
function failureMessageFromContent(content: ContentBlock[]): string {
  const text = content
    .map(block => block.type === 'text' ? block.text : `[${block.type} content]`)
    .join('\n')
  return text.length > 0 ? text : 'tool result blocked by post-execute policy'
}
```

**要点**：`content` 是 `decision.feedback` 原样（`index.ts:1760`），**只从 content 派生 message，不改 content**，无截断。

---

## ② 全仓截断点清单

### 2.1 关键澄清：唯一的 `120` 截的是什么

`packages/llm/llm/src/message.ts:109-125`

```ts
/**
 * Bound for a `notice` summary. The account rides a collapsed transcript row
 * and is committed to the durable log, while its inputs — task labels, goal
 * objectives, tool arguments — are caller text with no length of their own.
 */
export const CONTEXT_SUMMARY_MAX_CHARS = 120

/**
 * Bound one `notice` summary to {@link CONTEXT_SUMMARY_MAX_CHARS}.
 * @param summary - the producer's one-line account, of any length.
 * @returns the account, ellipsized when it exceeds the bound.
 */
export function boundContextSummary(summary: string): string {
  return summary.length <= CONTEXT_SUMMARY_MAX_CHARS
    ? summary
    : `${summary.slice(0, CONTEXT_SUMMARY_MAX_CHARS - 1)}…`
}
```

**这是 UI 折叠行摘要，不是模型可见正文。** 字段定义见 `packages/llm/llm/src/message.ts:85-94`：

```ts
  | {
    readonly form: 'notice'
    /** One-line account of what happened, shown without expanding the row. */
    readonly summary: string
  }
```

注释原文 **"shown without expanding the row"** —— 该摘要用于消息在 UI 中**未展开时**的一行账。

**铁证：正文与摘要是两个字段，正文不受 120 限制。**
`packages/subagent/subagent/src/continuation-messages.ts:135-159`：

```ts
export function createSettlementMessage(
  childId: SessionId,
  terminal: ActivationTerminal,
): ReturnType<typeof createUserMessage> {
  const summary = settlementSummary(childId, terminal.stopReason)
  // Parent providers receive this notice as a user message and may reject
  // nontext assistant blocks. Keep this conversion local so SDK/UI consumers
  // retain the complete child output.
  const closingText = (terminal.output ?? []).flatMap(block =>
    block.type === 'text' && block.text.length > 0 ? [block] : [],
  )
  return createUserMessage({
    content: [
      { type: 'text' as const, text: summary },
      ...closingText.length === 0
        ? [{ type: 'text' as const, text: 'It left no closing message.' }]
        : [{ type: 'text' as const, text: 'Its closing message:' }, ...closingText],
    ],
    source: {
      kind: 'subagent-settled' as const,
      form: 'notice' as const,
      summary: boundContextSummary(summary),   // ← 只有 summary 走 120
      senderSessionId: childId,
    },
  })
}
```

`content`（模型可见）是完整摘要 + 子代理完整 closing text；`source.summary`（UI 折叠行）才过 `boundContextSummary`。

**`boundContextSummary` 的全部调用点（5 处，均只写 `source.summary`）：**
| 位置 | 内容 |
|---|---|
| `packages/goal/tool-goal/src/index.ts:329` | `summary: boundContextSummary(\`${args.action as string}: ${goal.objective}\`)` |
| `packages/core/agent/src/model-selection.ts:53` | `summary: boundContextSummary(\`${from} → ${to}\`)` |
| `packages/webhook/webhook/src/session.ts:161` | `summary: boundContextSummary(\`${delivery.kind} webhook handled by ${ruleId}\`)` |
| `packages/jobs/tool-jobs/src/index.ts:142` | `return boundContextSummary(\`${snapshot.kind} ${snapshot.label} ${statusLine(snapshot)}\`)` |
| `packages/subagent/subagent/src/continuation-messages.ts:156` | 见上 |

### 2.2 截断点总表

> **口径说明**：本节为**精选 + 分类**清单（72 条编号行，覆盖全部错误路径与主要输出路径），非逐条穷举。第二轮穷尽审计在 `packages/*/src`、`apps/*/src`、`python/`（排除 tests/generated）内共定位约 **200 处**长度约束点，其中**与本课题相关（模型可见错误/输出）的部分已全部收录本表**；其余为纯 UI/CSS/定时器/并发/类型映射等无关项。§2.3 为第二轮新增的关键项。

分类：(a) 大块工具输出 (b) 错误/诊断/指引文本 (c) 仅 UI/展示/日志 (d) 上下文压缩 (e) 其他

| # | file:line | 阈值 | 策略 | 类别 | 说明（含原文摘录） |
|---|---|---|---|---|---|
| 1 | `packages/llm/llm/src/message.ts:114` + `:121-125` | **120 字符** | 砍头 + `…` | **(c) UI 折叠行** | `CONTEXT_SUMMARY_MAX_CHARS = 120`；`${summary.slice(0, 119)}…`。**只写 `source.summary`，不影响 `content`** |
| 2 | `packages/spill/spill-policy/src/index.ts:96-103` | `maxInlineBytes`（可配，默认**不启用**） | **保头+保尾（中间省略）** | **(a)+(b) 同策略** | `new TextRetainer({ kind: 'headTail', headBytes, tailBytes })`，`headBytes=Math.ceil(budget/2)`、`tailBytes=Math.floor(budget/2)` |
| 3 | `packages/spill/spill-policy/src/index.ts:185-204` | 同上 | 同上 | **(a)+(b)** | 模型可见臂。第 **191 行守卫不过滤 `isError`** |
| 4 | `packages/spill/spill-policy/src/index.ts:212-226` | 同上 | 同上 | (c) 持久日志副本 | `tools/ptc-dispatch-log` 臂，注释：`read sub-calls spill too: the log copy is not model context` |
| 5 | `packages/util/output-retention/src/index.ts:247-387` | 调用方给 | `head`/`tail`/`headTail` | (a) 通用库 | `TextRetainer`；`:93-110` 三种策略；UTF-8 边界安全 |
| 6 | `packages/util/output-retention/src/index.ts:93-99, 269-275` | 调用方给 | 保头 | (a) | `headTail` 策略定义：`Keep a stable prefix and suffix, omitting the middle. Requires reading to the end.` |
| 7 | `packages/util/output-retention/src/index.ts:146-198` | `maxItems` | 保头（items） | (a) | `ItemRetainer`，用于 glob/grep/搜索源。注释：`Only head retention in v1.` |
| 8 | `packages/util/output-retention/src/index.ts:412-421` | — | 省略量声明 | (a)+(b) | `describeOmitted()` → `` `Omitted ${omitted.count} ${unit}.` `` / `More ${unit} were omitted.` |
| 9 | `packages/util/output-retention/src/index.ts:436-443` | — | 省略量 + 恢复指引 | (a)+(b) | `formatRetentionNotice()`，注释：`The library never owns recovery words — only the tool knows the action` |
| 10 | `packages/subprocess/subprocess-local/src/output.ts:84-106` | `maxBytes`（shell 默认 64_000） | **保尾（tail-keep）** | (a) 命令输出 | 注释 `:54-55`：`Tail-keep rationale (pi/OpenCode): errors and final results cluster at the end of command output; the spill file covers the head.` |
| 11 | `packages/subprocess/subprocess-local/src/output.ts:98-101` | 同上 | 尾窗口字节精确 | (a) | `Trim the head so the retained window is byte-exact at the cap` |
| 12 | `packages/shell/tool-bash/src/render.ts:12-15` | 由 10 决定 | 保尾 + 溢出通告 | (a) | `return \`${output.text}\n[output truncated; full output: ${output.spillPath ?? '(unavailable)'}]\`` |
| 13 | `packages/shell/tool-bash/src/index.ts:78` | — | 工具自述 | (b) 指引 | `'Long output is truncated to its tail; the full output is saved to a file whose path is reported when available. '` |
| 14 | `packages/jobs/tool-jobs/src/index.ts:122-134` | `maxBytes` | **保尾** + 固定后缀预留 | (a) | `fitWithSuffix()`：先量后缀字节，再 `retainTail(content, maxBytes - fixedBytes)` |
| 15 | `packages/jobs/tool-jobs/src/index.ts:110-114` | 同上 | tail | (a) | `function retainTail(text, maxBytes) { new TextRetainer({ kind: 'tail', maxBytes }) ... }` |
| 16 | `packages/jobs/tool-jobs/src/index.ts:145-166` | `outputLimitBytes` | 多级降级保尾 | (c) 通知 | 保 `prefix + [notice truncated] + action`，必要时 `retainTail(action, maxBytes)` |
| 17 | `packages/terminal/tool-terminal/src/render.ts:62-66` | `maxBytes` | **保尾** | (a) | `return \`${retain(content, maxBytes - fixedBytes, 'tail')}${suffix}\`` |
| 18 | `packages/terminal/tool-terminal/src/render.ts:93-98` | `maxBytes` | **保头** | (a) | `boundTerminalText()`：`${retain(text, maxBytes - markerBytes, 'head')}${TRUNCATED}` |
| 19 | `packages/fs/tool-fs/src/read-render.ts:11` | `READ_MAX_LINE_LENGTH = 2000` | 砍行尾 + 说明 | (a) 文件内容 | 单行超长截断 |
| 20 | `packages/fs/tool-fs/src/read-render.ts:69-71` | 同上 | 砍头 + 显式说明 | (a) | `` return line.length > maxLineLength ? `${line.substring(0, maxLineLength)}... (line truncated to ${maxLineLength} chars)` : line `` |
| 21 | `packages/fs/tool-fs/src/read-render.ts:14` | `READ_MAX_BYTES = 50 * 1024` | 停止扫描 + 续读指引 | (a) | 窗口字节上限 |
| 22 | `packages/fs/tool-fs/src/read.ts:15` | `READ_LIMIT = 2000` | 行数窗口 | (a) | 默认/最大 `limit` |
| 23 | `packages/fs/tool-fs/src/read-render.ts:155-161` | 由 21 决定 | **给出续读指令** | (a) | `footer = \`(Output capped. Showing lines ${outcome.offset}-${endLine}. Use offset=${endLine + 1} to continue.)\`` |
| 24 | `packages/fs/tool-fs-search/src/search-core.ts:324-328` | `maxBytes` | 保头 | (a) grep 行预览 | `previewLine()` → `new TextRetainer({ kind: 'head', maxBytes })` |
| 25 | `packages/fs/tool-fs-search/src/search-core.ts:344-348` | `maxMatches` | 保头（items） | (a) | `retainGrepMatches()` → `new ItemRetainer<GrepMatch>({ kind: 'head', maxItems: maxMatches })` |
| 26 | `packages/fs/tool-fs-search/src/search-core.ts:359-361` | `maxResults` | 保头（items） | (a) | `retainGlobPaths()` → `new ItemRetainer<string>({ kind: 'head', maxItems: maxResults })` |
| 27 | `packages/fs/tool-fs-search/src/grep.ts:215-225` | 由 25 决定 | 计数头 + **恢复指引** | (a) | `` `Found ${retained.kept} of ${retained.seen} matches` `` + `` `Full grep result stored at: ${spillRef.locator}. ${spillRef.retrievalHint}` `` |
| 28 | `packages/fs/tool-fs-search/src/glob.ts:224-227` | 由 26 决定 | 分页 + 恢复指引 | (a) | `` `${body}\n\n(Showing ${items.length} of ${seen} paths${basis} ${recovery})` `` |
| 29 | `packages/web/web-fetch-http/src/provider.ts:165-175` | `maxBodyChars` | 砍头 | (a) 网页正文 | `const content = truncatedByChars ? decoded.slice(0, this.limits.maxBodyChars) : decoded` |
| 30 | `packages/web/web-fetch-http/src/provider.ts:185-237` | `maxBytes` | 流式字节上限 | (a) | `readCapped()`；注释 `:208-210`：`Only DROPPED bytes count as truncation` |
| 31 | `packages/compaction/compaction-tool-result-pruner/src/config.ts:7-14` | `thresholdChars: 8192` / `headChars: 4096` / `tailChars: 1024` | **保头+保尾（挖中段）** | **(d) 上下文压缩** | `PRUNE_MARKER = '\n\n[... tool result middle pruned ...]\n\n'` |
| 32 | `packages/compaction/compaction-tool-result-pruner/src/index.ts:83-122` | 由 31 决定 | 挖掉中间 | (d) | `pruneContent()`；**不区分 isError**，按字符预算一刀切 |
| 33 | `packages/compaction/compaction-tool-result-pruner/src/index.ts:136-186` | 由 31 决定 | 替换 + 影子定价 | (d) | `pruneSession()`，对所有 `tool/result` 一视同仁 |
| 34 | `packages/context/session-reference/src/projection.ts:151-178` | `maxOutputBytes` | **保头+保尾 + 精确省略量** | (a) | 二分搜索预算；`` const candidate = `${result.text}\n[… omitted ${omitted} UTF-8 bytes …]` `` |
| 35 | `packages/context/session-reference/src/projection.ts:161` | 由 34 决定 | headTail | (a) | `const retainer = new TextRetainer({ kind: 'headTail', headBytes, tailBytes })` |
| 36 | `packages/subagent/subagent/src/out-of-process.ts:20-42` | `MAX_SUBAGENT_DIAGNOSTIC_BYTES = 4_096` | **保头 + UTF-8 安全 + 后缀** | **(b) 失败诊断** | `limitSubagentDiagnostic()`，见 §④ |
| 37 | `packages/subagent/subagent/src/out-of-process.ts:37-39` | 同上 | 防切多字节 | (b) | `while (((bytes[prefixBytes] as number) & 0b1100_0000) === 0b1000_0000) { prefixBytes -= 1 }` |
| 38 | `packages/workflow/tool-workflow/src/index.ts:35` | `maxResultChars`（默认 **50000**） | 砍头 + 省略量 | (e) 工具渲染 | `Rendered-result ceiling, in characters: a longer JSON value is truncated with a notice (default 50000).` |
| 39 | `packages/workflow/tool-workflow/src/index.ts:198-200` | 同上 | 砍头 + 计数 | (e) | `` `${rendered.slice(0, maxChars)}\n… [truncated: ${rendered.length - maxChars} more characters]` `` |
| 40 | `packages/workflow/tool-ralph/src/index.ts:349-356` | `maxChars` | 砍头 + 固定通告 | (e) | `TRUNCATION_NOTICE = '\n… [truncated]'`；`boundResult()` |
| 41 | `packages/hooks/hook-protocol/src/events.ts:53` | `DEFAULT_STDERR_SUMMARY_MAX_CHARS = 500` | 砍头 + `…` | **(c) 审计摘要** | `summarizeStderr()`；`:67` `t.length > maxChars ? t.slice(0, maxChars) + '…' : t` |
| 42 | `packages/guard/repeat-tool-reminder/src/index.ts:118-121` | `cap` | 砍头 + 省略量 | **(b) 提醒文本** | `` return `${canonical.slice(0, cap)}… (+${canonical.length - cap} more chars)` `` |
| 43 | `packages/lsp/tool-lsp/src/render.ts:122-125` | `maxChars`（默认 16000） | 砍头 + 显式 limit | (a) | `const notice = \`\n… ${label} truncated (limit ${maxChars} characters).\`` |
| 44 | `packages/api/workspace-files/src/index.ts:78` | `maxFileBytes` | **拒绝而非截断** | (a) | `Inclusive byte cap on a complete-file read; larger files are refused, never truncated.` |
| 45 | `packages/api/workspace-files/src/index.ts:71-76` | `maxBytes` | **拒绝而非截断** | (a) | `A page above this fails; it is not shortened, because a silently cut page reads as the whole page.` |
| 46 | `packages/mcp/mcp-client/src/tools.ts:72` | 64 字符 | 砍长 + 哈希 | (e) 名称 | `truncation to the DeepSeek function-name contract (64 chars, ...)` — **协议约束，非内容策略** |
| 47 | `packages/bundle/headless/src/json-stream.ts:34,52-61` | `maxBytes` | 按字节截断 UTF-8 | (c) 外部事件流 | `Per-string and per-key byte cap; longer values are truncated and flagged.` |
| 48 | `packages/context/session-reference/src/projection.ts:170` | — | 省略量文字 | (a) | `` `[… omitted ${omitted} UTF-8 bytes …]` `` |
| 49 | `packages/skill/tool-skill/src/index.ts:27` | `DEFAULT_CATALOG_DESCRIPTION_MAX_LENGTH = 500` | 砍头 + `...` | (c) 目录展示 | 技能目录条目描述上限（模型可见的 catalog 段） |
| 50 | `packages/skill/tool-skill/src/index.ts:391-393` | 由 49 决定 | 砍头 + `...` | (c) | `` return normalized.length <= maxLength ? normalized : `${normalized.slice(0, maxLength - 3)}...` `` |
| 51 | `packages/lsp/tool-lsp/src/render.ts:18,20-21` | `DEFAULT_MAX_LOCATIONS = 100` / `DEFAULT_MAX_RESULT_CHARS = 16_000` | 位置数省略 + 总长上限 | (a) | `Default cap on the complete rendered tool result, including truncation metadata.` |
| 52 | `packages/mcp/mcp-client/src/tools.ts` / `packages/boot/plugin-manager/src/operations.ts:116-164` | `outputBytes` | 保尾诊断 | (c) | `truncated = Buffer.byteLength(diagnostic) > options.outputBytes` |

### 2.3 补充：第二轮穷尽审计新增的关键截断点

以下由独立穷尽审计（覆盖 `packages/*/src`、`apps/*/src`、`python/`，排除 tests/generated）补充，均已由本报告复核源码确认：

| # | file:line | 阈值 | 策略 | 类别 | 说明（含原文摘录） |
|---|---|---|---|---|---|
| 53 | `packages/hooks/hook-protocol/src/codec.ts:66-69` | **无上限** | **不截断** | **(b) 模型可见** | ⭐ **全仓唯一的「错误文本故意不截断」实现**：`if (exitCode === BLOCKING_EXIT_CODE) { output.decision = 'block'; if (trimmedErr.length > 0) output.reason = trimmedErr }` —— 阻塞原因 = **完整未截断的 stderr**，而 500 上限只作用于 `stderrSummary` 审计字段（`events.ts:64-67`）。**「模型可见的错误文本不设限、仅持久化摘要设限」——与本项目 `[:120]` 恰好相反** |
| 54 | `packages/compaction/compaction-tool-result-pruner/src/index.ts:136-150` | 8192/4096/1024 | **挖中段（保头+保尾）** | **(d) 但**含模型可见错误** | ⭐ **该包 `src/` 内 grep `isError` 零命中**——按 `event?.type === 'tool/result'` 一视同仁选中。测试 `tests/tool-result-pruner.spec.ts:189-207` 显式构造 `isError: true, error: { name:'ExitError', code:'EXIT_1' }` 并断言**被剪**（`:203` `expect(result.pruned).toHaveLength(1)`）。人读错误正文被挖中段，结构化 `error.code` 存活 |
| 55 | `packages/fs/tool-fs-search/src/search-core.ts:50`（接线 `:244`） | `SEARCH_STDERR_MAX_BYTES = 64*1024` | **保尾** | **(b)** | ⭐ **错误文本被截得比成功更狠**：stderr 只保尾，而**失败原因通常在头部**。唯一信号是字面后缀 `:116` `` return truncated ? `${text} [stderr truncated]` : text ``。经 `:127`/`:129` 嵌入模型可见 `SearchError` |
| 56 | `packages/deliverables/workspace-changes/src/git.ts:11,64,90` | `STDERR_TAIL_BYTES = 16*1024`（vs `outputMaxBytes` 默认 8 MiB，差 512×） | **保尾** | **(b)** | ⭐ `:90` `` throw new Error(`${what} failed: ${result.stderr.trim()}`) ``。`:79` `truncated: stdout.lossy` **只跟踪 stdout**，`:77` 丢弃 stderr 的 `lossy` ⇒ **该路径无任何截断标记** |
| 57 | `packages/shell/bash-local/src/index.ts:190-191`、`packages/shell/pwsh-local/src/index.ts:237-238` | stdout 可**逐调用调高**；stderr 硬绑 `maxOutputBytes`（默认 64_000，`bash-local:109`/`pwsh-local:135`） | 保尾（stderr） | **(b)** | ⭐ **调用方只能调高 stdout，stderr 被钉死** |
| 58 | `packages/workflow/tool-ralph/src/index.ts:354` | `maxChars` | 砍头，**标记在预算内** | **(b) 唯一'失败报告被砍到只剩标记碎片'** | ⭐ `if (maxChars <= TRUNCATION_NOTICE.length) return TRUNCATION_NOTICE.slice(0, maxChars)`；`:384-389` `renderRoundFailure` 把**子代理失败文本**送同一 `boundResult` ⇒ 极小 cap 下**失败报告被砍成它自己 `… [truncated]` 标记的碎片**。同类「标记占预算」另有 `jobs/tool-jobs/src/index.ts:164`、`terminal/tool-terminal/src/render.ts:64,96`、`web/tool-web/src/fetch.ts:335` |
| 59 | `packages/boot/plugin-manager/src/operations.ts:134-136,157-158` | tail 16384 / head 16384 | 保尾/保头 | (b) | `index.ts:366,442` 抛出**已截断**文本 |
| 60 | `packages/experimental/ptc-runtime-python/src/index.ts:724-760,810,542` | `maxValueBytes` 默认 32_768 | `capMessage` 砍头 | (b) | 标记 `'… [truncated]'` |
| 61 | `packages/session-query/session-query/src/query.ts:269-293` | 240 | **挖中段** | (a) | 查询结果中间省略 |
| 62 | `packages/subprocess/subprocess-local/src/output.ts:86,90-103` | `maxBytes` | **保尾、字节精确** | (a) | 已见 §2.2 #10、§4.3 |
| 63 | `apps/desktop/src/fatal-recovery.ts:18,20` | 末 8 行 / 1200 字 | 保尾 | (c) | 崩溃恢复日志 |
| 64 | `apps/desktop/src/host-process.ts:25,131` | 64 KiB | 保尾 | (c) | host stderr |
| 65 | `packages/bundle/headless/src/json-stream.ts:16-19` | `MAX_STRING_BYTES = 8*1024` / `MAX_EVENT_BYTES = 32*1024` / `MAX_DEPTH = 64` | 逐串砍 | (c) | 外部 JSON 事件流 |
| 66 | `packages/session-query/.../list.ts:65,243` | 240 code points | 砍头 | (c) | `truncateUnicodeCodePoints` |
| 67 | `packages/llm/llm-deepseek/src/protocols/chat-completions/translate.ts:149` | **120** | 砍头 | (c) 异常内嵌 | `` throw new LlmError(`malformed SSE payload: ${payload.slice(0, 120)}`, 'MALFORMED_RESPONSE') `` —— **这是全仓第二个 120，同样是诊断/日志用途，不是回喂给模型的错误正文** |
| 68 | `packages/core/system-prompt/src/index.ts:339` | 16 | 砍头 | (c) | 异常消息内嵌片段 |
| 69 | `packages/core/tools/src/py-types.ts:288,340-341` | `MAX_CLASS_NAME_BASE = 120` | 砍头 | (e) | Python 类型映射 |
| 70 | `packages/core/tools/src/py-types.ts:329,638-641` | `MAX_LIST_NESTING = 180` | 降级为 `Any` | (e) | 非文本截断 |
| 71 | `packages/skill/tool-skill/src/index.ts:27,391-393` | `DEFAULT_CATALOG_DESCRIPTION_MAX_LENGTH = 500` | 砍头 + `...` | (c) | 技能目录描述 |
| 72 | `python/sdk/src/deepseek_harness/client.py:60`（渲染 `:455`，抛出于 `:167,307-310,435`） | `deque(maxlen=400)` | **保尾环形缓冲** | (c) **SDK 调用方，非模型可见** | `python/` 全目录**仅 9 个 .py 文件、仅此 1 处截断**（另有 1 处在测试 `manual_sdk_agent_smoke.py:88`）。无省略标记、单行长度不限。**⇒ dsh 的 Python 侧对「回喂给模型」的失败文案零截断** |

**⚠️ 被排除的假阳性**（第二轮审计确认，非文本截断）：`Math.trunc()`（`core/agent-loop/src/inbox.ts:207,212`）；fs `truncate()` 系统调用（`session-persistence-jsonl/src/index.ts:16,840,1279,1289`）；路径/前缀解析 `slice()`（`util/crypto:40`、`client/connection/.../random-uuid.ts:13` 等）；`content.ts` 的数组拷贝前缀 `blocks.slice(0, index)`（6 处）；schema `z.string().max()`（**拒绝**而非截断）；**拒绝而非截断**的守卫（`FS_TOO_LARGE`、`WEB_FETCH_TOO_LARGE`（`web-fetch-http/src/provider.ts:189-191`）、`api/workspace-files/src/index.ts:126,372,385`）；`web-search-*` 的 `truncated: false`（provider 契约声明，无切割）；UI 的 CSS `MAX_HEIGHT`；定时器/并发上限（`MAX_TIMER_DELAY_MS`、`maxParallelToolCalls`、`maxGoalRounds`）。

### 2.4 与本项目 `[:120]` 最相关的对照

| 维度 | dsh | 本项目现状 |
|---|---|---|
| 错误正文长度上限 | **无字符硬顶**（仅 `maxInlineBytes` 字节软顶，默认不启用） | `[:120]` 硬编码 |
| 超限策略 | 保头+保尾，中间省略 | 纯砍尾 |
| 省略标记 | 有（`…` / `Omitted N bytes.`） | **无** |
| 长度说明 | 有（省略多少字节） | **无** |
| 全文去向 | 落盘 + 回喂定位符 | **直接丢弃** |
| 恢复指引 | 有（`Use read with offset/limit, or grep this path...`） | **无** |

---

## ③ 错误类 vs 大输出的策略差异（关键问题取证）

### 3.0 修正声明（第二版）

本节第一版写作「dsh 没有被特殊豁免」，**该表述已被推翻并修正**。经船长交叉复核 + 源码复验，dsh 确实存在豁免，但**豁免判据不是 `isError`，而是 `PostToolDecision.kind`**。

⚠️ **同时必须指出：船长给出的「闸机拒收 = `kind:'block'`」映射在 dsh 源码里不成立**，这一点直接决定本项目该怎么改，见 §3.2 的三路对照。请以本节为准。

### 3.1 直接回答

**dsh 不按 `isError` 标志分流**——判据是 `PostToolDecision.kind`（`accept` vs `block`）。同一份错误文本，走 `accept` 会被 spill，走 `block` 则**完全不动**。

**证据**：`packages/spill/spill-policy/src/index.ts:185-204`（模型可见臂全文）

```ts
  ctx.on('tools/post-execute', async (exec, result, next): Promise<PostToolDecision> => {
    // Delegate first so a downstream listener (e.g. a hook) settles the result;
    // we bound whatever it accepted. A block passes through — spill only shapes
    // accepted plain-text results, never corrective feedback.
    const decision = await next()
    // Skip `read` to avoid a read → spill → read again loop.
    if (decision.kind !== 'accept' || Object.hasOwn(decision, 'value')
      || exec.parent !== undefined || exec.name === 'read') return decision

    const content = decision.content ?? result.content
    const text = flattenPlainText(content)
    if (text === undefined) return decision
    const totalBytes = Buffer.byteLength(text, 'utf8')
    if (totalBytes <= maxInlineBytes) return decision

    const replacedText = await spillReplacement(text, totalBytes, ownerSessionId(exec), exec.name, exec.callId, 'result')
    if (replacedText === undefined) return decision
    const replaced: ContentBlock[] = [{ type: 'text', text: replacedText }]
    return { kind: 'accept', content: replaced, ...decision.additionalContexts ? { additionalContexts: decision.additionalContexts } : {} }
  }, { prepend: true })
```

**第 191 行的守卫条件逐项拆解**——共 4 个排除项，**没有一个是 `result.isError`**：

| 守卫条件 | 排除什么 | 是否排除错误 |
|---|---|---|
| `decision.kind !== 'accept'` | 只排除 `block` 决策（纠正反馈） | ❌ 否。工具体抛异常产生的 `isError` 结果**仍是 accept 决策**（默认 `{ kind: 'accept' }`，见 `core/tools/src/index.ts:1754`），因此会被 spill |
| `Object.hasOwn(decision, 'value')` | 排除 value 替换（需注册表重渲染） | ❌ 否 |
| `exec.parent !== undefined` | 排除嵌套 PTC 子调用 | ❌ 否 |
| `exec.name === 'read'` | 排除 `read` 工具（防 read→spill→read 循环） | ❌ 否 |

### 3.2 三条路径对照表（核心修正）

dsh 的 `tools/post-execute` 上共有**三种**形态，必须分开写：

| # | 路径 | dsh 类型 | 工具体跑了吗 | 到 post-execute 吗 | spill/截断策略 |
|---|---|---|---|---|---|
| **A** | **工具执行失败**（跑了但抛错 / 输出过大） | `accept` + `isError:true` | 是 | 是 | **会 spill**：保头保尾预览 + 定位符 |
| **B** | **前置闸机拒收** | `PreToolDecision` `{kind:'deny'}` → 内部转成 `post-result` | **否** | **是** | **会 spill**（与 A 同口径） |
| **C** | **后置纠正反馈** | `PostToolDecision` `{kind:'block'}` | 是 | 是（本身就是 post 阶段） | **完全不碰**：`return decision` 提前返回 |

**⚠️ 关键澄清**：船长复核意见把「本项目闸机拒收」映射为 dsh 的 `kind:'block'`，**该映射在源码里不成立**。dsh 的 `block` 是**后置**（post-execute）决策，而前置闸机拒收是 `deny`，两者是不同阶段的不同类型：

- `deny` 定义在 `packages/core/tools/src/index.ts:589-593`（**pre**-execute）：
  ```ts
  export type PreToolDecision =
    | { kind: 'allow' }
    | { kind: 'deny'; reason: string; info?: ToolErrorInfo }
    | { kind: 'cancel' }
    | { kind: 'ask'; reason?: string }
  ```
- `block` 定义在 `packages/core/tools/src/index.ts:599-602`（**post**-execute）：
  ```ts
  export type PostToolDecision =
    | { kind: 'accept'; content?: ContentBlock[]; value?: never; additionalContexts?: UserMessage[] }
    | { kind: 'accept'; value: JsonValue; content?: never; additionalContexts?: UserMessage[] }
    | { kind: 'block'; feedback: ContentBlock[]; additionalContexts?: UserMessage[] }
  ```

**路径 B 确实会被 spill——机械取证**：`deny` 在 prepare 阶段被转成 `post-result`：

`packages/core/tools/src/index.ts:1496-1508`
```ts
      const denialReason = decision.kind === 'allow' ? this.guardReason(exec) : decision.reason
      const denialInfo = decision.kind === 'deny' ? decision.info : undefined
      if (denialReason !== undefined) {
        return await next({
          kind: 'post-result',
          exec,
          result: this.materializeFinalResult({
            content: [{ type: 'text', text: `Error: ${denialReason}` }],
            isError: true,
            error: { message: denialReason, ...denialInfo === undefined ? {} : { info: denialInfo } },
          }),
        })
      }
```

`kind: 'post-result'` 随后经调度器走到 post-execute：

`packages/core/tools/src/index.ts:1360-1361`
```ts
      case 'post-result':
        return await this.finalizeScheduledExecution(prepared.exec, prepared.result)
```

`packages/core/tools/src/index.ts:1618-1620`
```ts
  private async finalizeScheduledExecution(exec: ToolRunContext, result: ToolExecutionResult): Promise<ToolExecutionResult> {
    try {
      const postResult = await this.postExecute(exec, result)
```

⇒ **`deny` 的拒收文案会经过 `tools/post-execute`**，而 spill-policy 的卫兵（`:191`）对该结果返回的是默认 `{kind:'accept'}`，**因此会被 spill 约束**（前提是超过 `maxInlineBytes`）。

旁证（dsh 自己的流水线不变式测试，把 denial 与 post-execute 列为合法阶段顺序）：
`packages/core/tools/tests/invariant.spec.ts:58-62`
```ts
    const denied = execution({ callId: ToolCallId('call-2') })
    await stage(ctx, 'tools/pre-execute', denied)
    await ctx.waterfall(ctx as never, 'tools/post-execute', denied, outcome(), () => Promise.resolve({ kind: 'accept' as const }))
```

**路径 C 的豁免是真实的**（船长引用的注释逐字属实）：
`packages/spill/spill-policy/src/index.ts:186-192`
```ts
    // Delegate first so a downstream listener (e.g. a hook) settles the result;
    // we bound whatever it accepted. A block passes through — spill only shapes
    // accepted plain-text results, never corrective feedback.
    const decision = await next()
    // Skip `read` to avoid a read → spill → read again loop.
    if (decision.kind !== 'accept' || Object.hasOwn(decision, 'value')
      || exec.parent !== undefined || exec.name === 'read') return decision
```
`block` 的落点在 `packages/core/tools/src/index.ts:1757-1763`：
```ts
    if (decision.kind === 'block') {
      const message = failureMessageFromContent(decision.feedback)
      return this.markCanonical(exec, {
        content: decision.feedback,
        isError: true,
        error: { message },
```
即 `feedback` 原样成为 `content`。**`block` 的 feedback 在任何阶段都不被 spill 触碰。**

### 3.3 对本项目的映射（修正后）

| 本项目 | 对应 dsh 路径 | dsh 是否会截断 |
|---|---|---|
| `card_media_gate` 等**前置闸机拒收**（`fc_tool_runner.py:487-489` `c.gate_error = chain.error`，工具体未执行） | **B（`deny`）** | **会**——但方式是头尾预览+定位符，**不是砍到 120** |
| 工具体执行失败（`:837-847` → `compose_failure_feedback`） | **A（`accept`+`isError`）** | **会**——同上 |
| （本项目暂无对应物） | **C（`block`）** | **完全不动** |

**⇒ 结论不变但理由要改**：本项目 `fc_feedback.py:447` 的 `[:120]` 必须去掉，但**不是**因为「dsh 豁免闸机文案」（该豁免在 dsh 只覆盖 post-execute 的 `block`，不覆盖前置闸机拒收），而是因为 **dsh 在任何一条路径上都不做固定字符数硬截断**：短则全留，长则「头尾预览 + 省略量 + 全文外置 + 定位符」。

### 3.4 铁证：测试用例标题就是「failure capture」

`packages/spill/spill-policy/tests/spill-policy.spec.ts:211-241`

```ts
describe('outer PTC mode failure capture', () => {
  it('spills the bounded output-limit diagnostic through the ordinary outer-result policy', async () => {
    const ctx = new Context()
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(ToolRuntime, { mode: 'ptc' })
    await ctx.plugin(StubStore)
    await ctx.plugin(SpillPolicy, { maxInlineBytes: 200 })
    await mountRuntime(ctx, { maxOutputBytes: 500 })
    const events: unknown[] = []
    const agent = observedAgent(ctx, 'code-spill', (_type: string, data: unknown) => { events.push(data) })

    const result = await ctx.tools.execute({
      signal: testToolSignal,
      callId: ToolCallId('code-output-limit'),
      name: 'run_code',
      arguments: {
        code: 'console.log("HEAD-" + "x".repeat(300)); console.log("TAIL-" + "y".repeat(300)); return "unreachable";',
        description: 'Print oversized head and tail lines',
      },
      agent: agent as never,
    })

    expect(result.isError).toBe(true)                                    // :233 ← 失败结果
    const saved = (ctx.spillStore as StubStore).saves
    expect(saved).toHaveLength(1)                                        // :235 ← 确实被 spill
    expect(saved[0]?.source).toMatchObject({ toolName: 'run_code' })
    expect(saved[0]?.content).toContain('code run failed (output-limit)') // :237 ← 全文含错误
    expect(saved[0]?.content).toContain('HEAD-')
    expect(textOf(result.content)).toContain('Full formatted result stored at: /spill/run_code.txt') // :239 ← 回喂定位符
    expect(events).toEqual([])
  })
})
```

**`:233` 与 `:239` 同时成立**——这是一个 `isError: true` 的失败结果，被替换成「头尾预览 + spill 定位符」。**错误信息没有被特殊放行，也没有被砍头丢弃。**

### 3.5 但存在一个「相对豁免」：错误内容通常够短，不会触发

`spill-policy` 的入口条件是字节数超 `maxInlineBytes`（`:198` `if (totalBytes <= maxInlineBytes) return decision`）。dsh 的错误正文（`Error: ${message}`）通常远小于阈值，**因此错误文本事实上极少被截断**——不是因为有豁免规则，而是因为错误消息本身设计得短。

### 3.6 dsh 对「大输出」反而有额外限制，对错误没有

`packages/spill/spill-policy/src/index.ts:29-32`（模块自述）

```
 * - `read` is skipped by the model-facing arm to avoid a
 *   `read → spill → read again` loop; the dispatch-log arm bounds `read`
 *   sub-calls too (a log copy is not model context, and `read` is precisely
 *   the tool that produces huge logs).
```

**取向清楚**：被额外限制的是「产生巨量日志的工具」（`read`），不是错误。

### 3.7 唯一的按 `isError` 分流：jobs 的输出可见性

`packages/jobs/tool-jobs/src/index.ts:241-255`

```ts
    if (exec.name === 'job_output' && !result.isError) {
      // This definition owns and schema-validates the canonical value. Preserve
      // its output/status split only while policy left the default rendering intact.
      const value = result.value as unknown as { text: string; job: PublicJobSnapshot }
      const body = value.text.length > 0 ? value.text : '(no new output)'
      const content = body.endsWith('\n') ? body.slice(0, -1) : body
      const suffix = `\n${statusLine(value.job)}`
      if (rawSingleText(result.content) === `${content}${suffix}`) {
        return [{
          type: 'text',
          text: fitWithSuffix(content, suffix, maxBytes, '\n[output truncated]'),
        }]
      }
    }
    return boundSingleText(result.content, maxBytes)
```

**注意**：`!result.isError` 分支走的 `fitWithSuffix` 是**保尾**（保留状态行），`else` 分支 `boundSingleText`（`:175-182`）同样按 `maxBytes` 保尾。**两个分支都截断，错误分支并不更宽松**。

### 3.9 第二轮穷尽审计新增：两处直接改变结论的发现

#### (1) ⭐ 唯一「模型可见错误文本故意不截断」的实测对照 —— hooks

`packages/hooks/hook-protocol/src/codec.ts:59-69`

```ts
export function parseHookOutput(exitCode: number | undefined, stdout: string, stderr: string, expectedEventName?: string): HookOutput {
  const trimmedErr = stderr.trim()
  const trimmedOut = stdout.trim()
  // Plain stdout remains available even when it is not JSON.
  const output: HookOutput = { exitCode, stderr: trimmedErr, stdout: trimmedOut }

  // Both dialects treat exit 2 as a block with stderr as its reason.
  if (exitCode === BLOCKING_EXIT_CODE) {
    output.decision = 'block'
    if (trimmedErr.length > 0) output.reason = trimmedErr
  }
```

**同一份 stderr，两个去向，两种待遇**：

| 去向 | 上限 | 证据 |
|---|---|---|
| **模型可见的阻塞原因** `output.reason` | **无** | `codec.ts:68` `output.reason = trimmedErr`（完整） |
| 持久化审计摘要 `stderrSummary` | **500 字符** | `events.ts:53` `DEFAULT_STDERR_SUMMARY_MAX_CHARS = 500`；`:64-67` `summarizeStderr()` `t.slice(0, maxChars) + '…'` |

**⇒ 这是全仓最接近「错误文本豁免截断」的实现，且它的方向恰好是本项目需要的**：模型读的那份**不设限**，只为**持久化/展示**的那份设限。而本项目 `fc_feedback.py:461` 把截断后的 `raw` 拼进**回喂给模型**的字符串——**正好搞反了**。

#### (2) ⚠️ 但「错误不豁免」在 compaction 上成立且更狠 —— 挖中段

`packages/compaction/compaction-tool-result-pruner/src/index.ts:136-150`

```ts
  pruneSession(session: Session): PruneResult {
    const candidates: SnapshotCandidate[] = []
    for (const seq of [...session.surface.nodes]) {
      const event = session.eventAt(seq)
      if (event?.type === 'tool/result') candidates.push({ seq, event })
    }
```

选中条件**只有** `event?.type === 'tool/result'`，**不查 `isError`**（该包 `src/` 内 grep `isError` **零命中**）。其自身测试显式覆盖并断言剪掉错误结果：

`packages/compaction/compaction-tool-result-pruner/tests/tool-result-pruner.spec.ts:189-207`

```ts
    const originalSeq = appendToolStep(session, 1, 'one', [{
      type: 'text',
      text: 'x'.repeat(100),
    }], {
      isError: true,
      error: { name: 'ExitError', code: 'EXIT_1' },
      meta: { diff: ['a', 'b'] },
      futureField: { nested: true },
    })
    ...
    const result = service().pruneSession(session)
    expect(result.pruned).toHaveLength(1)      // ← isError 结果照样被剪
```

**⇒ 精确表述**：dsh 对**模型可见的失败正文**在 `accept`/`deny` 路径上**不豁免**，超限即「保头 4096 + 标记 + 保尾 1024」（pruner 默认，`config.ts:11-13`）；人读正文被挖中段，结构化 `error.code` 存活。**豁免只存在于 hooks 的 `block` reason 这一处**（并入 §3.2 路径 C 的变体）。

#### (3) ⚠️ 「错误被截得比成功更狠」的三个反例（值得警惕，别照搬）

| 位置 | 现象 |
|---|---|
| `packages/fs/tool-fs-search/src/search-core.ts:50`（接线 `:244`，嵌入 `:127`/`:129`） | `SEARCH_STDERR_MAX_BYTES = 64*1024`，stderr **只保尾**，而**失败原因通常在头部**；唯一信号是 `:116` `` return truncated ? `${text} [stderr truncated]` : text `` |
| `packages/deliverables/workspace-changes/src/git.ts:11,64,90` | `STDERR_TAIL_BYTES = 16*1024` 对比 `outputMaxBytes` 默认 8 MiB（**小 512 倍**）；`:90` 把截断后的 stderr 拼进抛出的错误；`:79` `truncated: stdout.lossy` **只看 stdout**，`:77` 丢弃 stderr 的 `lossy` ⇒ **该路径完全没有截断标记** |
| `packages/shell/bash-local/src/index.ts:190-191`、`packages/shell/pwsh-local/src/index.ts:237-238` | stdout 走**可逐调用调高**的 `stdoutMaxBytes`；stderr 硬绑 `maxOutputBytes`（默认 64_000，`bash-local:109`/`pwsh-local:135`）⇒ **调用方能调高 stdout，却调不高 stderr** |

**这三处是 dsh 的**反面教材**，不是借鉴对象**：它们正好演示了「保尾却丢掉头部原因」「截断无标记」「错误通道不可调」。本项目改造时应避免重蹈。

#### (4) ⚠️ 「标记占预算」导致失败文案被砍成标记碎片

`packages/workflow/tool-ralph/src/index.ts:349-356`

```ts
const TRUNCATION_NOTICE = '\n… [truncated]'

/** Bound complete parent-facing text, including its envelope and truncation marker. */
function boundResult(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text
  if (maxChars <= TRUNCATION_NOTICE.length) return TRUNCATION_NOTICE.slice(0, maxChars)
  return `${text.slice(0, maxChars - TRUNCATION_NOTICE.length)}${TRUNCATION_NOTICE}`
}
```

`:384-389` `renderRoundFailure()` 把**子代理失败文本**送进同一个 `boundResult` ⇒ 极小 cap 下，**失败报告被砍成它自己 `… [truncated]` 标记的碎片**（连标记都不完整）。

同类「标记占预算」还有 4 处：`jobs/tool-jobs/src/index.ts:164`、`terminal/tool-terminal/src/render.ts:64,96`、`web/tool-web/src/fetch.ts:335`。

**对照 dsh 的正确做法**：`spill-policy/src/index.ts:166-168` 是**先给标记预留字节、再算预览预算**（`const reserve = ...; const previewBudget = Math.max(0, cap - reserve)`），并在 `:178-181` 宁可**放弃 spill 也不产出超限替换体**：

```ts
    if (Buffer.byteLength(replacedText, 'utf8') > cap) {
      ctx.logger.warn(`spill-policy: spill notice for ${toolName} exceeds maxInlineBytes; keeping the inline content`)
      return undefined
    }
```

⇒ **正确顺序**：先预留标记 → 再分配正文 → 预算不足时**保留原文**而非产出残缺标记。

### 3.10 结论

> dsh 的差异**不在「错误 vs 输出」，而在两条正交的维度**：
> **(1) `PostToolDecision.kind`**——`block`（后置纠正反馈）完全不碰；`accept`+`isError`（执行失败）与 `deny`（前置闸机拒收）都会被 spill 约束。
> **(2) 截断 vs 外置**——无论走哪条 accept 路径，超限时永远不单纯丢弃，而是外置全文 + 头尾预览 + 定位符 + 省略量。
>
> **不存在任何路径做「固定 N 字硬截断」**——这才是与本项目 `[:120]` 的真正分歧点。
> **未找到**「错误信息不截断」或「错误信息高上限」的按 `isError` 分流实现（见 §7.1）。

**推测（非证据）**：dsh 不分流 `isError` 的原因可能是错误文本既走 `Error: ${message}` 短信封，又在 `post-execute` 阶段与普通结果同构（都是 `content: ContentBlock[]`），分流会增加一个需要维护的分支而无收益。

---

## ④ 保尾 / 保关键句实现

### 4.1 `TextRetainer`：三种策略的统一实现

`packages/util/output-retention/src/index.ts:93-110`（策略类型）

```ts
/** Text retention strategy: keep a prefix, a suffix, or both, counted in bytes. */
export type TextRetentionStrategy =
  | {
    /** Keep the first `maxBytes` bytes. */
    kind: 'head'
    maxBytes: number
  }
  | {
    /** Keep the final `maxBytes` bytes. Requires reading to the end. */
    kind: 'tail'
    maxBytes: number
  }
  | {
    /** Keep a stable prefix and suffix, omitting the middle. Requires reading to the end. */
    kind: 'headTail'
    headBytes: number
    tailBytes: number
  }
```

`packages/util/output-retention/src/index.ts:235-245`（类自述）

```ts
/**
 * Bounds a byte-oriented text stream, keeping a prefix, a suffix, or both
 * ({@link TextRetentionStrategy}). All three strategies share one prefix/suffix
 * accumulator: `head` is prefix-only, `tail` is suffix-only, `headTail` is both.
 *
 * Bytes, not characters: caps and `omittedBytes` are byte counts for process/
 * body safety. Chunks that straddle a codepoint are handled — {@link finish}
 * trims a partial codepoint at each cut so the returned text never introduces a
 * replacement char at the boundary. The retainer holds at most
 * `prefixCap + tailBytes + one chunk` in memory (old suffix chunks are dropped
 * as they slide out), so a large stream does not accumulate unbounded.
 */
```

### 4.2 头尾各半的分配

`packages/spill/spill-policy/src/index.ts:95-103`

```ts
/** Build the bounded head/tail preview for `text`, splitting `budget` bytes across the two ends. */
function preview(text: string, budget: number): { text: string; omitted: Omitted } {
  const headBytes = Math.ceil(budget / 2)
  const tailBytes = Math.floor(budget / 2)
  const retainer = new TextRetainer({ kind: 'headTail', headBytes, tailBytes })
  retainer.push(text)
  const kept = retainer.finish()
  return { text: kept.text, omitted: kept.omittedBytes }
}
```

**注意**：预算是**动态**的——先扣掉通告自身的字节成本（`:166-168`）：

```ts
    const reserve = Buffer.byteLength(formatSpillNotice({ kind: 'exact', count: totalBytes }, ref), 'utf8') + 2
    const previewBudget = Math.max(0, cap - reserve)
    const { text: previewText, omitted } = preview(text, previewBudget)
```

### 4.3 尾保策略的工程理由（dsh 明确写了）

`packages/subprocess/subprocess-local/src/output.ts:47-56`

```ts
/**
 * Collects one stream with a bounded in-memory tail. With a spill cap, on
 * first overflow a spill file is created and every chunk (including those
 * already collected) is appended there while the full stream remains within
 * the cap; without one, only the in-memory tail is ever retained (the
 * diagnostic-tail shape — a language server's stderr).
 *
 * Tail-keep rationale (pi/OpenCode): errors and final results cluster at the
 * end of command output; the spill file covers the head.
 */
```

**这句话直接对应本项目的问题域**：dsh 明确指出「错误与最终结果聚集在输出末尾」，所以命令输出保尾。

### 4.4 UTF-8 边界安全（防切坏多字节）

`packages/util/output-retention/src/index.ts:211-233`

```ts
function trimTrailingPartialUtf8(bytes: Uint8Array): Uint8Array {
  let i = bytes.length - 1
  // Continuation bytes are 0b10xxxxxx; scan back at most 3 (max sequence is 4).
  while (i >= 0 && ((bytes[i] as number) & 0xc0) === 0x80 && bytes.length - i <= 3) i--
  if (i < 0) return bytes
  const lead = bytes[i] as number
  const expected = lead < 0x80 ? 1 : lead < 0xe0 ? 2 : lead < 0xf0 ? 3 : lead < 0xf8 ? 4 : 0
  if (expected === 0) return bytes
  return bytes.length - i < expected ? bytes.subarray(0, i) : bytes
}

function trimLeadingContinuationUtf8(bytes: Uint8Array): Uint8Array {
  let i = 0
  while (i < bytes.length && ((bytes[i] as number) & 0xc0) === 0x80) i++
  return bytes.subarray(i)
}
```

**对本项目意义重大**：本项目 `[:120]` 是 Python 字符切片，对中文安全；但**若改成字节级截断必须做同样处理**，否则会把中文字符切成半个（本项目已有 `openai_compat.py` 等处的 `str(e)[:120]`，字符切片本身安全）。

### 4.5 精确省略量（不撒谎）

`packages/util/output-retention/src/index.ts:372-386`

```ts
    // Report omission against the bytes ACTUALLY returned, not the pre-trim
    // budget: a boundary trim drops partial-codepoint bytes too, so an exact
    // count derived from the budget alone would overstate the retained text (and
    // any "Omitted N bytes" notice built from it would be a lie).
    const omitted = this.total - keptPrefix.length - keptSuffix.length
    const truncated = omitted > 0

    return {
      text,
      truncated,
      omittedBytes: truncated
        ? { kind: 'exact', count: omitted }
        : { kind: 'none' },
    }
```

### 4.6 子代理失败诊断：保头 + UTF-8 安全 + 显式后缀

`packages/subagent/subagent/src/out-of-process.ts:19-42`

```ts
/** Maximum UTF-8 size of {@link SubagentResult.diagnostic}. */
const MAX_SUBAGENT_DIAGNOSTIC_BYTES = 4_096

const DIAGNOSTIC_TRUNCATION_SUFFIX = '\n[diagnostic truncated]'
const utf8Encoder = new TextEncoder()
const utf8Decoder = new TextDecoder()

function limitSubagentDiagnostic(diagnostic: string): string {
  const bytes = utf8Encoder.encode(diagnostic)
  if (bytes.byteLength <= MAX_SUBAGENT_DIAGNOSTIC_BYTES) return diagnostic

  const suffixBytes = utf8Encoder.encode(DIAGNOSTIC_TRUNCATION_SUFFIX).byteLength
  let prefixBytes = MAX_SUBAGENT_DIAGNOSTIC_BYTES - suffixBytes
  while (((bytes[prefixBytes] as number) & 0b1100_0000) === 0b1000_0000) {
    prefixBytes -= 1
  }
  return utf8Decoder.decode(bytes.subarray(0, prefixBytes))
    + DIAGNOSTIC_TRUNCATION_SUFFIX
}
```

**这是全仓最接近「错误/诊断文本」的截断点**（`4096` 字节）。注意它的三个特征：
1. **预留后缀字节**（`MAX - suffixBytes`），确保截断后仍在 4096 内；
2. **UTF-8 边界回退**（`while` 循环跳开 continuation byte）；
3. **显式后缀** `[diagnostic truncated]`。

### 4.7 「保关键句」的实现：保留尾部状态行

`packages/jobs/tool-jobs/src/index.ts:122-134`

```ts
function fitWithSuffix(
  content: string,
  suffix: string,
  maxBytes: number | undefined,
  omitted: string,
): string {
  const complete = `${content}${suffix}`
  if (maxBytes === undefined || encoder.encode(complete).byteLength <= maxBytes) return complete
  const fixed = `${content.endsWith(omitted.trimStart()) ? '' : omitted}${suffix}`
  const fixedBytes = encoder.encode(fixed).byteLength
  if (fixedBytes >= maxBytes) return retainTail(fixed, maxBytes)
  return `${retainTail(content, maxBytes - fixedBytes)}${fixed}`
}
```

**核心思想**：`suffix`（状态行 `[status: completed, exit code: 0]`）是**关键句，必须保留**；先给它预留字节，剩余的才给正文，且正文**保尾**（`:133` `retainTail`）。注释 `:137-139` 称其为 "bounded like every notice summary"。

### 4.8 没有「保关键句」的语义理解

**未找到**任何基于语义（如「保留第一句错误」「保留 stack 首帧」）的选择性保留实现。dsh 的「关键句」保留全部是**位置性的**（尾部 = 关键，故保尾）或**结构性的**（后缀是已知固定模板，故预留）。

---

## ⑤ 错误信封结构

dsh 回喂给模型的失败信息由**两层**组成：模型可见层（`content`）与结构化层（`error`）。

### 5.1 逐项核对表

| 组成项 | 是否存在 | 证据 |
|---|---|---|
| **工具名** | ⚠️ **不在 content 里**，但在 `tool/result` 事件的 `tool/call` 关联上 | `packages/core/agent-loop/src/tool-calls.ts:263-266`：`session.append('tool/call', { turn, step, callId: block.id, name: block.name, arguments: block.arguments })`。模型靠 `callId` 关联。**工具名不进错误文本**；但部分工具自己写在消息里，如 `packages/core/tools/src/index.ts:1503` 的 `` `Error: ${denialReason}` ``，而 `denialReason` 常含 `tool "${exec.name}"`（见 `:1705`） |
| **错误类型 / 分类** | ✅ 有（结构化层） | `ToolErrorInfo.name` + `.code`，`packages/core/tools/src/index.ts:472-477` |
| 是否可重试 | ❌ **未找到** | 无 `retryable` 字段。重试决策由**独立插件**承担：`packages/guard/timeout-policy/src/index.ts:25` `export const TOOL_TIMEOUT = 'TOOL_TIMEOUT'`，注释 `:35-36`：`error.code is the same TOOL_TIMEOUT this plugin owns, so a retry/sandbox plugin (and replay) can route on it.` —— **靠 code 路由，不在信封里声明**。**对照本项目**：本项目 `compose_failure_feedback(retryable=...)` 反而是**更前进**的设计，dsh 无此字段 |
| **纠正性反馈豁免** | ✅ **有**（仅后置 `block`） | `packages/spill/spill-policy/src/index.ts:187-188` 注释 `a block passes through — spill only shapes accepted plain-text results, never corrective feedback.`；判据是 `decision.kind !== 'accept'`（`:191`）。**注意：仅覆盖 post-execute 的 `block`，不覆盖 pre-execute 的 `deny`**（见 §3.2） |
| **下一步建议** | ⚠️ 部分，**由具体工具/策略自备**，非统一字段 | 例：`packages/fs/tool-fs/src/error.ts:24-32` |
| **状态未变声明** | ⚠️ **仅特定失败**，非通用 | `packages/core/tools/src/index.ts:1757-1764` 的 block 语义隐含；显式的见 `packages/core/session/src/repair.ts:104-107` |
| **错误原文（不加工）** | ✅ | `message` 原样，`packages/core/tools/src/index.ts:1885` |
| **省略量 / 截断声明** | ✅ **在大输出超限时** | `packages/util/output-retention/src/index.ts:412-421` |
| **取回路径（定位符）** | ✅ **在大输出超限时** | `packages/spill/spill-local/src/index.ts:159` |

### 5.2 证据：错误类型/分类

`packages/core/tools/src/index.ts:471-477`（已引）与 `:643-650`（已引）。二类具体错误类：

`packages/core/tools/src/index.ts:487-521`

```ts
export class ToolNotFoundError extends HarnessError {
  constructor(toolName: string, reachableFrom?: string) {
    super(
      reachableFrom === undefined
        ? `unknown tool "${toolName}"`
        : `unknown tool "${toolName}": ${reachableFrom}`,
      'UNKNOWN_TOOL',
    )
    this.name = 'ToolNotFoundError'
  }
}

export class ToolOutputError extends HarnessError {
  readonly violations: string[]
  constructor(toolName: string, violations: string[]) {
    super(`tool "${toolName}" returned invalid output: ${violations.join('; ')}`, 'INVALID_TOOL_OUTPUT')
    this.name = 'ToolOutputError'
    this.violations = violations
  }
}
```

注释 `:487-492` 说明设计意图：

```
 * Extends {@link HarnessError} (`code: 'UNKNOWN_TOOL'`) so an unknown-tool
 * failure is as routable as a tool-thrown one — retry/sandbox/replay code can
 * distinguish it from a tool body's own error.
```

**注意 `violations.join('; ')` 无长度限制。**

### 5.3 证据：错误码常量

`packages/core/tools/src/index.ts:465-469`

```ts
/** Canonical error code for cancellation after a tool body was invoked. */
export const TOOL_ABORTED = 'ABORTED'

/** Canonical error code for cancellation before a tool body was invoked. */
export const TOOL_ABORTED_BEFORE_DISPATCH = 'ABORTED_BEFORE_DISPATCH'
```

`packages/guard/timeout-policy/src/index.ts:41-48`

```ts
function toolTimeoutResult(timeoutMs: number): ToolExecutionResult {
  const message = `tool call timed out after ${timeoutMs}ms`
  return {
    content: [{ type: 'text', text: `Error: ${message}` }],
    isError: true,
    error: { message, info: { name: 'ToolTimeoutError', code: TOOL_TIMEOUT } },
  }
}
```

### 5.4 证据：下一步建议（工具自备，非统一字段）

`packages/fs/tool-fs/src/error.ts:21-33`

```ts
export function remediateFsError(error: unknown, displayPath: string): unknown {
  if (!(error instanceof FsError)) return error
  if (error.code === 'FS_NOT_OBSERVED') {
    return new FsError(
      `cannot modify "${displayPath}": file has not been read — read the file, then retry`,
      error.code,
      { cause: error },
    )
  }
  if (error.code === 'FS_STALE_VERSION') {
    return new FsError(`${error.message} — re-read the file, then retry`, error.code, { cause: error })
  }
  return error
}
```

模式：`<原因> — <动作>, then retry`。模块注释 `:1-6`：

```
 * Model-facing diagnostics for guarded-mutation failures. Providers and
 * policies retain operation-specific causes, while this package owns the
 * stable message shown to the model.
```

### 5.5 证据：状态未变声明

`packages/core/session/src/repair.ts:99-110`（崩溃恢复合成的失败结果）

```ts
      content: [{
        type: 'tool-result',
        toolCallId: callId,
        isError: true,
        content: [{
          type: 'text',
          text: started
            ? 'The tool call was interrupted after it was recorded, but no result was durably recorded. Its outcome is unknown. Decide whether to retry from the tool semantics: retry only if the operation is read-only or idempotent; if it may have side effects, first verify external state or ask the user. Do not retry blindly.'
            : 'The tool call was interrupted before the Harness recorded it as started. Retry it if it is still needed.',
        }],
      }],
```

**这是全仓信息密度最高的一条失败文案**（约 300 字符，**未被任何 120 截断**），包含：
1. 发生了什么（interrupted after recorded）
2. 状态声明（no result was durably recorded）
3. 不确定性声明（Its outcome is unknown）
4. 重试决策树（retry only if read-only or idempotent）
5. 有副作用时的替代路径（first verify external state or ask the user）
6. 禁令（Do not retry blindly）

配套结构化码 `:119-121`：

```ts
        error: started
          ? { name: 'ToolOutcomeUnknownError', code: TOOL_OUTCOME_UNKNOWN }
          : { name: 'ToolNotStartedError', code: TOOL_NOT_STARTED },
```

### 5.6 证据：省略量 + 定位符（超限时的信封扩展）

`packages/spill/spill-policy/src/notice.ts:20-22`

```ts
export function formatSpillNotice(omitted: Omitted, ref: Pick<SpillRef, 'locator' | 'retrievalHint'>): string {
  return `${OPEN}${describeOmitted(omitted, 'bytes')}${LOCATION}${ref.locator}${GUIDANCE_SEPARATOR}${ref.retrievalHint}${CLOSE}`
}
```

常量 `:5-9`：`LOCATION = ' Full formatted result stored at: '`、`GUIDANCE_SEPARATOR = '. '`、`SEPARATOR = '\n\n'`。

`packages/spill/spill-local/src/index.ts:156-160`（定位符与指引的生产）

```ts
    return {
      locator: SpillLocator(saved.path),
      bytes: saved.bytes,
      retrievalHint: 'Use read with offset/limit, or grep this path to search within it.',
    }
```

最终回喂形态（`spill-policy/src/index.ts:170`）：

```ts
    const replacedText = previewText.length > 0 ? `${previewText}\n\n${notice}` : notice
```

即：**头尾预览 + `\n\n` + `(Omitted N bytes. Full formatted result stored at: <path>. Use read with offset/limit, or grep this path to search within it.)`**

**完整错误信封示例**（据 `tests/spill-policy.spec.ts:239` 与 `notice.ts:20-22` 复原）：

```
Error: code run failed (output-limit): outer output exceeded 500 bytes
Captured output:
HEAD-xxxxxx…（前若干字节）……（后若干字节）yyyyyyTAIL-

(Omitted 612 bytes. Full formatted result stored at: /spill/run_code.txt. Use read with offset/limit, or grep this path to search within it.)
```

### 5.7 **未找到**项

- ❌ 统一的 `retryable` / `isRetryable` 布尔字段（错误信封里没有）
- ❌ 统一的「下一步建议」字段（各工具自行写在 message 里）
- ❌ 统一的「状态未变」字段（仅特定工具/恢复路径显式声明）
- ❌ 工具名的自动注入（靠 `callId` 关联，名字由工具自己写）

---

## ⑥ 可借鉴做法清单（每条带 `文件:行号`）

### 借鉴 1：删掉错误正文的字符硬顶 —— dsh 全仓不存在「固定 N 字硬截断」用于模型可见内容

`packages/core/tools/src/index.ts:1879-1887` 构造错误内容时**只有拼接，没有切片**。
超限把关的是 `packages/spill/spill-policy/src/index.ts:67` 的 `maxInlineBytes?: number`，注释 `:63-66`：

```
   * The model-facing context cap for a plain-text tool result, in UTF-8 bytes.
   * Omitted disables the policy entirely (no-op). When set, a result larger than
   * this is spilled and replaced with a preview derived from this same budget.
```

**对照本项目**：`src/video_agent/core/fc_feedback.py:447` 的 `[:120]` 应删除，改为**默认不截断**；如确需上下文保险，走「阈值以下的正文全留，阈值以上整条外置」而非「每条都砍到 120」。

### 借鉴 2：超限时用「保头+保尾」而不是「砍尾」

`packages/spill/spill-policy/src/index.ts:96-103`

```ts
function preview(text: string, budget: number): { text: string; omitted: Omitted } {
  const headBytes = Math.ceil(budget / 2)
  const tailBytes = Math.floor(budget / 2)
  const retainer = new TextRetainer({ kind: 'headTail', headBytes, tailBytes })
  retainer.push(text)
  const kept = retainer.finish()
  return { text: kept.text, omitted: kept.omittedBytes }
}
```

策略定义见 `packages/util/output-retention/src/index.ts:105-110`：`Keep a stable prefix and suffix, omitting the middle.`

**理由**（dsh 自己写的）：`packages/subprocess/subprocess-local/src/output.ts:54-55`

```
 * Tail-keep rationale (pi/OpenCode): errors and final results cluster at the
 * end of command output; the spill file covers the head.
```

对本项目尤其适用：中文错误文案的**关键结论常在后半句**（「……请核对入参后重试」），纯砍尾恰好砍掉最有行动价值的部分。

### 借鉴 3：截断必须自带「省略量 + 去向 + 取回指引」

`packages/spill/spill-policy/src/notice.ts:20-22`（格式）+ `packages/util/output-retention/src/index.ts:412-421`（省略量措辞）：

```ts
export function describeOmitted(omitted: Omitted, unit: RetentionNotice['unit']): string {
  switch (omitted.kind) {
    case 'none':
      return ''
    case 'exact':
      return `Omitted ${omitted.count} ${unit}.`
    case 'unknown':
      return `More ${unit} were omitted.`
  }
}
```

**设计要点**（`packages/util/output-retention/src/index.ts:402-407` 注释）：`unknown` 时**不编造数字**——`unknown prints NO count because the caller did not provide one.` 这是防止「假精确」。

**对照本项目**：`fc_feedback.py:447` 截断后无任何标记，模型无法知道自己看到的是残缺信息，会据此做出错误判断。

### 借鉴 4：按「去向」分流，而不是按「内容」分流 —— 模型通道不截断，存档/展示通道才截断

**两个独立证据源，互相印证：**

**(a) LLM 消息层** —— `packages/llm/llm/src/message.ts:109-125`（120 上限只作用于 `source.summary`）
`packages/subagent/subagent/src/continuation-messages.ts:143-158`（正文与摘要分离的范例）

```ts
    content: [
      { type: 'text' as const, text: summary },
      ...closingText.length === 0
        ? [{ type: 'text' as const, text: 'It left no closing message.' }]
        : [{ type: 'text' as const, text: 'Its closing message:' }, ...closingText],
    ],
    source: {
      kind: 'subagent-settled' as const,
      form: 'notice' as const,
      summary: boundContextSummary(summary),   // ← 只有这里 120
      senderSessionId: childId,
    },
```

**(b) ⭐ hooks 层 —— 同一份 stderr 的双去向，与本项目场景最贴近：**

`packages/hooks/hook-protocol/src/codec.ts:66-69`（模型可见 `reason` = 完整 stderr，**无上限**）
`packages/hooks/hook-protocol/src/events.ts:53,64-67`（持久化审计 `stderrSummary` = 500 字符）

```ts
  if (exitCode === BLOCKING_EXIT_CODE) {
    output.decision = 'block'
    if (trimmedErr.length > 0) output.reason = trimmedErr   // ← 模型可见：完整，无上限
  }
```
```ts
export const DEFAULT_STDERR_SUMMARY_MAX_CHARS = 500

export function summarizeStderr(stderr: string, maxChars: number): string | undefined {
  const t = stderr.trim()
  if (t.length === 0) return undefined
  return t.length > maxChars ? t.slice(0, maxChars) + '…' : t   // ← 仅存档摘要截断
}
```

**这是本项目最直接的修法**（比 (a) 更贴切）：`[:120]` 若确实是给前端/trace 用的**展示摘要**，就应把它从「回喂给模型的字符串」里拆出去——新增独立字段承载 120 截断版，回喂正文保留全文。当前 `fc_feedback.py:461` 把截断后的 `raw` 直接拼进回喂串：

```python
    return f"[{kind}] {raw}（既有工作台状态未被本次失败改动）。建议：{hint}"
```

**dsh 的做法本质是「按去向分流」而非「按内容分流」**：同一个数据源，**模型通道不截断、存档/展示通道才截断**。本项目当前恰好**反了**——`fc_feedback.py:447` 的 120 砍在**要回喂给模型**的正文上；反倒是 `fc_tool_runner.py:814/821/830` 三处展示层截断，与 dsh 的方向一致（只是缺省略标记）。

### 借鉴 5：UTF-8 安全的截断助手（若必须截断）

`packages/subagent/subagent/src/out-of-process.ts:31-42`：预留后缀字节 → 回退到合法 UTF-8 边界 → 追加显式后缀。

```ts
function limitSubagentDiagnostic(diagnostic: string): string {
  const bytes = utf8Encoder.encode(diagnostic)
  if (bytes.byteLength <= MAX_SUBAGENT_DIAGNOSTIC_BYTES) return diagnostic

  const suffixBytes = utf8Encoder.encode(DIAGNOSTIC_TRUNCATION_SUFFIX).byteLength
  let prefixBytes = MAX_SUBAGENT_DIAGNOSTIC_BYTES - suffixBytes
  while (((bytes[prefixBytes] as number) & 0b1100_0000) === 0b1000_0000) {
    prefixBytes -= 1
  }
  return utf8Decoder.decode(bytes.subarray(0, prefixBytes))
    + DIAGNOSTIC_TRUNCATION_SUFFIX
}
```

Python 中对应写法（本项目参考）：`text.encode('utf-8')[:limit].decode('utf-8', errors='ignore')`，或直接用字符切片（Python 3 `str` 切片天然安全）。**注意**：本项目现有 `[:120]` 是 `str` 切片，安全；但 `mcp/adapter.py:134` 用的是 `len(serialized)` 字符数——若将来改字节口径需同步处理。

### 借鉴 7（新增）：先给标记预留字节，再分配正文；预算不足宁可保留原文

`packages/spill/spill-policy/src/index.ts:166-181`

```ts
    const reserve = Buffer.byteLength(formatSpillNotice({ kind: 'exact', count: totalBytes }, ref), 'utf8') + 2
    const previewBudget = Math.max(0, cap - reserve)
    const { text: previewText, omitted } = preview(text, previewBudget)
    const notice = formatSpillNotice(omitted, ref)
    const replacedText = previewText.length > 0 ? `${previewText}\n\n${notice}` : notice
    // Invariant: the policy NEVER emits a replacement larger than the cap. When
    // the notice alone exceeds maxInlineBytes (a tiny cap or a long spill root),
    // there is no within-cap replacement, so keep the inline content — spilling
    // would break the advertised cap. ...
    if (Buffer.byteLength(replacedText, 'utf8') > cap) {
      ctx.logger.warn(`spill-policy: spill notice for ${toolName} exceeds maxInlineBytes; keeping the inline content`)
      return undefined
    }
```

注释 `:158-165` 进一步说明设计动机：

```
    // Reserve the notice's byte cost INSIDE maxInlineBytes so the replacement
    // (preview + blank line + notice) never exceeds the documented cap — a naive
    // preview that spent the whole budget then appended the notice could be
    // larger than the cap, and for a marginally-over result even larger than the
    // original. The reservation uses a notice priced at the worst-case omission
    // count (the full byte total) ...
```

**反面教材（dsh 自己的 5 处缺陷，别照搬）**：`packages/workflow/tool-ralph/src/index.ts:354`——

```ts
  if (maxChars <= TRUNCATION_NOTICE.length) return TRUNCATION_NOTICE.slice(0, maxChars)
```

把标记切片返回，**极小 cap 下连标记本身都不完整**；`:384-389` 的 `renderRoundFailure`（子代理失败文本）走同一函数 ⇒ 失败报告可被砍成标记碎片。同类另有 `jobs/tool-jobs/src/index.ts:164`、`terminal/tool-terminal/src/render.ts:64,96`、`web/tool-web/src/fetch.ts:335`。

**⇒ 规则**：预算必须 `正文预算 = cap − 标记字节`；`cap` 小于标记时**保留原文**，不得产出残缺标记。

### 借鉴 8（新增）：同一份数据的「模型通道」与「存档通道」分别定策，且模型通道优先保真

见借鉴 4(b) 的 hooks 双去向。**dsh 的系统性范式**：
- **错误文本本身不截断**：`core/tools/src/index.ts:1503`（`Error: ${denialReason}`）、`:1883`（`Error: ${message}`）、`:1931`/`:1945`（abort 文案）、`guard/timeout-policy/src/index.ts:42`、`hooks/hook-protocol/src/codec.ts:68` —— **全部按构造即无上限**。
- **需要设限的只是「存档摘要 / UI 折叠行 / 外部事件流」**：`events.ts:53`（500）、`message.ts:114`（120）、`json-stream.ts:16-19`（8 KiB/32 KiB）。

**⇒ 对本项目**：`fc_feedback.py:447` 的 120 应**只保留在展示层**（前端折叠/Trace/SSE 摘要，即 `fc_tool_runner.py:814/821/830` 那类用途），**从回喂正文中移除**。

### 借鉴 6（附加）：失败文案应含「决策树」而非单句建议

`packages/core/session/src/repair.ts:104-107` 是最佳范例：约 300 字符的失败文案，含**不确定性声明 + 条件化重试决策树 + 替代路径 + 禁令**，且**完全未被截断**。

```
'The tool call was interrupted after it was recorded, but no result was durably recorded. Its outcome is unknown. Decide whether to retry from the tool semantics: retry only if the operation is read-only or idempotent; if it may have side effects, first verify external state or ask the user. Do not retry blindly.'
```

本项目 `fc_feedback.py:461` 已有类似结构（`[kind] raw（既有工作台状态未被本次失败改动）。建议：{hint}`），方向正确；问题**只在于 `raw` 被 `[:120]` 掐断**，导致 `[kind] + 残缺原文 + 状态声明 + 建议` 里最关键的原文部分残缺。

---

## ⑦ 未找到项与搜索记录

### 7.1 未找到项

| 问题 | 结论 | 说明 |
|---|---|---|
| 错误文案的 120 字硬截断（回喂给模型） | **未找到** | dsh 无此实现。全仓仅两个 120：`message.ts:114` 的 UI 折叠行 `source.summary`，与 `translate.ts:149` 的**异常内嵌诊断片段**（`malformed SSE payload: ${payload.slice(0,120)}`）——**均非回喂给模型的错误正文** |
| 「错误信息豁免截断」的按 `isError` 规则 | **未找到** | `spill-policy/src/index.ts:191` 守卫不含 `isError`；`compaction-tool-result-pruner/src/index.ts:138-142` 亦不含（该包 `src/` grep `isError` 零命中） |
| 「错误信息高上限」的按 `isError` 规则 | **未找到** | 无按 `isError` 分支的差异化阈值。**反而发现 3 处「错误比成功截得更狠」**（见 §3.9(3)） |
| **按 `PostToolDecision.kind` 的豁免** | ✅ **找到** | `spill-policy/src/index.ts:187-191`：`block` 提前 `return decision`，完全不碰。**仅后置，不含前置 `deny`**（见 §3.2） |
| **⭐「错误文本故意不截断」的实测对照** | ✅ **找到（1 处）** | `hooks/hook-protocol/src/codec.ts:66-69`：阻塞原因 `output.reason` = **完整未截断 stderr**；500 上限只作用于审计字段 `stderrSummary`（`events.ts:53,64-67`）。**按去向分流，非按内容分流**（见 §3.9(1)、借鉴 4b） |
| 前置闸机拒收（`deny`）是否豁免 | **否** | `core/tools/src/index.ts:1496-1508` 把 `deny` 转成 `post-result` → `:1360-1361` → `:1618-1620` 进 post-execute，**会被 spill 约束** |
| 统一的 `retryable` 字段 | **未找到** | 靠 `error.info.code` 由外部插件路由（`timeout-policy/src/index.ts:35-36`） |
| 统一的「下一步建议」字段 | **未找到** | 各工具自行写进 `message` |
| 统一的「状态未变」字段 | **未找到** | 仅特定路径显式声明（`repair.ts:104-107`） |
| 语义级「保关键句」（如保留首个 stack frame） | **未找到** | 仅位置性（保尾）与结构性（预留固定后缀）保留 |
| 「保留尾部 N 行的错误」专用实现 | **未找到** | 存在通用保尾（`TextRetainer kind:'tail'`），非错误专用 |
| `python/` 侧对模型可见失败文案的截断 | **未找到** | `python/` 仅 9 个 `.py`，**仅 1 处截断**：`client.py:60` `deque(maxlen=400)`（SDK 调用方 stderr 环形缓冲，非模型可见）；另 1 处在测试（`manual_sdk_agent_smoke.py:88`） |

### 7.2 搜索过的关键词

在 `packages/`、`apps/`、`python/` 下检索（`*.ts` / `*.py` / `*.md` / `*.yaml`）：

`truncat`、`truncated`、`truncation`、`slice(`、`substring(`、`substr(`、`MAX_`、`maxBytes`、`maxChars`、`maxLength`、`maxItems`、`maxResults`、`maxEntries`、`maxOutputBytes`、`maxInlineBytes`、`cap`、`limit`、`budget`、`headBytes`、`tailBytes`、`headTail`、`ellipsis`、`…`、`omitted`、`Omitted`、`TextRetainer`、`ItemRetainer`、`output-retention`、`fitWithSuffix`、`retain`、`toolResult`、`ToolResult`、`ToolExecutionResult`、`ToolFailure`、`ToolErrorInfo`、`isError`、`Error: `、`errorMessage`、`errorInfo`、`failureMessageFromContent`、`CONTEXT_SUMMARY_MAX_CHARS`、`boundContextSummary`、`spill`、`spill-policy`、`post-execute`、`retryable`、`unchanged`、`not modified`

### 7.3 检索过的目录

```
E:\07 天问\deepseek-harness-master\
├── packages\
│   ├── core\ (agent, agent-loop, tools, session, system-prompt, scope, session)
│   ├── llm\ (llm, llm-deepseek, llm-pi-ai, token-meter, llm-retry)
│   ├── spill\ (spill, spill-local, spill-policy)         ← 核心
│   ├── util\output-retention\                            ← 核心
│   ├── subprocess\ (subprocess, subprocess-local)        ← 核心
│   ├── shell\ (shell, tool-bash, tool-pwsh, bash-local, pwsh-local, bash-sandbox)
│   ├── fs\ (fs, tool-fs, tool-fs-search, fs-sandbox, fs-observation-policy)
│   ├── compaction\ (compaction-basic, compaction-tool-result-pruner, compaction-image-offload)
│   ├── context\ (session-reference, agent-instructions, time-context, tmux-context)
│   ├── subagent\ (subagent, tool-subagent, subagent-acp, subagent-dsh-sdk, ...)
│   ├── jobs\tool-jobs\, terminal\tool-terminal\, guard\ (repeat-tool-reminder, timeout-policy)
│   ├── workflow\ (tool-workflow, tool-ralph, workflow, workflow-ptc)
│   ├── hooks\hook-protocol\, lsp\tool-lsp\, web\ (tool-web, web-fetch-http, web-search-*)
│   ├── api\ (workspace-files, session-controller, gateway, ...)
│   ├── mcp\mcp-client\, bundle\headless\, experimental\ (auto-review, ptc-runtime-python, webworker-runtime)
│   └── session-query\, preset\, documents\, ...
├── apps\           (composition.md 等)
├── python\sdk\     (Python SDK：仅 max_tokens，无文本截断)
└── docs\           (subsystems\, cookbook\, config-catalog.md, persistence-catalog.md)
```

### 7.4 方法与局限

- ✅ 所有引用均通过 `read` 工具实际读取源文件后摘录，行号经核对。
- ✅ 核心结论（§3.4 错误被 spill）有 dsh 官方测试用例作双重佐证。
- ✅ **第二版修正**：§3.0-3.3 的豁免判据经船长交叉复核后重写，并**推翻了复核意见中「闸机拒收 = `kind:'block'`」的映射**（源码取证见 §3.2：`deny` 是 pre-execute 类型且在 prepare 阶段被转成 `post-result` 进入 post-execute，会被 spill 约束）。两方结论的差异已逐条给出 `文件:行号`。
- ⚠️ **局限**：本次调研为**静态源码阅读**，未运行 dsh 测试套件验证；结论依赖源码与测试断言的一致性。§3.2 中「`deny` 结果会被 spill 约束」是**从代码路径推导**（卫兵只排除非 accept / value 替换 / 嵌套 / read 四种），**未找到针对 `deny`+超长文案的专项测试用例**——此点为推导而非直接测试证据，已在文中标注。
- ⚠️ **推测已标注**：§3.8 末尾关于「dsh 为何不按 isError 分流」的解释标注为推测。其余均为证据。
- ⚠️ 目录列举基于实际 `Get-ChildItem` / `glob` 结果；本表为**精选+分类**而非逐条穷举（见 §2.2 口径说明）。第二轮穷尽审计约 200 处约束点，与课题相关者已全数收录。

### 7.5 第二轮穷尽审计（独立复核）及其局限

**做法**：另派独立审计，扫描 `packages/*/src`、`apps/*/src`、`python/`（排除 `tests/`、`node_modules`、`dist`、生成文件 `api-catalog.ts` / `*-catalog.ts` / `guest-source.ts`），检索 `truncat`、`slice(`、`substring(`、`MAX_*`、`maxBytes/maxChars/maxLength/maxItems/maxResults/maxEntries`、`cap`、`limit`、`budget`、`headBytes/tailBytes/headTail`、`omitted`、`TextRetainer/ItemRetainer`、`fitWithSuffix`、`…` 等，并逐条读文件核对行号。

**产出**：约 200 处约束点的 `file:line | 阈值 | 策略 | 类别(a-e) | 原文摘录` 表。其中**错误路径（kind b）全部经人工逐条确认**；其余行依据「已验证的 grep + 定点阅读」。

**本报告已整合的部分**：§2.3（新增 20 条关键截断点，含假阳性排除清单）、§3.9（4 项直接改变结论的发现）、§6 借鉴 7/8、§7.1（新增 4 条「未找到」结论修订）。

**⚠️ 该审计自述的两点局限（如实转述，未粉饰）**：
1. 覆盖纯 UI/CLI/bundle 的第四路并行扫描**提前停止**，由主审计者本人补扫其范围——该范围**独立复核程度低于错误路径**。
2. **`python/` 实质是非发现（non-finding）**：它是 9 文件的 JSON-RPC SDK 客户端，**不是 agent 核心**，仅 2 处截断（1 处生产代码 `client.py:60` 的 400 行 stderr 环形缓冲，**非模型上下文**；1 处在测试文件）。⇒ 本报告不能声称「已审计 dsh 的 Python agent 实现」，因为**该实现在本次调研范围内不存在**。

**本报告作者已独立复核的项**（非仅转述）：`codec.ts:59-69`、`tool-result-pruner.spec.ts:185-224`、`search-core.ts:44-50,110-130`、`git.ts:60-92`、`tool-ralph/src/index.ts:349-390`、`compaction-tool-result-pruner/src/index.ts`（全文件）、`config.ts`（全文件）。其余新增行号已用 grep 核对存在性，未逐行通读全部 200 条。

---

## 附：对本项目的具体修改建议（供父代理决策，非本报告强制结论）

### 附.1 缺陷定位（已核实，未修改任何本项目源码）

**模型可见通道（真正的问题）——1 处：**

- `src/video_agent/core/fc_feedback.py:447`
  ```python
  raw = str(error_text or
            f"工具 {name} 未返回具体失败原因，请核对入参后重试（必要时先读当前状态确认）")[:120]
  ```
  截断结果于 `:461` 拼进回喂串：
  ```python
  return f"[{kind}] {raw}（既有工作台状态未被本次失败改动）。建议：{hint}"
  ```
  **该串经 `fc_tool_runner.py:837-847` 写入 `st.tool_results`，再由 `turn_executor.py:567-568` 的 `format_tool_result_messages(tool_results, ...)` 转成 tool 消息回喂模型。** 这是**唯一**落在模型上下文里的 `[:120]`，也是主缺陷。

**展示/遥测通道（风险确实较低）——3 处：**

| 位置 | 去向 | 是否进模型上下文 | 复核结论 |
|---|---|---|---|
| `fc_tool_runner.py:814` `"result_summary": str(result.error or "执行失败")[:120]` | SSE `SSE_TOOL_FINISHED` 事件 | **否** | UI 事件流 |
| `fc_tool_runner.py:821` `result_summary=str(result.error or "执行失败")[:120]` | `tracer.record_action(...)` | **否** | trace 落盘/时间线 |
| `fc_tool_runner.py:830` `f"花钱生成失败：{c.start_summary} —— {str(result.error or '执行失败')[:120]}。"` | `self.gate_warnings` → `loop_result.warnings` → `chat_service.py:962` 响应 `"warnings"` | **否** | 用户可见警告 |

**⇒ 回答船长追问**：三处**均不在**模型可见通道上，判「风险低于 447」**成立**。依据：
- `fc_tool_runner.py:66-67` 自述 `warnings：本批闸机拦截/豁免的用户可见文案，由 planner 并入 loop_result.warnings`
- `planner_output.py:122` `warnings=loop_result.warnings` 只进结果对象
- `agent_loop.py:557/564/574` 对 `result.warnings` 全是 `append`，**无任何 `messages.append` / history 写入**
- `chat_service.py:960-962` 只把 `result.warnings` 放进 HTTP/SSE 返回体

**但需补一句**：这三处虽不污染模型上下文，**却仍是用户读到残缺文案**（`[:120]` 砍掉的恰好是行动指引尾部，如「去 write_media_prompt 做」）。若 Q9 的目标含「用户可见错误文案不残缺」，这三处也应一并处理——只是优先级低于 447。

### 附.2 建议方向（按 dsh 做法，已按 §3 修正后口径重写）

1. **`fc_feedback.py:447` 去掉 `[:120]`**，正文全量回喂（借鉴 1）。
2. **不要照搬「闸机文案免截断」的简化结论**——dsh 实测里前置闸机拒收（`deny`）**同样受 spill 约束**，只有后置 `block` 豁免。本项目闸机拒收对应 dsh 的 `deny`（见 §3.2 路径 B），因此**正确做法不是「豁免」，而是「改掉硬截断机制」**。
3. 若需上下文保险：设**远高于 120 的**阈值（对照 dsh `maxInlineBytes` 语义，或参考 `MAX_SUBAGENT_DIAGNOSTIC_BYTES = 4096`），超限时改为**保头+保尾 + 省略量 + 全文落盘 + 定位符**（借鉴 2、3）。本项目已有 `context_prune` / `truncate_messages` 等机制，可复用为「外置 + 预览」而非「就地砍」。
4. 若 `[:120]` 原本是服务前端折叠展示的，**拆出独立字段**承载摘要，不要复用到回喂正文（借鉴 4，dsh 的 `content` vs `source.summary` 分离是直接范式）。
5. `fc_tool_runner.py:814/821/830` 三处展示层截断可保留，但建议补省略标记与总长度提示（借鉴 3），避免用户把残缺当完整。
6. 任何截断都补上省略标记（`…`）+ 省略量 + 恢复指引（借鉴 3）。
