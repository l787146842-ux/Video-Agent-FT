"""gen_api_types 契约门禁回归（六轮 S1/N1①②；任务 #4 双产物扩展）。

钉死三件事：
1. --check 的判定只以退出码为准，且成败输出带 ASCII 前缀（OK:/FAIL:）——
   防 Windows GBK 终端乱码把「不一致」误读成「一致」（N7 勘误机制第四例）；
2. main(out_path) 注入点可用（漂移场景可在临时目录构造，不碰真实产物）；
3. 双产物成对：TS 产物与 sidecar 同目录写入，--check 同闸校验两份。
"""
import sys

import pytest

from scripts.gen_api_types import build_output, build_sidecar, main, sidecar_text


@pytest.fixture(autouse=True)
def _check_argv(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["gen_api_types.py", "--check"])


def _write_pair(tmp_path, ts_text, sidecar):
    (tmp_path / "api.generated.ts").write_text(ts_text, encoding="utf-8")
    (tmp_path / "sse.schema.json").write_text(sidecar_text(sidecar), encoding="utf-8")


def test_check_passes_on_consistent_artifact(tmp_path, capsys):
    sidecar = build_sidecar()
    _write_pair(tmp_path, build_output(sidecar), sidecar)
    assert main(out_path=str(tmp_path / "api.generated.ts")) == 0
    assert "OK:" in capsys.readouterr().out


def test_check_fails_on_drift_with_ascii_marker(tmp_path, capsys):
    sidecar = build_sidecar()
    _write_pair(tmp_path, build_output(sidecar) + "\n// manual drift\n", sidecar)
    assert main(out_path=str(tmp_path / "api.generated.ts")) == 1
    assert "FAIL:" in capsys.readouterr().out


def test_check_fails_on_sidecar_drift_with_ascii_marker(tmp_path, capsys):
    sidecar = build_sidecar()
    _write_pair(tmp_path, build_output(sidecar), sidecar)
    # sidecar 单侧漂移（TS 一致）：第二道闸必须命中
    with open(tmp_path / "sse.schema.json", "a", encoding="utf-8") as f:
        f.write("// drift\n")
    assert main(out_path=str(tmp_path / "api.generated.ts")) == 1
    assert "FAIL:" in capsys.readouterr().out


def test_check_fails_when_artifact_missing(tmp_path, capsys):
    assert main(out_path=str(tmp_path / "missing.ts")) == 1
    out = capsys.readouterr().out
    assert "FAIL:" in out and "missing" in out
