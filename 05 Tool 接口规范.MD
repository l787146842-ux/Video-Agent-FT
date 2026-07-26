# Video Agent v1 — Tool 接口规范

> Tool 是 Agent 系统中的标准执行单元。它向上对 Skill 和 Planner 提供结构化的功能调用接口，向下调用本地资源或通过 Adapter 对接外部模型 API。

---

## 一、Tool 定位与设计原则

```text
Skill / Planner ──▶ Tool Manager ──▶ Tool ──▶ Adapter / 本地系统 ──▶ 外部 API / 磁盘
```

**核心法则（Rule 2：所有Tool：必须实现统一接口）**：
1. **标准化输入输出**：必须通过预定义的 JSON Schema 定义输入（Pydantic BaseModel），必须返回 `ToolResult` 统一对象。
2. **防崩溃**：Tool 级别的崩溃和异常必须被捕获并转化为 `success: false` 的返回结果，禁止向上抛出原生 Exception。
3. **隔离性**：每个 Tool 只关心特定任务，例如"发起视频生成"、"读取本地文件"、"搜索引擎查询"。
4. **Adapter 薄封装**：对于模型服务，Tool 负责业务参数的标准化，将具体的网络/模型处理交给 Adapter。

---

## 二、BaseTool 接口定义

所有 Tool 必须继承并实现 `BaseTool` 抽象基类。

### 2.1 基础实现模版 (Python)

```python
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, Type
from abc import ABC, abstractmethod

class ToolResult(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_code: Optional[int] = None

class BaseTool(ABC):
    # 工具名称，必须全局唯一（例如：generate_video, web_search, read_file）
    name: str = ""
    # 对 Planner 和 LLM 可见的工具描述，描述越清晰越有利于自动调用
    description: str = ""

    @abstractmethod
    def get_input_schema(self) -> Type[BaseModel]:
        """
        返回当前工具所需参数的 Pydantic 模型
        必须包含字段级别的 Field(description="...") 以便转为 JSON Schema
        """
        pass

    @abstractmethod
    def execute(self, params: BaseModel) -> ToolResult:
        """
        执行具体的业务逻辑。
        入参 params 是经过 get_input_schema() 校验后的对象。
        """
        pass

    async def aexecute(self, params: BaseModel) -> ToolResult:
        """
        异步执行版本接口（系统默认优先调用）。
        若无异步实现，可默认包裹 execute()。
        """
        pass
```

---

## 三、开发一个具体的 Tool 示例

以“视频生成（调用某 Adapter）”为例：

```python
import os
from pydantic import BaseModel, Field

class GenerateVideoParams(BaseModel):
    image_path: str = Field(..., description="首帧图片在本地系统中的绝对路径")
    prompt: str = Field(..., description="视频生成的动态描述提示词")
    duration: int = Field(5, description="生成的视频时长，默认5秒，可选5/10")

class GenerateVideoTool(BaseTool):
    name = "generate_video_from_image"
    description = "根据传入的首帧图片和提示词，生成并下载一段高清视频。"

    def get_input_schema(self) -> Type[BaseModel]:
        return GenerateVideoParams

    async def aexecute(self, params: GenerateVideoParams) -> ToolResult:
        try:
            # 1. 前置校验
            if not os.path.exists(params.image_path):
                return ToolResult(success=False, error="Image file not found")
            
            # 2. 调用具体的 Adapter（Adapter 规范见后续章节）
            adapter = get_adapter("video_generation")
            response = await adapter.generate(
                img=params.image_path,
                prompt=params.prompt,
                duration=params.duration
            )
            
            # 3. 封装返回结果
            return ToolResult(
                success=True, 
                data={"task_id": response.task_id, "video_url": response.url}
            )
        except Exception as e:
            # 4. 捕获一切异常禁止上抛
            return ToolResult(success=False, error=str(e))
```

---

## 四、Tool Manager 的职责

`Tool Manager` 是所有 Tool 的集散中心。

**主要职责：**
1. **Tool 注册与发现**：服务启动时，自动扫描并注册 `tools/` 目录下的所有实现了 `BaseTool` 的类。
2. **Schema 导出**：为 LLM (Planner/Skill) 提供所有已注册工具的 OpenAI/Anthropic 标准 Function Calling JSON Schema 格式。
3. **参数强校验**：LLM 给出 JSON 后，Tool Manager 使用 `get_input_schema()` 实例化并验证参数，若引发 Pydantic 错误，则直接将错误原因转为 `ToolResult` 并反馈给 LLM 处理。
4. **生命周期拦截**：支持中间件（例如：权限校验、流量审计、日志记录）。

### 4.1 Schema 导出格式标准

Tool Manager 需确保自动导出的 JSON 完全对齐主流模型（如 GPT-4）格式：

```json
{
  "type": "function",
  "function": {
    "name": "generate_video_from_image",
    "description": "根据传入的首帧图片和提示词，生成并下载一段高清视频。",
    "parameters": {
      "type": "object",
      "properties": {
        "image_path": {
          "type": "string",
          "description": "首帧图片在本地系统中的绝对路径"
        },
        "prompt": {
          "type": "string",
          "description": "视频生成的动态描述提示词"
        },
        "duration": {
          "type": "integer",
          "description": "生成的视频时长，默认5秒，可选5/10",
          "default": 5
        }
      },
      "required": ["image_path", "prompt"]
    }
  }
}
```

---

## 五、Tool 分类

在 `Video Agent v1` 中，可以将工具作以下分类，存放在各自目录下：

1. **`tools/core/`**: 业务无关的核心能力（读取文件，网络搜索，写入 State）。
2. **`tools/video/`**: 视频处理（组装视频生成，裁剪，提帧）。
3. **`tools/audio/`**: 音频/音乐/音效生成、TTS（Text-to-Speech）。
4. **`tools/vision/`**: 图片生成、鉴黄、裁剪、重绘。

**注意**：Tool 必须与具体模型提供商接口（如 KlingAPI/RunwayAPI/SunoAPI）解耦。Tool 应该叫 `GenerateVideoTool`，而不叫 `RunwayTool`。具体的模型分支切换由内部 `Adapter` 统一调度。
