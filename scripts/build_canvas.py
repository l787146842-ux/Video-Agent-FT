"""构建画布子应用到 static/canvas-app（base=/canvas-app/）。

画布前端（vendors/infinite-canvas/web）是独立 React 子应用：
- 单独构建、单独产物，不并入主包（主包首屏 400KB 硬上限，画布单包 ~3.6MB）；
- Windows 下 esbuild 会往系统 TEMP 写临时文件，本机 TEMP 有清理保护，
  曾导致 "remove ... Access is denied" 构建失败，故构建期把 TEMP 收到 .tmp-build。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "vendors" / "infinite-canvas" / "web"
OUT_DIR = ROOT / "static" / "canvas-app"
TMP_DIR = ROOT / ".tmp-build"
BASE = "/canvas-app/"


def main() -> int:
    if not (WEB_DIR / "package.json").is_file():
        print(f"[build_canvas] FAIL - 画布源码缺失: {WEB_DIR}")
        return 1
    if not (WEB_DIR / "node_modules").is_dir():
        print("[build_canvas] 依赖未安装，请先执行: "
              "npm --prefix vendors/infinite-canvas/web install")
        return 1

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({"TEMP": str(TMP_DIR), "TMP": str(TMP_DIR), "TMPDIR": str(TMP_DIR)})
    npx = "npx.cmd" if os.name == "nt" else "npx"
    cmd = [npx, "vite", "build", f"--base={BASE}",
           f"--outDir={OUT_DIR}", "--emptyOutDir"]
    print(f"[build_canvas] {WEB_DIR} -> {OUT_DIR}")
    proc = subprocess.run(cmd, cwd=str(WEB_DIR), env=env)
    if proc.returncode != 0:
        print(f"[build_canvas] FAIL - vite build 退出码 {proc.returncode}")
        return proc.returncode

    if not (OUT_DIR / "index.html").is_file():
        print("[build_canvas] FAIL - 产物缺少 index.html")
        return 1
    size = sum(p.stat().st_size for p in OUT_DIR.rglob("*") if p.is_file())
    print(f"[build_canvas] OK - {size / 1024 / 1024:.2f} MB，index.html 就绪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
