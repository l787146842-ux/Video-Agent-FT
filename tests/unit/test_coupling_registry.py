"""八轮 B5 遍历测试（T20）：耦合注册表每行的强制项必须真实存在。

注册表是「改 A 必须同步检查 B」的机器可读唯一来源；本测试保证注册表
自身不腐烂：符号可导入、钉死测试/关键文件存在、门禁脚本已注册进
acceptance.py、prose 降级行必须给出理由。任一强制项失效即红——
耦合行改名/删除必须先改注册表，漏改即断链被机械拦截。
"""
import importlib
from pathlib import Path

import pytest

from src.video_agent.core.coupling_registry import COUPLING_ROWS, ROW_INDEX

ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE_SRC = (ROOT / "scripts" / "acceptance.py").read_text(encoding="utf-8")

VALID_KINDS = {"file", "symbol", "testfile", "vtest", "gate", "prose"}


def test_row_ids_unique_and_indexed():
    assert len(ROW_INDEX) == len(COUPLING_ROWS)
    for row in COUPLING_ROWS:
        assert row.row_id and row.trigger and row.sync_points
        assert row.enforcement, f"{row.row_id}: 无任何强制项"


def test_enforcement_kinds_valid():
    for row in COUPLING_ROWS:
        for kind, ref in row.enforcement:
            assert kind in VALID_KINDS, f"{row.row_id}: 未知强制类型 {kind}"
            assert ref.strip(), f"{row.row_id}: 空引用"


def _resolve_symbol(spec: str):
    module_name, attr = spec.split(":", 1)
    module = importlib.import_module(module_name)
    obj = module
    for part in attr.split("."):
        assert hasattr(obj, part), f"符号缺失: {spec}（缺 {part}）"
        obj = getattr(obj, part)
    return obj


@pytest.mark.parametrize("row", COUPLING_ROWS, ids=lambda r: r.row_id)
def test_row_enforcement_alive(row):
    has_mechanical = False
    for kind, ref in row.enforcement:
        if kind == "prose":
            assert len(ref) >= 6, f"{row.row_id}: prose 降级必须给出理由"
            continue
        has_mechanical = True
        if kind == "file":
            assert (ROOT / ref).exists(), f"{row.row_id}: 文件缺失 {ref}"
        elif kind == "testfile":
            assert (ROOT / ref).exists(), f"{row.row_id}: 钉死测试缺失 {ref}"
        elif kind == "vtest":
            assert (ROOT / ref).exists(), f"{row.row_id}: 前端钉死测试缺失 {ref}"
        elif kind == "gate":
            script = ROOT / "scripts" / ref
            assert script.exists(), f"{row.row_id}: 门禁脚本缺失 {ref}"
            assert ref in ACCEPTANCE_SRC, (
                f"{row.row_id}: 门禁 {ref} 未注册进 acceptance.py（13.7 同构条款）"
            )
        elif kind == "symbol":
            _resolve_symbol(ref)
    # 纯 prose 行允许存在（确不可机械化），但全表 prose 行必须少数
    if not has_mechanical:
        assert any(k == "prose" for k, _ in row.enforcement)


def test_prose_only_rows_are_minority():
    prose_only = [
        r.row_id for r in COUPLING_ROWS
        if all(k == "prose" for k, _ in r.enforcement)
    ]
    assert len(prose_only) <= len(COUPLING_ROWS) // 3, (
        f"纯 prose 行过多（{prose_only}）——耦合表退化回散文，违反 T20 初衷"
    )


def test_registry_covers_constitution_row_count():
    # 宪法 13.7 原表 26 行全量登记；行数变化必须同批更新本断言
    # （0818 架构板正批：R19 流程门禁行随门禁链退役删除；
    # 整改计划批 7：R27 planner 拆分委托行登记）
    assert len(COUPLING_ROWS) == 26
