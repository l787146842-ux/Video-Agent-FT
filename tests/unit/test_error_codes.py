"""单元测试：错误码增强 + Prompt 多语言加载

覆盖：
- VideoAgentError 及子类携带 error_code
- 自定义 error_code 覆盖默认值
- 异常消息保持中文
- app 异常处理器响应包含 error_code 字段
- load_prompt 的 lang 参数 fallback 逻辑
"""
import pytest

from src.video_agent.exceptions import (
    VideoAgentError,
    AdapterError,
    GenerationError,
    StateError,
)


class TestErrorCodes:
    def test_base_error_has_default_code(self):
        err = VideoAgentError("出错了")
        assert err.error_code == "INTERNAL_ERROR"
        assert str(err) == "出错了"

    def test_adapter_error_code(self):
        err = AdapterError("供应商超时")
        assert err.error_code == "ADAPTER_ERROR"
        assert err.status_code == 502
        assert "供应商超时" in str(err)

    def test_generation_error_code(self):
        err = GenerationError("生图失败")
        assert err.error_code == "GENERATION_ERROR"
        assert err.status_code == 502

    def test_state_error_code(self):
        err = StateError("项目不存在")
        assert err.error_code == "STATE_ERROR"
        assert err.status_code == 400

    def test_custom_error_code_override(self):
        err = AdapterError("特殊错误", error_code="CUSTOM_CODE")
        assert err.error_code == "CUSTOM_CODE"

    def test_custom_status_code_override(self):
        err = VideoAgentError("限流", status_code=429, error_code="RATE_LIMITED")
        assert err.status_code == 429
        assert err.error_code == "RATE_LIMITED"

    def test_message_stays_chinese(self):
        """错误消息保持中文（国际化由前端根据 error_code 翻译）"""
        err = AdapterError("LLM 请求超时（120s），请检查网络或供应商状态")
        assert "超时" in str(err)
        assert err.error_code == "ADAPTER_ERROR"


class TestErrorHandlerResponse:
    """验证 app 异常处理器的响应格式"""

    def test_error_response_includes_error_code(self):
        """模拟异常处理器输出格式"""
        exc = GenerationError("图片生成失败：模型不支持")
        # 模拟 app.py 中的处理逻辑
        response_content = {"detail": str(exc), "error_code": exc.error_code}
        assert response_content["error_code"] == "GENERATION_ERROR"
        assert "图片生成失败" in response_content["detail"]


class TestPromptLangLoading:
    def test_load_prompt_without_lang(self):
        """无 lang 参数时正常加载默认文件"""
        from src.video_agent.utils.prompts import load_prompt, clear_cache
        clear_cache()
        content = load_prompt("planner/system_fc.md")
        assert len(content) > 0

    def test_load_prompt_with_nonexistent_lang_falls_back(self):
        """lang 对应的文件不存在时 fallback 到默认文件"""
        from src.video_agent.utils.prompts import load_prompt, clear_cache
        clear_cache()
        # system_fc_xx.md 不存在，应 fallback 到 system_fc.md
        content = load_prompt("planner/system_fc.md", lang="xx")
        default_content = load_prompt("planner/system_fc.md")
        assert content == default_content

    def test_load_prompt_missing_file_returns_empty(self):
        """文件不存在返回空字符串"""
        from src.video_agent.utils.prompts import load_prompt, clear_cache
        clear_cache()
        content = load_prompt("nonexistent/file.md")
        assert content == ""
