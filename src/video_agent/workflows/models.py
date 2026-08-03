from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class RetryPolicy(BaseModel):
    max_retries: int = Field(3)
    backoff: str = Field("exponential")
    base_delay_seconds: int = Field(5)

class WorkflowContextConfig(BaseModel):
    max_parallel_tasks: int = Field(2)
    timeout_seconds: int = Field(3600)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)

class TriggerConfig(BaseModel):
    on: str = Field(...)
    condition: Optional[str] = Field(None)

class PhaseExecution(BaseModel):
    skill: str = Field(..., description="Name of the skill to execute")
    adapter: Optional[str] = Field(None, description="Adapter override")
    params: Dict[str, Any] = Field(default_factory=dict)

class ModelConfig(BaseModel):
    """阶段级模型配置 — 指定该阶段使用的供应商和模型"""
    provider: str = Field("", description="供应商 ID")
    model: str = Field("", description="模型名")
    adapter_type: str = Field("chat", description="适配器类型: chat | image_generation")

class PhaseValidation(BaseModel):
    rules: List[Dict[str, str]] = Field(default_factory=list)

class PhaseDefinition(BaseModel):
    phase_id: str = Field(...)
    name: str = Field(...)
    type: str = Field("skill_invoke")
    depends_on: List[str] = Field(default_factory=list)
    input_mapping: Dict[str, str] = Field(default_factory=dict)
    execution: PhaseExecution = Field(...)
    output_mapping: Dict[str, str] = Field(default_factory=dict)
    validation: Optional[PhaseValidation] = Field(None)
    timeout_seconds: int = Field(3600)
    llm_config: Optional[ModelConfig] = Field(
        None,
        description=(
            "阶段级模型配置（由 build_executors 中 _resolve_chat/_resolve_image 消费）。"
            "优先级：phase_configs(API运行时) > llm_config(工作流定义) > 全局默认。"
            "为空时使用全局默认。"
        ),
    )

class WorkflowDefinition(BaseModel):
    workflow_id: str = Field(...)
    name: str = Field(...)
    version: str = Field("1.0.0")
    triggers: Optional[TriggerConfig] = Field(None)
    context: WorkflowContextConfig = Field(default_factory=WorkflowContextConfig)
    phases: List[PhaseDefinition] = Field(default_factory=list)
