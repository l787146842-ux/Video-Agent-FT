"""脚手架注册表钉死测试（正向设计改造 2-1）。

钉死三件事：
1. sid 集合不漂移（新增/删除脚手架必须显式改本测试，禁止静默变动）；
2. 每条 component 符号可导入（登记即承重，防僵尸条目）；
3. 棘轮：scaffold 计数 <= 基线（只降不升）。
"""
import importlib

from src.video_agent.core import scaffold_registry as reg


_EXPECTED_SIDS = {
    "S03",
    "S05", "S06", "S07",
    "S08", "S09", "S10", "S13",  # S11/S12 随任务#36 B5 执行器退役删除
    "I01", "I02", "I03", "I04", "I05", "I06", "I07", "I08",
    # 审核整改批 8：action_executor 承重壳登记
    "I09",
}


def test_sid_set_pinned():
    assert {e.sid for e in reg.SCAFFOLDS} == _EXPECTED_SIDS


def test_all_components_importable():
    for e in reg.SCAFFOLDS:
        mod_path, _, attr = e.component.partition(":")
        obj = importlib.import_module(mod_path)
        for part in attr.split(".") if attr else []:
            assert hasattr(obj, part), f"{e.sid}: {e.component} 不可导入"
            obj = getattr(obj, part)


def test_scaffold_entries_require_deprecation_fields():
    for e in reg.scaffold_entries():
        assert e.assumption.strip(), f"{e.sid} 缺可证伪假设"
        assert e.retest_policy.strip(), f"{e.sid} 缺复测策略"
        assert e.evidence.strip(), f"{e.sid} 缺承重证据"


def test_ratchet_count_only_down():
    assert len(reg.scaffold_entries()) <= reg.SCAFFOLD_COUNT_BASELINE
