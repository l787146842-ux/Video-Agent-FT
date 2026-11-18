"""上传白名单与界面文案一致性（2026-11-06 修 m4a 文案/白名单矛盾）。

界面对音色参考音频写的是「mp3 / wav / m4a 等」，后端白名单必须真的接收这些容器，
否则用户按提示选的文件在上传阶段就被拒。
"""
from src.video_agent.web.routes.upload import ALLOWED_EXTS


def test_audio_formats_claimed_by_ui_are_accepted():
    for ext in (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"):
        assert ALLOWED_EXTS.get(ext) == "audio", ext


def test_non_audio_still_needs_whitelist():
    # 白名单不是“全放行”：可执行/可回显类型仍然拒绝
    for ext in (".exe", ".html", ".js"):
        assert ext not in ALLOWED_EXTS
