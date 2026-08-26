"""
供应商配置 Pydantic 校验模型。

在 load_api_providers() 加载 JSON 后进行结构化校验：
- 校验失败记 warning 日志但不阻断（向后兼容）
- 按 protocol 字段区分不同供应商类型的必填项（discriminated union）
"""
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator
from loguru import logger


class ProviderBase(BaseModel):
    """供应商公共字段"""
    id: str
    name: str
    base_url: str = ""
    protocol: str = "openai"
    enabled: bool = True
    primary: bool = False
    image_models: List[str] = Field(default_factory=list)
    chat_models: List[str] = Field(default_factory=list)
    video_models: List[str] = Field(default_factory=list)
    # 扩展字段（前端用）
    image_request_mode: str = "openai"
    video_request_mode: str = "classic"  # classic: ModelScope/Seedance；openai: OpenAI /video/generations
    image_edit_route: str = "general"
    image_generation_endpoint: str = ""
    image_edit_endpoint: str = ""
    model_names: Dict[str, str] = Field(default_factory=dict)
    model_protocols: Dict[str, str] = Field(default_factory=dict)
    ms_loras: List[Any] = Field(default_factory=list)
    ms_defaults_version: int = 0
    rh_apps: List[Any] = Field(default_factory=list)
    rh_workflows: List[Any] = Field(default_factory=list)
    volcengine_project_name: str = ""
    volcengine_region: str = ""
    clear_wallet_key: bool = False
    clear_volcengine_access_key_id: bool = False
    clear_volcengine_secret_access_key: bool = False


class OpenAIProvider(ProviderBase):
    """OpenAI 兼容协议供应商（包含 OpenAI / APIMart / 火山引擎 / Gemini 反代 / RunningHub 等）"""
    protocol: Literal["openai", "apimart", "volcengine", "gemini", "runninghub"] = "openai"

    @model_validator(mode="after")
    def check_base_url(self) -> "OpenAIProvider":
        if not self.base_url:
            logger.debug(
                f"[ProviderModels] OpenAI 供应商 '{self.id}' 未配置 base_url"
            )
        return self


class CliProvider(ProviderBase):
    """本机 CLI 工具协议供应商（无 base_url，通过 subprocess 通信）"""
    protocol: Literal["gemini-cli", "codex", "jimeng"]
    base_url: str = ""  # CLI 协议无需 base_url

    @model_validator(mode="after")
    def warn_if_base_url(self) -> "CliProvider":
        if self.base_url:
            logger.debug(
                f"[ProviderModels] CLI 供应商 '{self.id}' 配置了 base_url，将被忽略"
            )
        return self


# 允许的协议类型（runninghub：ComfyUI 云工作流平台，走 OpenAI 风格请求，
# 与 detect_protocol() 的检测结果保持一致）
VALID_PROTOCOLS = {"openai", "gemini-cli", "codex", "jimeng", "volcengine", "apimart", "gemini", "runninghub"}

# CLI 协议集合
_CLI_PROTOCOLS = {"gemini-cli", "codex", "jimeng"}


def _select_model_class(protocol: str) -> type:
    """根据协议类型返回对应的校验模型类"""
    if protocol in _CLI_PROTOCOLS:
        return CliProvider
    return OpenAIProvider


def validate_providers(raw_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    对 provider 列表进行 Pydantic 校验（discriminated union）。
    - 根据 protocol 字段选择 OpenAIProvider 或 CliProvider 校验
    - 校验失败的条目记 warning 但仍保留（不阻断服务）
    返回原始列表（不修改），仅记录日志。
    """
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            logger.warning(f"[ProviderModels] 第 {i} 项不是字典，跳过校验")
            continue
        protocol = item.get("protocol", "openai")
        try:
            if protocol not in VALID_PROTOCOLS:
                logger.warning(
                    f"[ProviderModels] 供应商 '{item.get('id', '?')}' 协议 '{protocol}' "
                    f"不在已知列表中（允许: {VALID_PROTOCOLS}）"
                )
                # 未知协议仍用基类校验
                ProviderBase.model_validate(item)
            else:
                model_cls = _select_model_class(protocol)
                model_cls.model_validate(item)
        except Exception as e:
            logger.warning(
                f"[ProviderModels] 供应商配置校验失败（第 {i} 项，id={item.get('id', '?')}）: {e}"
            )
    return raw_list
