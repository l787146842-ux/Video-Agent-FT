# 任务进度清单（todo_write）文案唯一源

> `## KEY` 分节由 `load_prompt_section("shared/todo_write.md", KEY)` 读取，
> 供 `tools/todo_tools.py` 装配工具描述（本平台 prompt_literals 闸要求
> CJK prose 外置，Rule 6）。
>
> 文案逐项**照翻 dsh** `packages/todo/tool-todo/src/index.ts:45-78`
> （2026-09-23 用户裁决「完全照抄 dsh」）。两档并行策略文案成对：
> 档位翻转时必须同步改本文件，二者不得各改一半
> （dsh 注释：该开关**唯一**改变的就是这条指令）。

## DESCRIPTION_PARALLEL
规划多步工作并用它展示进度：开工前为每个具体步骤加一条清单。把正在做的步骤标 in_progress——真正能并行的可以同时标几件（例如并发的子代理或后台命令），串行的就只标一件；只要还有活没干完，就至少有一件是 in_progress。做完一件就立刻标 completed（不要攒着批量标），只有全部活都干完时才允许没有 in_progress 项。琐碎的单步任务跳过清单即可。状态取值：pending（未开始）、in_progress（正在做）、completed（已完成）。整表覆盖：每次提交完整清单。

## DESCRIPTION_SINGLE
规划多步工作并用它展示进度：开工前为每个具体步骤加一条清单。任何时刻至多只有一件 in_progress；只要还有活没干完，就恰好有一件是 in_progress。做完一件就立刻标 completed（不要攒着批量标），只有全部活都干完时才允许没有 in_progress 项。琐碎的单步任务跳过清单即可。状态取值：pending（未开始）、in_progress（正在做）、completed（已完成）。整表覆盖：每次提交完整清单。

# 尾部注入文案（清单随状态注入回上下文）

## LIST_HEADER
== 本次任务进度清单（你自己记的）==

## LIST_FOOTER
清单由 todo_write 维护（整表覆盖）；它只作步骤索引，步骤内容本身以当前阶段 Skill 章节为准。
