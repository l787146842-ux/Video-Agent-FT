from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Dict, Optional, List

from src.video_agent.exceptions import AdapterError

class VideoGenerationResponse(BaseModel):
    task_id: str
    status: str  # 'pending', 'processing', 'completed', 'failed'
    video_url: Optional[str] = None
    error_msg: Optional[str] = None
    raw_response: Optional[dict] = None

class BaseVideoAdapter(ABC):
    
    @abstractmethod
    async def generate(self, image_url: str, prompt: str, **kwargs) -> VideoGenerationResponse:
        """
        提交生成任务
        """
        pass

    @abstractmethod
    async def fetch_result(self, task_id: str) -> VideoGenerationResponse:
        """
        查询任务结果
        """
        pass

class ImageGenerationResponse(BaseModel):
    task_id: str
    status: str
    image_urls: List[str] = []
    error_msg: Optional[str] = None
    raw_response: Optional[dict] = None

class BaseImageAdapter(ABC):
    
    @abstractmethod
    async def generate_image(self, prompt: str, reference_image: Optional[str] = None, **kwargs) -> ImageGenerationResponse:
        """
        提交图生图/文生图任务
        """
        pass
        
    @abstractmethod
    async def fetch_result(self, task_id: str) -> ImageGenerationResponse:
        """
        查询图片生成结果
        """
        pass


# ---------- 音频（Rule 4 外部调用必须走 Adapter；音色设计/合成/音乐/音效同属一族） ----------

class AudioDesignResponse(BaseModel):
    """音色设计结果：音色 ID + 预览音频（服务端直接返回字节，不是 URL）"""
    voice_id: str = ""
    preview_audio: bytes = b""
    sample_rate: int = 24000
    response_format: str = "wav"
    target_model: str = ""
    status: str = ""
    raw_response: Optional[dict] = None


class AudioGenerationResponse(BaseModel):
    """音频生成结果：远程 URL 或内联字节（二选一，调用方负责本地化）"""
    audio_url: str = ""
    audio_bytes: bytes = b""
    sample_rate: int = 0
    audio_format: str = ""
    duration: float = 0.0
    raw_response: Optional[dict] = None


class BaseAudioAdapter(ABC):
    """音频适配器契约：设计音色 / 语音合成 / 音乐生成 / 音效生成。"""

    @abstractmethod
    async def design_voice(
        self, *, target_model: str, voice_prompt: str, preview_text: str,
        prefix: str = "", language: str = "zh",
        sample_rate: int = 24000, response_format: str = "wav",
        speaker_id: str = "", audio_data: str = "",
    ) -> AudioDesignResponse:
        """音色来源二选一：文字描述设计，或参考音频复刻。

        ``voice_prompt`` = 自然语言描述（无需音频样本）；
        ``audio_data`` = 参考音频（公网 URL 或 data URI，走声音复刻）；
        两者至少给一个，各平台支持情况由适配器自行校验并报可读错误。

        ``speaker_id`` 仅平台需要「音色位」时使用（火山豆包语音：控制台购买后分配，
        决定剩余设计次数）；其余平台实现可忽略。
        """
        pass

    @abstractmethod
    async def synthesize(
        self, *, model: str, text: str, voice_id: str,
        language: str = "Auto", audio_format: str = "wav",
        sample_rate: int = 24000, speed: Optional[float] = None,
        volume: Optional[float] = None, pitch: Optional[int] = None,
        emotion: str = "",
    ) -> AudioGenerationResponse:
        """已设计/已复刻音色 → 语音音频"""
        pass

    @abstractmethod
    async def generate_music(
        self, *, model: str, prompt: str, lyrics: str = "",
        instrumental: bool = True, gender: str = "",
        audio_format: str = "mp3", watermark: bool = False,
    ) -> AudioGenerationResponse:
        """提示词/歌词 → 音乐（instrumental=True 时出纯音乐）"""
        pass

    @abstractmethod
    async def generate_sfx(
        self, *, model: str, text_prompt: str,
        references: Optional[List[str]] = None, audio_format: str = "wav",
        sample_rate: int = 48000, channels: int = 2, volume: int = 50,
        rate: float = 1.0, seed: int = 42, aigc_tag: bool = False,
    ) -> AudioGenerationResponse:
        """场景描述 + 可选参考音频 → 音效/环境音/多人对话"""
        pass

    async def list_voices(self, *, model: str = "") -> List[Dict[str, str]]:
        """平台账号下的音色清单（``voice_id`` / ``name`` / ``preview_url``）。

        默认不支持：只有实测接通列表接口的适配器才覆写（如 ElevenLabs
        ``GET /v1/voices``，列表自带 preview_url）；未覆写直接抛可读错误，
        不猜端点、不返回空列表假装成功。
        """
        raise AdapterError("该供应商不支持拉取音色列表")
