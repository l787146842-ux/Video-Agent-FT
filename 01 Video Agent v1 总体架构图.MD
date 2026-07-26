                         用户 User
                            |
                            |
                    自然语言需求
                            |
                            ↓

              ┌─────────────────────┐
              │   Agent Interface    │
              │                     │
              │ Web / Canvas / API  │
              │ VSCode / Desktop    │
              └──────────┬──────────┘

                         ↓


====================================================
                 Agent Runtime 层
====================================================


              ┌─────────────────────┐
              │       Planner       │
              │       规划器         │
              │                     │
              │ Goal 理解           │
              │ Task 拆解           │
              │ 决策下一步           │
              └──────────┬──────────┘

                         ↓


              ┌─────────────────────┐
              │   Workflow Engine   │
              │     工作流引擎       │
              │                     │
              │ Story → Storyboard  │
              │        ├→ Image     │
              │        │   → Video ─┤
              │        └→ Audio  ───┤
              │                → Edit│
              └──────────┬──────────┘
              (Image/Audio 可并行执行)

                         ↓


====================================================
                 State 状态管理层
====================================================


              ┌─────────────────────┐
              │    State Manager    │
              │                     │
              │ Project State       │
              │ Task State          │
              │ Asset State         │
              │ Error State         │
              └──────────┬──────────┘



====================================================
                  能力管理层
====================================================


        ┌──────────────┬───────────────┬─────────────┐


        ↓              ↓               ↓

   Skill 系统      Tool Manager      Memory


 ┌──────────┐    ┌──────────┐     ┌──────────┐
 │剧本 Skill│    │工具调度   │     │用户记忆  │
 │分镜 Skill│    │权限管理   │     │项目记忆  │
 │Prompt    │    │参数管理   │     │知识库    │
 │优化 Skill│    │执行反馈   │     │RAG      │
 └──────────┘    └──────────┘     └──────────┘



                         ↓


====================================================
                Adapter 适配层
====================================================


                 Adapter Interface


                         ↓


 ┌──────────┬──────────┬──────────┬──────────┐


 ↓          ↓          ↓          ↓


Image     Video      Audio       Edit


Adapter  Adapter    Adapter    Adapter


 ↓          ↓          ↓          ↓


ComfyUI   Seedance   MiniMax    Premiere

FLUX      Kling      RVC        剪映

SDXL      Hunyuan   Foley      Blender


====================================================

                         ↓


                 外部世界 External


====================================================


---

## 全局规则索引（Global Rules）

> 以下规则在各规范文档中引用时统一使用此编号。

| 编号 | 规则名称 | 说明 | 所属规范 |
|------|---------|------|---------|
| Rule1 | 单一规划入口 | 所有用户需求必须经由 Planner 理解和拆解，不允许绕过 Planner 直接调用 Workflow | 08 Planner 规范 |
| Rule2 | Tool 统一接口 | 所有 Tool 必须继承 BaseTool 并实现 `get_input_schema()` 和 `execute()`，返回统一的 `ToolResult` | 05 Tool 接口规范 |
| Rule3 | State 单一写入 | 所有 State 只由 StateManager 修改，任何模块不得直接写入 | 02 State JSON 规范 |
| Rule4 | Prompt 集中管理 | 所有 Prompt 模板存放在 `prompts/` 目录，禁止在代码中硬编码 Prompt | 04 Skill 系统规范 |
| Rule5 | Adapter 声明式选择 | Skill 不硬编码 Adapter 选择，通过 `adapter_selection` 声明优先级和降级链 | 04 Skill 系统规范 |
| Rule6 | 外部调用必须走 Adapter | 所有外部服务（模型 API、第三方工具）的调用必须封装在 Adapter 中，Tool 层不允许直接对接外部 API | 06 Adapter 接口规范 |
| Rule7 | Skill 通过 Tool Manager 调用 | Skill 不直接调用 Adapter，必须通过 Tool Manager 间接调用 | 04 Skill 系统规范 |
