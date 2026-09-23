# DSH 源码调研 Q8：agent 如何"边想边做"（增量执行）

- **调研对象**：`E:\07 天问\deepseek-harness-master`（只读，未修改任何文件）
- **调研日期**：本次会话
- **方法**：直接读源码 + 官方 README/子系统文档 + 组合配置（agent preset / cordis.patch.yml）。每条结论均带 `文件:行号` 与原文摘录。
- **阅读范围**：`packages/core/{agent,agent-loop,system-prompt,tools}`、`packages/todo/tool-todo`、`packages/plan/plan-mode`、`packages/goal/*`、`packages/subagent/*`、`packages/workflow/*`、`packages/guard/*`、`packages/context/agent-instructions`、`packages/api/session-controller`、`packages/preset/agent-presets`、`packages/bundle/base|web-app`、`docs/subsystems/*`、`.agents/notes/*`。
- **未找到 `prompts/` 目录**（`Test-Path` 返回 `False`）：dsh 没有集中的提示词文件夹，提示词以 plugin 注册的 prompt section 形式分散在各包里。

---

## ① 主循环结构

### 1.1 位置

主循环在 **`packages/core/agent-loop/src/agent.ts`** 的 `ReactLoopAgent` 类（`packages/core/agent-loop/src/agent.ts:72`）。这是 `Agent` 公共契约唯一的默认实现。

源码地图（README 自述，`packages/core/agent-loop/README.md:99-107`）：

| File | Role |
|---|---|
| `src/index.ts` | Plugin entry: `AgentLoop` service, config schema, factory registration |
| `src/agent.ts` | The concrete `ReactLoopAgent` driver: inbox, turn/step machine, cancellation |
| `src/inbox.ts` | Package-internal `ReactLoopInbox` |
| `src/tool-calls.ts` | Tool scheduling: exclusive barriers and the bounded parallel pool |
| `src/runtime-context.ts` | Per-step runtime-context snapshot handling |

### 1.2 是"一次推理→多个工具调用→再推理"的循环 —— 是，而且是**双层**循环

**外层：turn 循环**（`packages/core/agent-loop/src/agent.ts:226-239`）

```ts
  private async kick(): Promise<void> {
    try {
      while (await this.turn()) {}
```

**中层：step 循环**（`packages/core/agent-loop/src/agent.ts:287-322`，位于 `turn()` 内）

```ts
      while (true) {
        signal.throwIfAborted()
        const step = phase.step + 1
        const decision = await this.preStep(target, { turn, step })
        ...
        this.session.append('step/start', { turn, step })
        phase.step = step
        try {
          const stepEnd = await this.step(decision)
```

**step 的续跑条件**（`packages/core/agent-loop/src/agent.ts:316-321`）：

```ts
        if (turnEnds && this.inbox.nextStep.length === 0) {
          await this.dispatch.serial('agent/turn-stopping', { turn, signal })
          signal.throwIfAborted()
        }
        if (turnEnds && this.inbox.nextStep.length === 0) break
        target = 'next-step'
```

**内层：单步内 模型流 → 工具 → 再进下一 step**（`packages/core/agent-loop/src/agent.ts:485-493`）—— 这是"再推理"的判定点：

```ts
        if (finish.kind === 'max-tokens') return { kind: 'max-tokens' }

        const toolCalls = message.content.filter(block => block.type === 'tool-call')
        if (toolCalls.length === 0) return { kind: 'completed' }
        const { concluded } = await executeToolCalls(
          this.loopCtx, turn, step, toolCalls, signal,
          context => this.inbox.splice('next-step', this.inbox.nextStep.length, 0, [context]),
        )
        return concluded ? { kind: 'completed' } : null
```

**关键语义**：`toolCalls.length === 0` → 返回 `{kind:'completed'}` → 该 step 结束。若 `turnEnds` 非空且 `inbox.nextStep` 为空 → 跳出 while → turn 结束。**反之，只要有工具调用返回 `null`，循环就继续下一个 step，模型再次被请求。** 这就是"边想边做"的引擎：**每一轮模型只产出到下一步动手所需的程度，动手结果回灌日志，再请求下一次推理。**

一次模型调用 + 工具执行 = 一个 step；一次模型调用**不是**整个任务。

### 1.3 核心：每一步的请求都由**日志重新派生**（不是预先生成的静态计划）

`packages/core/agent-loop/src/agent.ts:602-618`（`buildRequest`）：

```ts
    // canonicalHeader is shallow; append logs a detached snapshot, not these local values.
    deepFreeze(header)
    const boundaryMessages = session.deriveMessages()
```

`docs/subsystems/core.md:348`：

> A `Session` is an **append-only log** of typed `SessionEvent`s — the single source of truth. The LLM message history is *derived* from the log (`deriveMessages()`), not stored separately.

即：**没有"先算完整个会话再发出去"的结构**。每一步的消息数组都是"当刻日志的函数"。工具结果先落库，下一步才能看到。

`packages/core/agent-loop/README.md:75`（What a step does）：

> Each step sends the session's derived history — with the latest non-empty `system/message` node as the effective prompt ... and its visible tool schemas; the model's tool calls run through the guarded tool pipeline and **every accepted fact is appended to the session log before the next step derives from it**.

### 1.4 是否存在"先产出完整计划再执行"模式？

**存在，但它是可选的、独立的、默认关闭的协作模式（plan mode），不是主循环的必经阶段。**

- plan mode 由 `packages/plan/plan-mode/src/index.ts` 提供，主循环**不依赖它**（`docs/subsystems/plan.md:5`：*"The package is optional, and the agent loop does not depend on it."*）。
- 其 README 明确说明是"soft guidance"（软约束）：`packages/plan/plan-mode/README.md:185`：*"**Guidance, not enforcement** — plan mode restrains through text only; deployments that need enforced restrictions configure sandbox mode and approval policy independently."*
- 激活方式：用户输入 `/plan`（`/plan off` 退出），或 Web 端切换到 plan 模式。**不是 agent 自发进入的默认流程。**
- 在 plan mode 下，模型**只能**通过 `exit_plan_mode` 提交计划并等用户批准，批准后才在**后续 step** 执行（`packages/plan/plan-mode/src/index.ts:78-82`）：

```ts
const EXIT_DESCRIPTION
  = 'Use only in plan mode. Present your plan for the user\'s review and, on approval, leave plan mode. '
  + 'Send the COMPLETE plan as markdown, starting with a # heading that names it. '
  + 'The user may approve (carry out the plan from your next step) or keep '
  + 'planning — their feedback comes back in the tool result; revise and present again.'
```

审批结果渲染文本（`packages/plan/plan-mode/src/index.ts:287`）：

```
'Plan approved — plan mode exited; carry out the plan starting with your next step.'
```

**结论**：dsh 里"先想完全部再执行"是**用户可显式开启的一种模式**（plan mode），并且它仍然按 step 推进（提交计划本身是一个 tool call + 一个 step；批准后从"next step"开始执行）。**默认形态是增量循环，不是先规划后执行。**

### 1.5 无 turn/step 预算

`packages/core/agent-loop/README.md:200`（Known Limitations）：

> **No built-in turn budget** — tool calls or steering continue the current turn; a policy that bounds runaway turns must cancel from an existing lifecycle extension point such as `agent/turn-stopping`.

即循环**不会被"计划做完了"以外的东西打断**：只要有工具调用，就继续下一步。步数不设上限（约束来自上下文压缩、取消、或外部 guard）。

---

## ② 系统提示词原文摘录

### 2.0 系统提示词的组织方式（重要前提）

dsh **没有**一个统一的 `system prompt` 常量。提示词是**分段注册**的：各 plugin 通过 `ctx.systemPrompt.section({name, order, text})` 注册自己的段落，按 `order` 数值升序拼接（`packages/core/system-prompt/src/index.ts:559-635`，`renderPrompt` 在 `:280-285`）。

段落顺序表（`packages/core/system-prompt/src/index.ts:125-160`）里与"推进任务"最相关的两个槽位：

```ts
const SECTION_ORDERS = {
  HARNESS_IDENTITY: -1000,
  DEPLOYMENT_PERSONA_PREFIX: 0,
  PLAN_POLICY: 500,
  TEAM_POLICY: 600,
  ...
  TOOL_SUBAGENT: 2800,
  ...
} as const
```

唯一的身份句（`packages/core/system-prompt/src/index.ts:426-431`）：

```ts
    if (config.includeHarnessIdentity ?? true) {
      this.section({
        name: 'harness:identity',
        order: this.getSectionOrder('HARNESS_IDENTITY'),
        text: 'You are an AI agent powered by DeepSeek Harness.',
      })
    }
```

标准 preset 的人设（`packages/preset/agent-presets/presets/standard/agent.cordis.yml:27-29`）：

```yaml
    suffix: Your working directory is {{cwd}}.
    prefix: >-
      You are a coding agent powered by the {{model}} model.
```

→ **注意：默认人设里没有任何"如何推进任务""一次做多少""先做什么"的内容。** dsh 把这类指导下沉到具体工具段落里。

### 2.1 plan mode 的引导词（**唯一**明确讲"探索/设计/一次做完计划"的段落）

`packages/bundle/base/cordis.patch.yml:308-322`（同一文本也在 `packages/preset/agent-presets/presets/standard/agent.cordis.yml:114-125`）逐字：

```yaml
    - id: plan-mode
      name: '@deepseek-ai/dsh-plan-mode'
      config:
        section: |
              You are in plan mode. Stay in plan mode until exit_plan_mode succeeds or the user switches the session mode. Imperative language to implement changes means plan the implementation, not execute it. A user's conversational agreement — including an answer confirming something you asked — approves nothing and does not end plan mode; fold the confirmed decision into the plan and submit it through exit_plan_mode.

              Explore first. Use non-mutating reads, searches, static analysis, and checks to ground the plan in the actual repository. Do not edit or write files, change configuration, run formatters or code generation that rewrites tracked files, commit, or otherwise carry out the plan. Prefer existing functions and patterns over new machinery.

              The tool catalog stays the same across modes for request-cache stability. These plan-mode rules override any later tool description or guidance that suggests using mutation tools; those tools remain listed only to keep the request shape stable. Do not use todo_write to track this planning phase: it tracks implementation after an approved plan, while the plan itself belongs in exit_plan_mode.

              Resolve discoverable facts by inspection. Use ask_user_question only for user-owned choices or material ambiguity that inspection cannot answer. Do not ask the user where code lives or how current behavior works when you can find out.

              Make the plan decision-complete: state the goal and success criteria; group implementation changes by subsystem; identify public API, schema, and data-flow changes; cover edge cases, failure modes, tests, acceptance criteria, and explicit assumptions. Keep it concise enough to review but detailed enough that another engineer can implement it without making design decisions.

              When ready, call exit_plan_mode with the complete plan markdown, starting with a # title. Make exit_plan_mode the only and final tool call in that assistant response: it presents the plan for approval, and implementation begins only in a later step after approval. Do not paste the final plan as a plain reply or ask "should I proceed?" through prose or ask_user_question. If review rejects it, incorporate the feedback and present again. If the review channel is unavailable or aborted, stay in plan mode and ask the user to switch modes manually; do not proceed with implementation.
```

**逐条解读（这是回答"先做什么后做什么"的最直接证据）**：
- `Explore first.` —— 先只读探索。
- `Do not use todo_write to track this planning phase: it tracks implementation after an approved plan` —— **todo 工具被明确限定为"计划批准后、实施阶段"的工具**，不用于规划阶段本身。
- `Make exit_plan_mode the only and final tool call in that assistant response` —— 计划提交必须是该次 assistant 响应的**唯一且最后一个**工具调用。
- `implementation begins only in a later step after approval` —— 批准后才在**后续 step**开始实施。

**重要限定**：这段文字**只在 plan mode 激活时**渲染（`packages/plan/plan-mode/src/index.ts:212-220`，text 是函数，非激活时返回 `''`）：

```ts
    ctx.systemPrompt.section({
      name: 'plan:policy',
      order: ctx.systemPrompt.getSectionOrder('PLAN_POLICY'),
      text: (context) => {
        if (context.agent === undefined) return ''
        const pending = this.pendingIntents.get(context.agent.session)
        return (pending?.active ?? this.loggedActive(context.agent.session)) ? this.section : ''
      },
    })
```

### 2.2 todo_write 工具描述（**这是"增量推进"最核心的模型可见指令**）

`packages/todo/tool-todo/src/index.ts:45-78` 逐字（注意这是拼接的）：

```ts
const DESCRIPTION_HEAD =
  'Record and update a structured task list for the current work. Send the ENTIRE '
  + 'list every call — it REPLACES the previous list (there are no partial updates, '
  + 'no per-item edits). Use it to plan multi-step work and show progress: add one '
  + 'todo per concrete step before you start. '

const DESCRIPTION_PARALLEL =
  'Mark every todo being actively worked '
  + 'on `in_progress` — several at once when work genuinely runs in parallel (e.g. '
  + 'concurrent subagents or background commands), one for sequential work; while '
  + 'work remains, at least one task should be `in_progress`. '

const DESCRIPTION_SINGLE =
  'Keep AT MOST ONE todo `in_progress` at a '
  + 'time; while work remains, exactly one active task should be `in_progress`. '

const DESCRIPTION_TAIL =
  'Mark a todo '
  + '`completed` the moment it is done (do not batch completions), and allow no '
  + '`in_progress` item only once all work is complete. Skip the list for trivial '
  + 'single-step tasks. Statuses: `pending` (not started), `in_progress` (being '
  + 'worked on now), `completed` (finished).'
```

标准 preset 采用 parallel 变体（`packages/preset/agent-presets/presets/standard/agent.cordis.yml:248-251`）：

```yaml
- id: tool-todo
  name: '@deepseek-ai/dsh-tool-todo'
  config:
    allowParallelInProgress: true
```

→ 实际渲染给模型的完整描述 = HEAD + PARALLEL + TAIL。

**关键短语（逐字）**：
- `add one todo per concrete step before you start` —— 动手前先登记这一步。
- `Mark every todo being actively worked on in_progress` —— **先标记 in_progress，再去做**。
- `while work remains, at least one task should be in_progress` —— 只要还有活，就必须有活跃项。
- `Mark a todo completed the moment it is done (do not batch completions)` —— **完成即刻勾掉，禁止攒批**。
- `allow no in_progress item only once all work is complete` —— 全部完成前不允许出现"无活跃项"。
- `Skip the list for trivial single-step tasks` —— 单步琐事可跳过。

### 2.3 参数级描述（同文件）

`packages/todo/tool-todo/src/index.ts:151-167`：

```ts
      todos: {
        type: 'array',
        required: true,
        description: 'The COMPLETE task list, replacing any previous list.',
        items: {
          type: 'object',
          additionalProperties: false,
          properties: {
            content: { type: 'string', required: true, description: 'What the task is — a short imperative line.' },
            status: {
              type: 'string',
              required: true,
              enum: [...STATUSES],
              description: 'pending (not started) | in_progress (now) | completed (done).',
            },
```

### 2.4 子代理委派：明确鼓励**并行 + 不阻塞**

`packages/subagent/tool-subagent/src/index.ts:599-605`：

```ts
      runtimeCtx.systemPrompt.section({
        name: `tool:${toolName}`,
        order: runtimeCtx.systemPrompt.getSectionOrder('TOOL_SUBAGENT'),
        text: context => mounted === undefined || runtimeCtx.tools.get(toolName, context.scope) === undefined
          ? ''
          : `Use ${toolName} in the background by default. Start independent delegations together in one assistant message and continue useful work while they run. Set \`run_in_background: false\` only when your next action depends on that subagent's result. When a background run settles, the runtime sends you a notice containing its outcome and any final assistant message.`,
      })
```

工具 schema 侧的同义表述（`packages/subagent/tool-subagent/src/index.ts:387`）：

> `' This tool runs in the background by default, immediately returns a durable subagent id, and keeps the child conversation available for later turns. When that run settles, the runtime sends the parent a notice containing its outcome and any final assistant message; \`send_message\` steers the child\'s nearest step while it is running and starts a turn while it is idle. Set \`run_in_background: false\` only when your next action depends on receiving the result.'`

→ **这是明确的"批量并行推进"表述**，与 todo 的"逐步勾选"并存：dsh 不要求"每次只做一步"，而是要求**每一步都有可见的进度状态**。

### 2.5 重复调用护栏（防原地打转）

`packages/guard/repeat-tool-reminder/src/index.ts:63-79` 逐字：

```ts
const GENTLE_REMINDER =
  'You are repeating the exact same tool call with identical arguments. '
  + 'Carefully analyze the previous result before calling again: if the task is '
  + 'not complete, try a different approach or different arguments instead of '
  + 'repeating the call.'

/** The detailed later-threshold reminder naming the tool, the run length, and the canonical arguments. */
function detailedReminder(toolName: string, count: number, canonicalArguments: string): string {
  return 'Repeated tool call detected:\n'
    + `- tool: ${toolName}\n`
    + `- consecutive_calls: ${count}\n`
    + `- arguments: ${canonicalArguments}\n`
    + 'The repeated calls are not making progress. Do not call this tool with '
    + 'these exact arguments again. Inspect the latest result and choose a '
    + 'different action, different arguments, or finish the task if enough '
    + 'evidence has been gathered.'
}
```

默认阈值 `[3, 5, 8]`（`packages/guard/repeat-tool-reminder/src/index.ts:46`）。

### 2.6 goal 工具：跨轮次推进

`packages/goal/tool-goal/src/index.ts:112-122`（`guidance()` 函数，注册为 `tool:goal` 段落）：

```ts
function guidance(blockedAfter: number): string {
  return 'Use goal tools for one long-running completion objective in the current session. '
    + 'create_goal may infer goal intent from a direct human request in any language; do not '
    + 'create a goal for routine single-turn work. Call get_goal before update_goal and copy its '
    + 'exact goal_id and revision. After session resume or fork, an active goal is disarmed: when '
    + 'a human asks to continue or resume in any wording or language, use update_goal action '
    + 'resume to rearm it. Mark complete only when the objective is actually achieved. Mark '
    + `blocked only after the same blocking condition persists for at least ${blockedAfter} `
    + 'consecutive goal rounds, and report that concrete condition in blocked_reason; difficulty, uncertainty, '
    + 'or useful remaining work is not blocked.'
}
```

每轮续跑的注入提示（`packages/goal/goal-round-driver/src/prompt.ts:12-26`）：

```ts
export function renderGoalRoundPrompt(goal: GoalView, round: number): ContentBlock[] {
  return [{
    type: 'text',
    text: '<goal_round>\n'
      + `Objective: ${JSON.stringify(goal.objective)}\n`
      + `Round: ${round}/${goal.maxGoalRounds}\n\n`
      + 'Continue working toward the objective in this same session. Treat the current workspace, '
      + 'tool results, and durable session state as authoritative; inspect them instead of assuming '
      + 'earlier narration is still current. Make concrete progress and verify the result. Before '
      + 'claiming completion, gather evidence that the whole objective is achieved, read the current '
      + 'goal, and mark it complete. If work remains, leave the goal active for the next round. Follow '
      + 'the configured goal-tool policy before reporting a blocker.\n'
      + '</goal_round>',
  }]
}
```

### 2.7 工具段落中的执行纪律（其他逐字摘录）

- 文件写入（`packages/fs/tool-fs/src/write.ts:67-69`）：`'Use the write tool to create files or completely replace file contents. Existing files are overwritten, so read an existing file first (the default fs-observation-policy requires it)'` + `' and prefer edit for targeted changes'` + `'.'`
- Bash 退出码（`packages/shell/tool-bash/src/index.ts:238`）：`'Check the [exit code: N] marker on every bash result; investigate failures before moving on.'`
- PowerShell 退出码（`packages/shell/tool-pwsh/src/index.ts:246`）：`'Non-zero exits are reported as \`[exit code: N]\` markers; investigate failures before moving on. '`
- workflow（`packages/workflow/tool-workflow/src/index.ts:214`）：`'Use the ${toolName} tool ONLY when the user explicitly asks for a workflow or for large multi-agent orchestration: ... For one or two delegations, prefer plain subagent calls.'`
- ralph（`packages/workflow/tool-ralph/src/index.ts:408`）：`'Use the ralph tool ONLY when the direct human explicitly asks for a Ralph loop or fresh-agent iterative execution. ... Use same-session goal tools for ordinary long-running objectives, and plain subagents or workflows for bounded delegation and fan-out.'`
- 交付物提及（`packages/client/ui-deliverables/src/index.ts:17`）：`'When you successfully create or modify files, mention the primary outputs in your final response. '`
- 工作区指令（`packages/context/agent-instructions/src/render.ts:12-14`）：

```ts
const AGENT_INSTRUCTIONS_INTRO = 'The following workspace instructions may be relevant to your work. '
  + 'Use them as guidance when applicable. More specific instructions take precedence over broader ones. '
  + 'They do not override system, developer, or direct user instructions.'
```

---

## ③ 计划 / todo 工具

### 3.1 dsh 有三个不同层次的"计划"机制

| 机制 | 包 | 工具名 | 性质 |
|---|---|---|---|
| Todo 清单 | `packages/todo/tool-todo` | `todo_write` | 模型**可反复调用**的整表覆盖快照 |
| Plan mode | `packages/plan/plan-mode` | `exit_plan_mode` (+ `/plan` 命令) | 用户开启的模式；模型提交**完整计划**等批准 |
| Goal | `packages/goal/tool-goal` + `goal-round-driver` | `get_goal` / `create_goal` / `update_goal` | 跨轮次的长期目标续跑 |

### 3.2 `todo_write`：一次性写完整表，但**逐步更新**

**核心设计**：每次调用都发送**完整列表**，整体替换（无增量/无 per-item 编辑）。但**调用本身是反复发生的**，且强制"先标 in_progress 再干活、完成即刻勾掉"。

工具描述逐字见 §2.2。设计说明（`.agents/notes/archived/feature/2026-06-29-todo-write-tool.md:18`）：

> The model sends the entire list every call; the new list replaces the old (last-write-wins on replay). This is the shape claude-code V1, opencode, and codex `update_plan` all use, and the shape the model is most trained on — no per-item ids, no delta protocol.

排序与勾选纪律**不是代码强制**，而是模型自律（同 note `:38`）：

> The schema enforces type/required/enum. Beyond that, `execute` rejects empty or duplicate `content` and, when `allowParallelInProgress` is `false`, more than one active task. **Ordering and keeping the list current remain model disciplines expressed in the tool description.** A rejected write returns an `isError` result so the model self-corrects.

**唯一被代码强制的 in_progress 规则**（`packages/todo/tool-todo/src/index.ts:107-109`，仅当 `allowParallelInProgress: false`）：

```ts
  if (!allowParallel && active > 1) {
    throw new Error(`invalid todos: at most one task may be in_progress (got ${active})`)
  }
```

### 3.3 `todo_write` 是"整表覆盖"而不是"逐步 delta"——但它是**每一步可重写的活文档**

`packages/todo/tool-todo/src/index.ts:1-5`（模块注释）：

```ts
/**
 * Model-facing whole-list replacement. Each call appends a `todo/write` snapshot to the calling
 * agent's session; replay is last-write-wins, and UIs render from session events. A non-agent
 * caller has no owning list and is rejected. Named exports preserve loader injection metadata.
 * @module @deepseek-ai/dsh-tool-todo
 */
```

`todo/write` 是**日志事件，不是模型消息**（`packages/todo/tool-todo/src/types.ts:30-32`）：

```ts
    /** Whole-list snapshot; latest write wins on replay. Log-only UI state; never derived history. */
    'todo/write': { todos: TodoItem[] }
```

生命周期折叠（`packages/todo/tool-todo/src/index.ts:134-145`）——**每开新 turn 清空**，`turn/end` 保留：

```ts
  ctx.sessionProjections.register<'todos', TodoItem[] | null>({
    key: 'todos',
    stateSchema: todosProjectionSchema,
    init: () => null,
    apply: (state, event) => {
      if (event.type === 'todo/write') return event.data.todos
      if (event.type === 'turn/start') return null
      return state
    },
```

### 3.4 **没有** TodoWrite 强制流程工具调用

dsh **没有**像 Claude Code 那样"必须先用 TodoWrite 建计划"的硬性门禁。搜索 `TodoWrite` 无匹配；`todo_write` 是可选挂载的 preset 行（`packages/preset/agent-presets/presets/standard/agent.cordis.yml:248`）。且 §2.1 明确：**plan mode 下禁止用 todo_write 做规划**。

### 3.5 `exit_plan_mode`：这才是"一次性写完整计划"的工具

工具描述逐字（`packages/plan/plan-mode/src/index.ts:78-82`，见 §1.4）；参数描述（`packages/plan/plan-mode/src/index.ts:277`）：

```ts
        plan: { type: 'string', required: true, description: 'The complete plan, as markdown, starting with a # heading that names it.' },
```

**强制校验**（`packages/plan/plan-mode/src/index.ts:295-297`）：

```ts
        if (!/^#\s+\S/.test(args.plan.trim())) {
          throw new Error(`${EXIT_PLAN_MODE} requires a non-empty markdown plan starting with a # heading`)
        }
```

**驳回即失败**，带用户反馈回到模型（`packages/plan/plan-mode/src/index.ts:338-343`）：

```ts
        if (item?.selected.length !== 1 || item.selected[0] !== APPROVE_LABEL || item.custom !== undefined) {
          const feedback = item?.custom ?? ''
          throw new Error(feedback === ''
            ? 'The user chose to keep planning; revise the plan and present it again.'
            : `The user chose to keep planning; their feedback: ${feedback}`)
        }
```

→ 这是一个**人机往返的规划闸门**，但**只在用户开启 plan mode 时存在**。

---

## ④ 增量产出机制（强制分步产出，而非憋到最后）

### 4.1 步骤边界是**持久事件**（turn/step 双层）

`packages/core/agent-loop/src/agent.ts:279`（turn 开场）：

```ts
      this.session.append('turn/start', { turn })
```

`packages/core/agent-loop/src/agent.ts:303` 与 `:313`（step 边界，`try/finally` 保证闭合）：

```ts
        this.session.append('step/start', { turn, step })
        phase.step = step
        try {
          const stepEnd = await this.step(decision)
          if (turnEnds === null || turnEnds.kind !== 'max-tokens') turnEnds = stepEnd
        } finally {
          this.session.append('step/end', { turn, step })
        }
```

`packages/core/agent-loop/src/agent.ts:340`（turn 闭合）：

```ts
        this.session.append('turn/end', { turn, reason: turnEnds! })
```

事件类型声明（`docs/subsystems/session.md:34-47`）：

```ts
  'turn/start': { turn: number }
  'turn/end': { turn: number; reason: TurnEndReason }
  'step/start': { turn: number; step: number }
  'step/end': { turn: number; step: number }
```

→ **每个 step 都有 start/end 落库。** 不需要等整个任务完成才知道进展到哪。

### 4.2 assistant 消息**逐 step 落库**

`packages/core/agent-loop/src/agent.ts:475-484`：

```ts
        live.settle(
          'assistant/message',
          () => this.session.append('assistant/message', {
            turn,
            step,
            message,
            ...live.usage === undefined ? {} : { usage: live.usage },
            stream: live.stream,
          }, { surfaceOp: 'append' }).seq,
        )
```

**工具调用/结果也逐条落库**（`packages/core/agent-loop/src/tool-calls.ts:263-266` 与 `:282-289`）：

```ts
function appendToolCall(session: Session, turn: number, step: number, block: ToolCallBlock): SessionSeq {
  const event = session.append('tool/call', { turn, step, callId: block.id, name: block.name, arguments: block.arguments })
  return event.seq
}
```

```ts
  session.append('tool/result', {
    turn, step,
    message,
    ...result.error?.info ? { error: result.error.info } : {},
    ...result.meta !== undefined ? { meta: result.meta } : {},
  }, { surfaceOp: 'append', sourceEventSeqs: [callSeq] })
```

### 4.3 **token 级**流式事件（进程内，供 UI 实时渲染）

`packages/core/agent-loop/src/assistant-stream.ts:48-71`：

```ts
  /** Publish the opening marker before the first delivered chunk. */
  start(): void {
    this.emit({
      type: 'start',
      attemptId: this.attemptId,
      revision: this.nextRevision(),
      turn: this.turn,
      step: this.step,
    })
  }

  /** Snapshot one chunk once, then feed durable compaction, assembly, and live publication. */
  push(chunk: StreamChunk): void {
    const timed = this.accumulator.push({ time: Date.now(), chunk })
    this.assembler.push(timed.chunk)
    this.emit({
      type: 'chunk',
      attemptId: this.attemptId,
      revision: this.nextRevision(),
      index: this.index++,
      time: timed.time,
      chunk: timed.chunk,
    })
  }
```

发射点（`packages/core/agent-loop/src/agent.ts:381-388`）：

```ts
      const live = new AssistantStreamAttempt(
        this.session.id,
        ++this.assistantAttemptCounter,
        () => ++this.assistantStreamRevision,
        turn,
        step,
        (frame) => { this.dispatch.emit('agent/assistant-stream', { frame }) },
      )
```

事件契约（`docs/subsystems/core.md:912`）：

> Process-local assistant-stream publication. Chunk frames are transient; the loop appends one final v2 `assistant/message` or `assistant/attempt` with the same stream before a committed end frame.

宿主消费（`packages/api/session-controller/src/history.ts:54-61`）：

```ts
    ctx.on('agent/assistant-stream', ({ agent, frame }) => {
      let stream = this.assistantStreams.get(agent.session.id)
      if (stream === undefined) {
        stream = new SessionAssistantStreamAccumulator()
        this.assistantStreams.set(agent.session.id, stream)
      }
      stream.accept(frame, cursorBeforeNext(agent.session.seq))
    }, { global: true })
```

### 4.4 工具结果会把**新上下文回灌下一步**（增量反馈闭环）

`packages/core/agent-loop/src/agent.ts:489-492`：

```ts
        const { concluded } = await executeToolCalls(
          this.loopCtx, turn, step, toolCalls, signal,
          context => this.inbox.splice('next-step', this.inbox.nextStep.length, 0, [context]),
        )
```

`packages/core/agent-loop/src/tool-calls.ts:157`（工具可注入额外上下文）：

```ts
      for (const context of result.additionalContexts ?? []) acceptContext(context)
```

工作区指令（`AGENTS.md`）是**事件驱动增量刷新**的典型：文件被 read/write/edit 触碰后，指令内容被重新投影并进入下一步（`packages/context/agent-instructions/src/index.ts:74`）：

```ts
const FILE_TOUCH_TOOL_NAMES = new Set(['read', 'write', 'edit'])
```

`packages/context/agent-instructions/src/index.ts:307-313`（step 结束后刷新）：

```ts
  ctx.on('session/event', (session, event) => {
    if (event.type !== 'step/end') return
    const pending = stepTouches.get(session)
    if (pending === undefined) return
    stepTouches.delete(session)
    for (const touch of pending) queueProjection(touch.agent, touch.path)
  })
```

### 4.5 step 之间可被"插话"（steering / injection）

`packages/core/agent-loop/src/agent.ts:137-147`：

```ts
  followup(input: UserMessage): void {
    this.send(input, 'next-turn', true)
  }

  steer(input: UserMessage): void {
    this.send(input, 'next-step', true)
  }

  inject(input: UserMessage): void {
    this.send(input, 'next-step', false)
  }
```

`steer` 会在**最近的 step 边界**被消费（`docs/subsystems/core.md:123-130`）：

> Submit steering for the nearest step. An idle driver starts a turn; a running driver consumes it at its next step boundary.

→ 人类可以在 agent 跑到一半时改变方向，**不需要等它把整个计划执行完**。

### 4.6 中途取消保留已产出文本

`packages/core/agent-loop/src/agent.ts:403-420`：

```ts
          if (signal.aborted) {
            const content = live.interruptedBlocks()
            if (content.length > 0) {
              live.settle('assistant/message', () => this.session.append('assistant/message', {
                turn,
                step,
                message: createAssistantMessage({
                  content,
                  source: {
                    provider: request.provider,
                    model: request.model,
                    ...live.replayState === undefined ? {} : { replayState: live.replayState },
                  },
                }),
                interrupted: true,
```

### 4.7 崩溃后的中断 turn 由恢复流程补齐

`packages/core/agent-loop/README.md:115`：

> `resume` calls `persistence.open(id, 'write')` first ..., reads the physically valid log through the handle, and appends `interruptedTurnClosers` for a log crashed mid-turn as an ordinary batch

`docs/subsystems/session.md:694-700`：

```ts
  /**
   * A crash-orphaned turn was closed after the fact: agent-loop resume appends
   * this closer for a stored log whose last turn never ended, and session-query
   * synthesizes it on cold reads. The loop never emits this marker live, and
   * the events recorded before the crash remain intact.
   */
  interrupted: { kind: 'interrupted' }
```

→ **即使进程崩溃，已产出的中间结果也不会丢**；而"憋到最后"的形态在崩溃时是全丢。

### 4.8 无强制"每步汇报"

未找到"强制模型每步必须输出文字总结"的机制。模型可以只发 tool call 不说话。**但进度可见性由 todo_write + step 事件 + 流式 chunk 共同保证**，而不是靠"要求模型汇报"。

---

## ⑤ 差异点清单（dsh 增量执行 vs「一次性想完全部再执行」）

| # | 维度 | dsh 的做法 | 「一次性想完全部再执行」 | 证据 |
|---|---|---|---|---|
| 1 | **循环形态** | 双层循环：`while (await this.turn())` + 内层 `while(true)` step 循环；有工具调用就继续下一步 | 单次推理产出全量结果，然后（可选）批量执行 | `agent.ts:226-239`、`agent.ts:287-322`、`agent.ts:485-493` |
| 2 | **上下文来源** | 每步的请求消息是 `session.deriveMessages()`，**从追加式日志实时派生** | 初始一次性构造完整上下文/计划 | `agent.ts:602-618`；`docs/subsystems/core.md:348` |
| 3 | **工具的反馈位置** | 工具结果 `session.append('tool/result', ...)` 落库后，**下一步才可见** | 先规划好全部工具调用，执行阶段无模型介入 | `tool-calls.ts:282-289`；`agent-loop/README.md:75` |
| 4 | **计划是否必经** | **不是**。plan mode 是可选、默认关闭、且明确是 soft guidance；主循环不依赖它 | 必须先产出完整计划才允许动手 | `docs/subsystems/plan.md:5`；`plan-mode/README.md:185`；`plan-mode/src/index.ts:212-220` |
| 5 | **计划粒度** | `todo_write` 要求**整表覆盖**（无 delta），但**可以每步重写**；工具描述要求 `add one todo per concrete step before you start` | 计划一次定稿，后续不再改 | `tool-todo/src/index.ts:45-49`、`:46`、`:151-167` |
| 6 | **活跃态强制** | 描述要求 `Mark every todo being actively worked on in_progress` + `while work remains, at least one task should be in_progress` | 无逐步活跃态概念 | `tool-todo/src/index.ts:51-59` |
| 7 | **完成态纪律** | `Mark a todo completed the moment it is done (do not batch completions)` —— **明文禁止攒批** | 结尾一次性汇总 | `tool-todo/src/index.ts:61-66` |
| 8 | **并行 vs 串行** | **两者都允许**：`allowParallelInProgress` 是部署选择；standard preset 用 `true`；子代理段落明确要求 `Start independent delegations together in one assistant message and continue useful work while they run` | 单一串行批处理 | `tool-todo/src/index.ts:51-59`；`standard/agent.cordis.yml:250-251`；`tool-subagent/src/index.ts:604` |
| 9 | **步数上限** | **无内置 turn/step 预算**；有工具调用就继续 | 计划条目数=执行次数，天然有界 | `agent-loop/README.md:200` |
| 10 | **进度可见性** | turn/step 边界是**持久事件**（`turn/start`/`step/start`/`step/end`/`turn/end`），逐条落库 | 执行期无中间事件 | `agent.ts:279`、`:303`、`:313`、`:340`；`session.md:34-47` |
| 11 | **token 级增量** | `agent/assistant-stream` 发 `start`/`chunk`/`end` 帧，UI 实时渲染 | 无（或仅最终一次性） | `assistant-stream.ts:48-71`；`agent.ts:387`；`core.md:912` |
| 12 | **人机中断** | `steer()` 在**最近 step 边界**注入；人类可中途改向 | 计划执行期间不可介入 | `agent.ts:141-143`；`core.md:123-130` |
| 13 | **取消语义** | 取消保留已交付文本（`interruptedBlocks()` → `interrupted: true` 落库） | 取消=全丢 | `agent.ts:403-420` |
| 14 | **崩溃恢复** | 恢复时对中断 turn 补 `interruptedTurnClosers`；已完成中间结果保留 | 崩溃=全部重来 | `agent-loop/README.md:115`；`session.md:694-700` |
| 15 | **防打转** | `repeat-tool-reminder` 检测连续同参调用，在阈值 3/5/8 注入提醒（advisory，不 veto） | 无（因为只推理一次） | `repeat-tool-reminder/src/index.ts:63-79`、`:46`、`:213-224` |
| 16 | **长任务跨轮** | goal 工具 + `goal-round-driver` 自动续轮：每轮一个 turn，注入 `<goal_round>` 提示 | 无 | `tool-goal/src/index.ts:112-122`；`goal-round-driver/src/prompt.ts:12-26` |
| 17 | **规划闸门（若启用）** | plan mode 下：`exit_plan_mode` 必须是该响应的**唯一且最后一个工具调用**，且**批准后才在后续 step 实施**；驳回=失败调用带反馈重来 | 计划即最终，无审批往返 | `cordis.patch.yml:322`；`plan-mode/src/index.ts:78-82`、`:287`、`:338-343` |
| 18 | **规划阶段与实施阶段的工具分工** | plan mode 明文：`Do not use todo_write to track this planning phase: it tracks implementation after an approved plan, while the plan itself belongs in exit_plan_mode` | 无此分工 | `cordis.patch.yml:316` |

### 5.1 一句话概括差异

dsh 把"想"和"做"**交织在同一个 step 循环里**，用**追加式日志**作为唯一事实源，用 **todo_write 的整表快照 + step 边界事件 + token 级流**保证"每做一点就有可见状态"；而"一次性想完全部再执行"把两者切成两个串行阶段，执行期没有模型参与、没有中间事实落库。

dsh 里唯一接近"先想完再做"的形态（plan mode）有三个关键限定：
1. **由用户开启**，不是 agent 自发；
2. 它自己也**沿 step 循环运行**（提交计划 = 一个 step；批准后从 next step 开始）；
3. 它是 **soft guidance**，不构成强制门禁。

---

## ⑥ 未找到项与搜索记录

### 6.1 明确的"未找到"

| 项 | 结论 | 搜索证据 |
|---|---|---|
| `prompts/` 目录 | **不存在**。`Test-Path "E:\07 天问\deepseek-harness-master\prompts"` → `False` | 根目录列表（`.agents/.claude/.github/apps/benchmarks/docs/native/packages/patches/python/scripts/snapshots/vendor/website`），无 `prompts/` |
| 统一的大段 system prompt 常量 | **未找到**。提示词全部拆成 plugin 注册的 section | 全库 `grep "systemPrompt.section("` 得到 144 处，均分散在各 plugin |
| `TodoWrite` 强制流程 / 门禁 | **未找到**。grep `TodoWrite`（大小写敏感，`*.ts`）→ 无匹配；dsh 的工具名是 `todo_write`（小写下划线） | `grep "TodoWrite\|create_plan\|update_plan\|plan_tool\|make_plan"` → No matches found |
| "必须先建计划再执行"的硬性要求（默认模式） | **未找到**。plan mode 是可选 + 软约束 | `docs/subsystems/plan.md:5`、`plan-mode/README.md:185` |
| "每次只做一步"的明文要求 | **未找到**。相反，子代理段落鼓励 `Start independent delegations together in one assistant message` | `grep "one step at a time\|one at a time"` 命中的均为无关实现注释（如 settings 串行化）；`tool-subagent/src/index.ts:604` |
| "不要预先规划全部"的明文 | **未找到**。dsh 没有反对预规划的文字；它只是不强制预规划 | `grep "Do NOT plan\|do not have a plan\|no plan mode\|plan first\|think first\|then execute"` → 仅 1 处无关命中（`plan-mode.spec.ts:1158` 测试名） |
| turn/step 数量预算（`maxTurns`/`maxSteps`） | **未找到**（dsh 明确说没有）。`maxTurns` 仅出现在 claude-code 子代理 SDK 测试里 | `grep "maxSteps\|maxTurns\|turn budget"`；`agent-loop/README.md:200` |
| "强制每步汇报中间结果"的机制 | **未找到**。进度可见性靠 todo + 事件，不靠强制汇报 | `grep "reflection\|self-review\|intermediate result\|report progress\|progress update"` → 无相关命中 |

### 6.2 搜索关键词与目录清单

**搜索过的关键词**（`grep` tool，`include: *.ts` / `*.md` / `*.yml`）：
```
agent loop / run loop / step loop / turn
PLAN_POLICY / plan-policy / planPolicy
getSectionOrder('
systemPrompt.section(
GUIDANCE|PROMPT =|_PROMPT|SYSTEM_PROMPT
todo_write / TodoWrite
before you start / one step at a time / do not plan / don't plan / first .* then / one at a time / in parallel
Step 1 / step by step / before moving on / next step
Do NOT plan / do not have a plan / no plan mode / plan first / think first / then execute
Do not pre- / not plan / avoid planning / upfront / up front / all at once / at the end of / do not batch
in one assistant message / single assistant message / one assistant response
'step/start'|'step/end'|'turn/start'|'turn/end'
agent/assistant-stream
description: 'Use this tool / description: `
reflection / self-review / intermediate result / report progress / progress update
no built-in turn budget / turn budget / maxSteps / maxTurns
incremental / step by step / one step at a time  (在 .agents/notes/*.md)
plan-mode (全库，含 yaml/json)
```

**搜索/阅读过的目录**：
```
packages/core/{agent, agent-loop, system-prompt, tools, scope, session}
packages/todo/tool-todo/{src,tests}
packages/plan/plan-mode/{src,README.md}
packages/goal/{tool-goal, goal-round-driver, goal}
packages/subagent/{tool-subagent, subagent, subagent-in-process-driver}
packages/workflow/{tool-workflow, tool-ralph}
packages/guard/{repeat-tool-reminder, timeout-policy}
packages/context/{agent-instructions, file-reference, file-reference-local}
packages/api/session-controller
packages/preset/{agent-presets/presets/*, persona}
packages/bundle/{base, web-app}
packages/fs/tool-fs, packages/shell/tool-{bash,pwsh}, packages/web/tool-web
packages/client/ui-deliverables, packages/client/ui-plan
packages/boot/app-boot
docs/subsystems/{core, plan, todo, session, system-prompt}.md
docs/persistence-catalog.md（经 README 引用）
.agents/notes/{archived,implemented}/*
.claude/skills（只读列目录）
AGENTS.md（仓库根）
```

### 6.3 区分「dsh 的做法」与「我的推测」

**属于 dsh 做法（有源码/原文佐证）**：§①–§④ 的全部内容、§⑤ 表格 1–18 行。

**属于我的推测/推断（无直接文字佐证，仅从结构推出）**：
1. **推测**：dsh 之所以不写"不要预先规划全部"，是因为其架构上**做不到**"一次性定计划后不再推理"——日志派生 + step 循环本身就排除了那种形态。这是我从 `deriveMessages()` 与 step 循环结构推出的，**源码里没有一句话这样说**。
2. **推测**：`todo_write` 的"整表覆盖"设计（而非 delta）降低了模型每步的输出成本（no ids / no delta protocol），从而**鼓励高频更新**。`.agents/notes/.../2026-06-29-todo-write-tool.md:30` 确实说了"No id — whole-list replace needs no stable identity"，但**没有**明说"为了鼓励高频更新"。这是我的推断。
3. **推测**：`allowParallelInProgress: true` 在 standard preset 中作为默认，暗示官方认为编码 agent 应并行推进。preset 里没有解释性注释，这是我的解读。
4. **推测**：step 循环"有工具调用就继续"的设计，配合"无 turn 预算"，意味着 dsh 把**终止判断权交给模型本身**（模型不再调工具 = 认为做完了）。源码没有这样表述，是我对 `toolCalls.length === 0 → completed` 的解读。

**关于 plan mode 的一个注意点**：`docs/subsystems/plan.md:29` 说 *"the exact `section` text renders as the `plan:policy` [system-prompt section](system-prompt.md) at order 50"*，但源码 `packages/core/system-prompt/src/index.ts:128` 定义 `PLAN_POLICY: 500`。**这是文档与源码的不一致**（`plan-mode/src/index.ts:214` 用的是 `getSectionOrder('PLAN_POLICY')`，即 500）。以源码为准：**order = 500**。这条我记录为"发现文档偏差"，不是推测。

---

## 附：对本项目（中文视频生成 Agent 平台）的可迁移要点

> 以下为**基于上述证据的推论**，非 dsh 源码明文，供改造时参考取舍。

1. **把"计划"做成可反复重写的活文档，而不是一次定稿的产物** —— 对应 `todo_write` 整表覆盖 + `add one todo per concrete step before you start`。
2. **让每一步的产物先落库再驱动下一步** —— 对应 `session.append('tool/result', ...)` → `deriveMessages()`。视频生成场景里，"分镜脚本""每个镜头的提示词""渲染结果"都应在每步落库，而不是最后一次性拼装。
3. **给每个执行单元加持久边界事件** —— 对应 `step/start`/`step/end`。长视频生成任务尤其需要"某镜头第 N 次重试"级别的可见性。
4. **默认不用规划闸门，但保留可开启的"先审批后执行"模式** —— 对应 plan mode 的可选 + soft guidance 设计。
5. **"完成即刻勾掉，禁止攒批"** 是低成本高收益的提示词条款（`do not batch completions`）。
6. **取消/崩溃必须保留中间产物** —— 对应 `interrupted: true` 落库与 `interruptedTurnClosers`。视频生成的单步成本高，全丢代价大。
