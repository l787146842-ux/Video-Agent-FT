# 子代理活动 actor 归组（流式二期）计划书

> **状态：暂缓**。用户 2026-09-15 裁决「先出计划书、自行择期实施」；指针登记见
> `docs/冻结与暂缓清单.md` #17（防翻案：未经用户提出不得启动）。
> **性质**：功能增强计划，非「第 N 轮修复计划书」（GOVERNANCE §六 所禁为修复轮计划书；
> 前瞻需求文档先例 = `docs/对画布的需求清单.md`），故落 `docs/` 且不占清偿载体。
> **一期已落地**（commit `3028e55`）：父 `on_event` 透传子循环，子级增量事件进父 SSE，
> 故事板增量亮卡。本计划书只治一期遗留的**观感归组**缺口。

---

## 一、背景与一期现状

- 一期（已做）：`planner._launch_subagent` 把父 `on_event` 透传给
  `child.handle_message(..., on_event=on_event)`；`fc_tool_runner` 经
  `_subagent_on_event` 在 run_subagent 派发处注入。子级
  `state_refresh / timeline / tool_started / tool_finished / 事件卡` 进入父 SSE。
  效果：故事板增量亮卡；左栏 `SubagentRail` 4s 轮询可见步数/状态推进。
- 一期遗留缺口：子的 tool 事件以**普通工具卡**散落在主对话 Feed，无「这是子代理在干」
  标识，父 Feed 噪声大。flova 形态为具名 specialist actor（转录 flova6.md：
  「Resource Specialist 已完成」「Agent 分析完成」独立成行、实时态）。二期即对齐该形态。

## 二、目标 / 非目标

**目标**
1. 主 Feed 将同一子代理的全部活动归组为**一张子代理 actor 卡**：
   显示 label（阶段名/任务摘要）、实时状态（执行中/已完成/已中断）、步数、子工具名单（折叠）。
2. 点击 actor 卡 → 进该子只读执行记录（复用 `SubagentRail` 记录态 / `getSubagentRecord`）。
3. 父自身 `run_subagent` 工具卡保留为「委派锚点」，actor 卡内联或紧随其后。

**非目标**
- 不改子级隐藏线程 jsonl 落盘结构；不改 `SubagentRail` 数据源与轮询口径。
- 不做 depth≥2 的嵌套 actor（试点深度上限 1）。
- 不改一期透传语义；不把左栏改 SSE 驱动（保留轮询）。

## 三、后端方案（子事件打标）

**落点 1 · `src/video_agent/core/planner.py::_launch_subagent`**
现有 `resp = await child.handle_message(base_task, child_ctx, on_event=on_event)`。
改为包一层 tagger（仅当 `on_event` 非空）：

```python
meta = {"cid": child_cid, "stage": resolved_stage,
        "label": STAGE_LABELS.get(resolved_stage, resolved_stage) if resolved_stage
                 else (task or "")[:24],
        "depth": child_depth}

async def _child_on_event(ev):
    await on_event({**ev, "subagent": meta})

resp = await child.handle_message(
    base_task, child_ctx,
    on_event=_child_on_event if on_event is not None else None)
```

- `child_cid` 为空（创建子会话降级）仍打标，`cid=""` 时前端按 label+depth 兜底归组。
- 只加字段、不改子事件原有 type/payload，一期消费方零感知。

**落点 2 · `src/video_agent/core/sse_events.py`**
给 `tool_started / tool_finished / state_refresh / timeline* / event_card` 等 TypedDict
增可选字段 `subagent: NotRequired[SubagentMeta]`；
`SubagentMeta = TypedDict(cid: str, stage: str, label: str, depth: int)`。

**落点 3 · 契约重生成**
`python scripts/gen_api_types.py` → `src/web/types/api.generated.ts`。
**禁止手改 api.generated.ts**（contract 闸会对账，见风险 B）。

## 四、前端方案（归组渲染）

1. **`src/web/lib/sse-events.ts`**：dispatch 分支内，若 `ev.subagent` 存在 →
   不走 `fx.chat.toolStarted/toolFinished` 普通卡，改调新增 `fx.subagentEvent(ev.subagent, ev)`。
2. **新增 store `src/web/stores/chat/subagent-actors.ts`**：
   `Map<cid, ActorState{label, stage, status, steps, tools[], startedAt}>`。
   - `tool_started` → status=running、tools push；
   - `tool_finished` → 更新末条工具 ok/摘要；
   - `state_refresh` → 保留一期故事板刷新 + steps 递增；
   - 父 `run_subagent` 的 `tool_finished`（或子 turn 结束事件）→ status=completed/failed
     （failed 判定复用 8888 批 D 的 turn/end reason 口径）。
3. **新增组件 `src/web/components/right-panel/SubagentActorCard.tsx`**：
   渲染 actor 卡；状态语义色复用 `--color-info / --color-success / --color-danger`
   （须过 `scripts/check_semantic_colors.py`，不新增硬编码色）。
   点击 → 切 middle-panel 子任务视图并选中该 cid（复用 `SubagentRail` 的 openThread 逻辑）。
4. **ChatFeed 槽位**：`src/web/stores/chat/stream.ts` / `turn-ledger.ts` 中，
   带 `subagent` 的条目不单独成卡，归入 actor 卡槽位（锚定父 run_subagent 卡处）。
5. **`src/web/types/index.ts`** 增 `SubagentActor` 类型；api.generated 由落点 3 同步。

## 五、测试计划

- 后端单测（`tests/unit/test_subagent_run_subagent.py` 或新文件，注释带「流式二期」）：
  ① `_launch_subagent` 透传的每个子事件均带 `subagent={cid,stage,label,depth}`；
  ② `on_event=None` 时不包装、不崩；③ cid 为空时 meta.cid=="" 仍打标。
- 前端 vitest：① 一条子 tool_started+tool_finished 只渲染**一张** actor 卡（无普通工具卡）；
  ② status running→completed 迁移；③ 点击 actor 卡触发选中该 cid 的记录视图。
- `src/web/lib/__tests__/sse-contract.test.ts` 补 `subagent` 字段透传断言。
- 批末 `python scripts/acceptance.py` 全量三阶段（GATES+SUITES+RATCHETS），只认退出码 0。
- UI 纪律：`npm run build` 后交用户目测（宪法 §3.1）；`docs/前端体验规范.md`
  子任务面板条目就地补 actor 卡映射一行，不新开章节。

## 六、实施顺序（可拆 3 个独立 commit）

1. 后端打标（planner tagger + sse_events 契约）+ gen_api_types + 后端单测。
2. 前端 store + sse-events 归组 + SubagentActorCard 组件 + vitest。
3. ChatFeed 槽位接入 + 前端体验规范映射 + build + 目测 + acceptance 全量。

## 七、风险与回退

- **A 信息丢失**：归组后父 Feed 不显子工具细节 → actor 卡折叠区保留子工具名单+摘要，
  点进记录看全文（信息不丢，只换载体）。
- **B contract 闸失败**：新字段必须经 `gen_api_types.py` 重生成，手改 api.generated.ts 必炸闸。
- **C 归组键冲突**：cid 为空（降级不落流）时以 `label+depth` 兜底键，或退化为普通卡。
- **回退**：二期纯增量（打标字段 + 前端归组）。回退 = 前端忽略 `ev.subagent` 即回到一期观感；
  后端字段保留无害，无需回滚后端。

## 八、参考

- flova：`C:\Users\ASUS\Desktop\flova参考\flova AI的对话记录和设置截图…\flova6.md`
  （具名 specialist actor 实时态）；可再联网检索 Flova 多智能体面板形态。
- dsh：`E:\07 天问\dsh-latest\packages\subagent\subagent\src\projection.ts`、
  `list-children.ts`（子活动投影 / 枚举口径）。
- 一期实现：commit `3028e55`；`planner._launch_subagent`、`fc_tool_runner._subagent_on_event`。
- 失败态口径：8888 委派失踪批·批 D（turn/end reason → failed），commit `ef92743`。
