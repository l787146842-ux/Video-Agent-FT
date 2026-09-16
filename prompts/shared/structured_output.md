# structured_output 打卡指令文案（单一事实源）

> `## BRIEF` 由 `core/planner._launch_subagent` 随委派任务下发（子代理可见、
> 主对话不可见）；prompts/planner/subagent.md 逐字锁零触碰。

## BRIEF
【完工打卡】本次委派全部完成时，必须调用 structured_output 工具一次收尾，按四槽汇报：created（已创建的组/卡：类别+名称+ID）/ modified（已修改：类别+位置）/ removed（已移除：类别+位置）/ unfinished（未完成事项，无则空数组）。打卡只写真正调用过工具落账的事实；打卡成功后本轮进入终局，后续工具调用会被拒收——剩余事项写进 unfinished 槽交回委派你的主代理。
