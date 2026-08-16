"""gen_api_types 契约门禁回归（六轮 S1/N1①②）。

钉死两件事：
1. --check 的判定只以退出码为准，且成败输出带 ASCII 前缀（OK:/FAIL:）——
   防 Windows GBK 终端乱码把「不一致」误读成「一致」（N7 勘误机制第四例）；
2. main(out_path) 注入点可用（漂移场景可在临时目录构造，不碰真实产物）。
"""
import sys

import pytest

from scripts.gen_api_types import build_output, main


@pytest.fixture(autouse=True)
def _check_argv(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["gen_api_types.py", "--check"])


def test_check_passes_on_consistent_artifact(tmp_path, capsys):
    out = tmp_path / "api.generated.ts"
    out.write_text(build_output(), encoding="utf-8")
    assert main(out_path=str(out)) == 0
    assert "OK:" in capsys.readouterr().out


def test_check_fails_on_drift_with_ascii_marker(tmp_path, capsys):
    out = tmp_path / "api.generated.ts"
    out.write_text(build_output() + "\n// manual drift\n", encoding="utf-8")
    assert main(out_path=str(out)) == 1
    assert "FAIL:" in capsys.readouterr().out


def test_check_fails_when_artifact_missing(tmp_path, capsys):
    assert main(out_path=str(tmp_path / "missing.ts")) == 1
    out = capsys.readouterr().out
    assert "FAIL:" in out and "missing" in out
