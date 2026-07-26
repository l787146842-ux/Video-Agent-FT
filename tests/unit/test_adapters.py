"""wait_until_complete：failed 立即抛出而不是空转到超时"""
import time

import pytest

from src.video_agent.adapters.factory import GenerationTaskFailed, wait_until_complete
from src.video_agent.adapters.mock_adapters import MockImageAdapter, MockVideoAdapter


async def test_failed_task_raises_immediately():
    adapter = MockVideoAdapter(delay_seconds=0, pre_configured_status="failed")
    resp = await adapter.generate(image_url="", prompt="x")

    start = time.monotonic()
    with pytest.raises(GenerationTaskFailed):
        # 旧版会空转 5 秒（超时）；新版应在首次轮询就抛出
        await wait_until_complete(adapter, resp.task_id, timeout=5, poll_interval=1)
    assert time.monotonic() - start < 2


async def test_completed_task_returns_result():
    adapter = MockImageAdapter(delay_seconds=0, pre_configured_status="completed")
    resp = await adapter.generate_image(prompt="x")
    result = await wait_until_complete(adapter, resp.task_id, timeout=5, poll_interval=0)
    assert result.status == "completed"
    assert result.image_urls


async def test_unknown_task_raises_failed():
    adapter = MockImageAdapter(delay_seconds=0)
    with pytest.raises(GenerationTaskFailed):
        await wait_until_complete(adapter, "no-such-task", timeout=3, poll_interval=1)
