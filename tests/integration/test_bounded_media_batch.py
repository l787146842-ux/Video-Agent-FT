"""P3-13 黄金用例：12 个 key_element 批量出图（桩供应商）。

有界并行三件套（BoundedChannel）全链路验证——模型发起的执行器批内部
（ImageGenerateTool → submit_image_task 统一提交管线 → image 通道 → 供应商）：
1) 并发峰值 ≤ image 通道信号量上限（且确实并行，峰值 > 1）；
2) 429 指数退避生效（退避序列 5s/10s，第 3 次尝试成功，整批不丢）；
3) 连败熔断可触发（连败 ≥ 阈值后新提交确定性拦截，不再触碰供应商）。
主体回归（决策史见 git tag adr-archive-20260901）：并行只发生在模型发起的批内部，本用例不引入 runtime 自主生成。
"""
import asyncio
import re

import pytest

from src.video_agent.config import settings
from src.video_agent.exceptions import GenerationError
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool
from src.video_agent.web import generation as gen_mod
# 任务#11 拆分：generate_image_via_provider 的 patch 目标迁至实现模块（承重壳仅 re-export）
from src.video_agent.web import generation_dispatch

_BATCH = 12


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture(autouse=True)
def _reset_image_channel():
    """通道熔断台账测试间隔离（模块级单例，跨用例不得串账）。"""
    gen_mod.image_channel.reset()
    yield
    gen_mod.image_channel.reset()


@pytest.fixture(autouse=True)
def _isolated_task_manager(monkeypatch):
    """生成任务表测试隔离：不落盘、不携带历史累积任务（全局单例会跨
    用例/跨进程累积任务并每次全量落盘，拖慢用例且污染 data/）；
    显示名解析打桩，避免每条生成日志触发画布 HTTP 探测（既有基线
    行为，与本批断言无关）。"""
    from src.video_agent.web import task_manager as tm_mod

    tm = gen_mod.get_task_manager()
    monkeypatch.setattr(tm, "_persist", lambda: None)
    monkeypatch.setattr(tm_mod, "_resolve_provider_display_name", lambda pid: pid)
    tm._tasks.clear()
    tm._gen_logs.clear()
    yield
    tm._tasks.clear()
    tm._gen_logs.clear()


def _seed_key_elements(svc, n: int = _BATCH):
    svc.state_dict["shots"] = []
    svc.state_dict["keyElements"] = [
        {
            "id": f"ke-{i}",
            "title": f"Element_{i}",
            "drafts": [{
                "id": f"d-ke-{i}",
                "label": "概念图",
                "tag": "已确认",
                "prompt": f"概念图提示词 {i}：白发老者站在冥王星冰原上，宿命感。",
                "providerId": "prov-m",
                "aspectRatio": "16:9",
            }],
        }
        for i in range(n)
    ]


async def _wait_all(task_ids):
    return [await gen_mod.wait_image_task(tid, timeout=60) for tid in task_ids]


# ---------- ① 并发峰值 ≤ 信号量上限（12 目标批内并行，峰值有界） ----------


async def test_batch_12_peak_concurrency_within_semaphore(svc, monkeypatch):
    """12 个 key_element 批量出图：并发峰值 ≤ settings.image_gen_concurrency，
    且确实并行（峰值 > 1，对照旧串行基线）；全部成功并回写 imgUrl。"""
    _seed_key_elements(svc)
    real_sleep = asyncio.sleep
    active = 0
    peak = 0

    async def fake_gen(provider_id, model, prompt, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await real_sleep(0.03)  # 持有一小段时间，制造可观测的并发重叠窗口
        active -= 1
        return f"http://fake/{prompt[-12:-1]}.png"

    monkeypatch.setattr(generation_dispatch, "generate_image_via_provider", fake_gen)

    result = await ImageGenerateTool().aexecute(
        GenerateImageInput(target="all_keyElements", provider_id="prov-m"))
    assert result.success and result.data["submitted"] == _BATCH

    outcomes = await _wait_all(result.data["task_ids"])
    assert all(ok for ok, _ in outcomes), [err for ok, err in outcomes if not ok]

    limit = settings.image_gen_concurrency
    assert peak <= limit, f"并发峰值 {peak} 超出信号量上限 {limit}"
    assert peak > 1, "12 目标批应并行执行（峰值>1），回归串行即劣化"

    # 任务管线写回闭环：12 张概念图全部落 draft.imgUrl
    drafts = [g["drafts"][0] for g in svc.state_dict["keyElements"]]
    assert all(d.get("imgUrl") for d in drafts)


# ---------- ② 429 指数退避生效（整批撞限流也能全量跑完） ----------


async def test_batch_12_429_backoff_retries_to_success(svc, monkeypatch):
    """恢复型 429 场景：部分目标首次调用撞 429，通道按退避基数（5s）退避后
    重试成功；成功即清零连败台账，整批 12 目标全量完成、熔断不误伤。
    （整批持续 429 属于熔断用例场景，见下方 consecutive_failures 用例。）"""
    _seed_key_elements(svc)
    flaky_indexes = {0, 1, 2, 3, 4}  # 前 5 个目标首次撞 429（连败峰值 5 < 阈值 6）
    attempt_by_idx = {}
    backoff_waits = []
    real_sleep = asyncio.sleep

    async def recording_sleep(delay):
        backoff_waits.append(delay)
        await real_sleep(0)  # 让出控制权即可，不真实等待

    monkeypatch.setattr(gen_mod.asyncio, "sleep", recording_sleep)

    async def flaky_gen(provider_id, model, prompt, **kwargs):
        idx = int(re.match(r"概念图提示词 (\d+)", prompt).group(1))
        n = attempt_by_idx.get(idx, 0) + 1
        attempt_by_idx[idx] = n
        if idx in flaky_indexes and n == 1:
            raise GenerationError("HTTP 429 Too Many Requests")
        return f"http://fake/recovered-{idx}.png"

    monkeypatch.setattr(generation_dispatch, "generate_image_via_provider", flaky_gen)

    result = await ImageGenerateTool().aexecute(
        GenerateImageInput(target="all_keyElements", provider_id="prov-m"))
    assert result.success and result.data["submitted"] == _BATCH

    outcomes = await _wait_all(result.data["task_ids"])
    assert all(ok for ok, _ in outcomes), [err for ok, err in outcomes if not ok]

    # 撞 429 的目标恰好 2 次尝试（1 次 429 + 退避重试成功），其余 1 次成功
    assert len(attempt_by_idx) == _BATCH
    for idx, n in attempt_by_idx.items():
        expect = 2 if idx in flaky_indexes else 1
        assert n == expect, f"目标 {idx} 尝试 {n} 次 ≠ 预期 {expect}"
    # 429 退避生效：退避序列含 backoff_base=5s（重试前真实等待过）
    assert 5.0 in backoff_waits
    # 恢复型场景不得误触发熔断
    assert not gen_mod.image_circuit_open("prov-m")


async def test_channel_429_backoff_series_exact():
    """通道级退避序列直测：429 两次后退避序列恰为 [5.0, 10.0]，第 3 次成功。"""
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise GenerationError("HTTP 429 Too Many Requests")
        return "http://fake/ok.png"

    ch = gen_mod.BoundedChannel("image-test", 2, backoff_base=5.0)
    _patched = asyncio.sleep
    asyncio.sleep = fake_sleep
    try:
        url = await ch.run("prov-m", flaky)
    finally:
        asyncio.sleep = _patched
    assert url == "http://fake/ok.png"
    assert calls["n"] == 3
    assert sleeps == [5.0, 10.0]


# ---------- ③ 连败熔断可触发（确定性拦截，不再触碰供应商） ----------


async def test_batch_12_consecutive_failures_trip_circuit(svc, monkeypatch):
    """整批供应商持续报错：连败 ≥ 阈值触发熔断；熔断后再次提交整批被
    确定性拦截（submit 口直接报错），不再触碰供应商。"""
    _seed_key_elements(svc)
    calls = {"n": 0}

    async def dead_gen(provider_id, model, prompt, **kwargs):
        calls["n"] += 1
        raise GenerationError("upstream 500 internal error")

    monkeypatch.setattr(generation_dispatch, "generate_image_via_provider", dead_gen)

    # 第一批：全部失败，连败台账累计 ≥ 熔断阈值
    result = await ImageGenerateTool().aexecute(
        GenerateImageInput(target="all_keyElements", provider_id="prov-m"))
    assert result.success and result.data["submitted"] == _BATCH
    outcomes = await _wait_all(result.data["task_ids"])
    assert not any(ok for ok, _ in outcomes)
    assert gen_mod.image_circuit_open("prov-m")

    # 熔断后第二批：提交口确定性拦截（抛 GenerationError），供应商零新增调用
    before = calls["n"]
    with pytest.raises(GenerationError) as ei:
        await ImageGenerateTool().aexecute(
            GenerateImageInput(target="all_keyElements", provider_id="prov-m"))
    assert "熔断" in str(ei.value)
    assert calls["n"] == before, "熔断开路后不得再触碰供应商"


async def test_channel_circuit_blocks_without_touching_provider():
    """通道级熔断直测：连败 6 次开路；开路后 run 直接报错，fn 零执行。"""
    ch = gen_mod.BoundedChannel(
        "image-test", 2, circuit_threshold=6, circuit_window=60.0)

    async def boom():
        raise GenerationError("upstream 500")

    for _ in range(6):
        with pytest.raises(GenerationError):
            await ch.run("prov-m", boom)
    assert ch.circuit_open("prov-m")

    touched = {"n": 0}

    async def guard():
        touched["n"] += 1
        return "x"

    with pytest.raises(GenerationError) as ei:
        await ch.run("prov-m", guard)
    assert touched["n"] == 0
    assert "熔断" in str(ei.value)

    # 冷却窗口过后（台账人工恢复口径=reset）通道可恢复放行
    ch.reset()
    assert not ch.circuit_open("prov-m")
    assert await ch.run("prov-m", guard) == "x"


# ---------- bounded_gather 原语：同批多目标 gather + 通道 ----------


async def test_bounded_gather_keeps_order_and_isolates_failures():
    """bounded_gather：结果按索引对应，单项失败不连锁取消，峰值不破上限。"""
    active = 0
    peak = 0

    def make_fn(i):
        async def fn():
            nonlocal active, peak
            if i == 1:
                raise GenerationError("单项失败")
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return f"ok-{i}"
        return fn

    ch = gen_mod.BoundedChannel("gather-test", 2)
    results = await gen_mod.bounded_gather(
        ch, [("prov-m", make_fn(i)) for i in range(6)])
    assert results[0] == "ok-0"
    assert isinstance(results[1], GenerationError)
    assert results[5] == "ok-5"
    assert peak <= 2
