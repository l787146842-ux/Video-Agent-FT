# -*- coding: utf-8 -*-
with open('01 Video Agent v1 总体架构图.MD', 'r', encoding='utf-8') as f:
    content = f.read()
if '核心系统演进法则' not in content:
    rule_index = '''
## 核心系统演进法则 (System Rules Index)
为解耦和规范开发，整个架构遵循以下全系统共通的核心法则约束（详见后续各细分规范）：
- **Rule 1：State 唯一真实源法则** - 系统的所有的决策上下文必须来自于 State，严禁组件间私下传参。
- **Rule 2：Tool 标准接口法则** - 所有外部操作封装为 Tool，必须暴露统一接口，且异常就地捕获。
- **Rule 3：StateManager 唯一写入法则** - 所有 State 变更操作只能通过 StateManager，禁止直接修改 State。
- **Rule 4：外部服务适配法则** - 所有云端或本地大模型/服务调用必须包裹一层薄薄的 Adapter，严禁硬编码服务商API代码。
- **Rule 5：Prompt 内聚与版本化法则** - 本体的系统提示词或针对大语言模型的指令，必须封装并管理在具体的 Skill 配置中，以便版本控制与溯源。
'''
    content = content.replace('## 三、层级详述', rule_index + '\n## 三、层级详述')
content = content.replace('│      │-- 4. 音频 (BGM/SFX/TTS)', '│      │-- 3b. 音频 (BGM/SFX/TTS) [与图像分镜头并行]')
content = content.replace('│      │-- 3. 图像 (分镜头)', '│      │-- 3a. 图像 (分镜头)')
content = content.replace('Prompt │ 优化Skill│', 'Prompt │ 优化Skill │')
with open('01 Video Agent v1 总体架构图.MD', 'w', encoding='utf-8') as f:
    f.write(content)


with open('02 State JSON 规范.MD', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('Rule3', 'Rule 3')
c = c.replace('\"assets\": {\\n    \"assets\": [', '\"assets\": [')
c = c.replace('\"assets\": {\n    \"assets\": [', '\"assets\": [')
c = c.replace('      ]\n    }\n  },\n  \"timeline\":', '      ]\n  },\n  \"timeline\":')
c = c.replace('assets: AssetStore', 'assets: List[AssetItem]')
c = c.replace('第九节：AssetStore 与 AssetItem', '第九节：Assets 与 AssetItem')
t_old = '| metadata | Map | 扩展属性（宽/高、时长、风格指示等） |'
t_new = t_old + '\n| category | String | 音频分类（如 bgm, sfx等，仅音频有效） |\n| sample_rate | Int | 采样率（仅音频类型有效） |'
c = c.replace(t_old, t_new)
c = c.replace('asset_005', 'asset_002')
with open('02 State JSON 规范.MD', 'w', encoding='utf-8') as f:
    f.write(c)


with open('03 Workflow 定义规范.MD', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('{ \"\": \"#/phase_definitions/story\" }', '{ \"\": \"#/phase_definitions/story\" } \n      // 注意：此处的  是伪代码说明，代表从顶层 phase_definitions 字典中提取对应配置')
c = c.replace('    if not any([state == \"pending\" or state == \"running\" for state in current_phase_states]):\n        break', '    if not any([state == \"pending\" or state == \"running\" for state in current_phase_states]):\n        break\n\n    # 补充退出条件：如果所有 phase 均进入 failed，也退出流转\n    if all([state == \"failed\" for state in current_phase_states]):\n        break')
c = c.replace('timeout_seconds: 86400', 'timeout_seconds: 14400')
c = c.replace('// 24小时不回复默认通过（或超时）', '// 4小时不回复则触发超时挂起（或发通知），避免自动产生残次废片')
with open('03 Workflow 定义规范.MD', 'w', encoding='utf-8') as f:
    f.write(c)


with open('04 Skill 系统规范.MD', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('Rule2', 'Rule 2')
c = c.replace('Rule4', 'Rule 4')
c = c.replace('Rule5', 'Rule 5')
c = c.replace('[\"minimax\"]', '[\"minimax\", \"suno\", \"udio\"]')
c = c.replace('\"action\": \"invoke_skill\"', '\"action\": \"invoke_tool\"')
c = c.replace('#/schemas/Scene', 'Scene (详见 02 State JSON 规范)')
c = c.replace('#/schemas/StoryState', 'StoryState (详见 02 State JSON 规范)')
c = c.replace('Prompt │ 优化Skill│', 'Prompt │ 优化Skill │')
with open('04 Skill 系统规范.MD', 'w', encoding='utf-8') as f:
    f.write(c)


with open('05 Tool 接口规范.MD', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('Rule2', 'Rule 2')
if 'async def aexecute' in c:
    c = c.replace('async def aexecute(self, **kwargs) -> ToolResult:\n        pass', 'async def aexecute(self, **kwargs) -> ToolResult:\n        import asyncio\n        return await asyncio.to_thread(self.execute, **kwargs)')
if 'Anthropic' not in c:
    c = c.replace('## 4. Tool Manager 的职责', '## 4. Tool Manager 的职责\n\n*注意：同时支持将 JSON Schema 转换为 OpenAI (Function Calling) 和 Anthropic (tool_use) 的格式，底层实现自动抹平差异。*\n')
c = c.replace('### 四、分类与解耦原则', '### 四、并发控制与依赖图\n在 DAG 调度时，ToolManager 可提供 AsyncExecutor 来并行调用无关的 Tool；针对部分高并发限制的外部 Tool（如同账号视频生成），Tool 自身通过信号量（Semaphore）等机制，管理生命周期与限流。\n\n### 五、分类与解耦原则')
with open('05 Tool 接口规范.MD', 'w', encoding='utf-8') as f:
    f.write(c)


with open('06 Adapter 接口规范.MD', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('Rule3', 'Rule 4')
if 'BaseAudioAdapter' not in c:
    c = c.replace('class BaseImageAdapter(BaseAdapter, ABC):', 'class BaseAudioAdapter(BaseAdapter, ABC):\n    @abstractmethod\n    def generate_audio(self, prompt: str, **kwargs) -> str:\n        pass\n\nclass BaseEditAdapter(BaseAdapter, ABC):\n    @abstractmethod\n    def render_timeline(self, timeline_data: dict, **kwargs) -> str:\n        pass\n\nclass BaseImageAdapter(BaseAdapter, ABC):')
c = c.replace('self._adapters[name] = adapter_cls()', 'self._adapter_classes[name] = adapter_cls # 延迟实例化')
c = c.replace('adapter = factory.get_adapter(\"kling\")', 'adapter = factory.get_adapter_class(\"kling\")() # 实际调用时实例化')
c = c.replace('raise Exception(f\"生成失败: {status}\")', 'return {\"status\": \"failed\", \"error\": f\"生成失败: {status}\"}  # Adapter 返回值交由 Tool 封装为 ToolResult')
c = c.replace('raise TimeoutError', 'return {\"status\": \"failed\", \"error\": \"生成超时\"}')
with open('06 Adapter 接口规范.MD', 'w', encoding='utf-8') as f:
    f.write(c)


with open('07 Codex 开发任务拆分表.MD', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('* **Task 4.1：搭建 Skill Registry 与描述规范**', '* **Task 4.1：搭建 Skill Registry 与描述规范**\n* **Task 4.2：核心 Skill Prompt 开发（剧本阶段）**\n  * 编写 story_generation, character_design 等前置 Skill\n* **Task 4.3：核心表现 Skill 开发建设**\n  * 编写 storyboard_generation, ideo_prompt_conversion 等转化环节 Skill')
c = c.replace('Task 4.2：开发 Skill Executor（技能执行器）', 'Task 4.4：开发 Skill Executor（技能执行器）')
c = c.replace('Kiling Adapter', 'Kling Adapter')

mem_txt = '''
* **Task 5.3：实现 Memory 系统 (短期/长期记忆)**
  * 提供 ShortTermMemory（单次任务上下文窗口）
  * 提供 LongTermMemory（基于 RAG 检索的跨项目向量库片段等）
'''
if 'Task 5.3' not in c:
    c = c.replace('---', mem_txt + '\n---', 5) # insert before task 6

planner_txt = '''
## 阶段_新：Planner 与 API 交互层（主控大脑）
📍 **目标**：补充缺失的大脑决策规范和向外暴露的接口定义。
* **Task P.1: 补充 Planner 行为规范**
  * 定义 Planner 如何接收目标，拆解 Phase。
* **Task P.2: API 和 Security 规范机制**
  * 定义标准鉴权和暴露的 HTTP Router 列表。
'''
c = c.replace('## 阶段六：集成与交付（Integration & Interface）', planner_txt + '\n## 阶段六：集成与交付（Integration & Interface）')
c = c.replace('结合进行拆分。', '结合进行拆分。同时包含单元测试（Unit Test）与集成测试（Mock Adapter Test）的配套建设。')
with open('07 Codex 开发任务拆分表.MD', 'w', encoding='utf-8') as f:
    f.write(c)
