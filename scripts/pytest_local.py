# -*- coding: utf-8 -*-
"""本机网络类用例红灯绕行器（D-22）——**不改仓库代码**。

背景：本机环境变量 `no_proxy`/`NO_PROXY` 含 `[::1]`，httpx 的
`get_environment_proxies()` 把它解析成非法挂载 `all://*[::1]`，
其后任何 `httpx.Client(...)` 构造即抛 `InvalidURL: Invalid port: ':1]'`
⇒ 42 个网络类用例在 fixture setup 阶段全红，与被测代码无关。

口径（见 `docs/未清偿债务清单.md` D-22）：属**本机环境**问题，不改仓库代码；
`[::1]` 已由 `::1` 覆盖同一语义，去掉此项不损失豁免面。

用法（等价于直接跑 pytest，只是先清掉那一项）：

    python scripts/pytest_local.py tests/unit -q
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_BAD = "[::1]"
_VARS = ("no_proxy", "NO_PROXY")


def sanitize() -> list:
    """从当前进程环境清掉 no_proxy/NO_PROXY 里的 `[::1]` 项。返回改动说明。"""
    notes = []
    for name in _VARS:
        raw = os.environ.get(name)
        if not raw:
            continue
        kept = [p.strip() for p in raw.split(",") if p.strip() and p.strip() != _BAD]
        cleaned = ",".join(kept)
        if cleaned != raw:
            os.environ[name] = cleaned
            notes.append(f"{name}: {raw!r} -> {cleaned!r}")
    return notes


def main() -> int:
    print(f"[pytest_local] BEFORE os.environ {_VARS[0]!r} = {os.environ.get(_VARS[0])!r}",
          file=sys.stderr)
    notes = sanitize()
    if notes:
        print("[pytest_local] 已清理 no_proxy 的非法项（D-22）：", file=sys.stderr)
        for n in notes:
            print(f"  - {n}", file=sys.stderr)
    print(f"[pytest_local] AFTER  os.environ {_VARS[0]!r} = {os.environ.get(_VARS[0])!r}",
          file=sys.stderr)

    # 自证：清理后 httpx 不应再有非法挂载
    import httpx._utils as u
    proxies = u.get_environment_proxies()
    bad = [k for k in proxies if _BAD in k and "*" in k]
    if bad:
        print(f"[pytest_local] ⚠ 仍存在非法代理挂载：{bad}", file=sys.stderr)
        return 2
    print("[pytest_local] httpx 代理表已干净", file=sys.stderr)

    root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, "-m", "pytest", *sys.argv[1:]]
    return subprocess.call(cmd, cwd=str(root))


if __name__ == "__main__":
    raise SystemExit(main())
