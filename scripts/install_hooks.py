"""安装 Git pre-commit 钩子（任务 #18：钩子自动安装，替代手工复制）。

把 scripts/pre-commit.sh 安装到 .git/hooks/pre-commit：
- 幂等：钩子已存在且内容一致（行尾归一比较，兼容 CRLF/LF）→ 直接通过
- 已存在但内容不同 → 仅提示，不覆盖（避免破坏他人本地定制）
- 安装时统一写 LF 行尾（sh 钩子在 Git Bash/POSIX 下更稳）
- 非 Git 仓库（无 .git 目录）→ 提示并放行（退出码 0，npm prepare 在
  无 .git 环境如 CI 产物安装时不炸）

用法：
    python scripts/install_hooks.py          # 一步安装
    npm run hooks                            # package.json 一步入口
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "scripts" / "pre-commit.sh"
HOOKS_DIR = ROOT / ".git" / "hooks"
TARGET = HOOKS_DIR / "pre-commit"


def main() -> int:
    if not SOURCE.is_file():
        print(f"[install_hooks] FAIL: 源钩子不存在: {SOURCE}")
        return 1

    if not HOOKS_DIR.is_dir():
        # 无 .git（如 npm 安装到非仓库目录）：静默放行
        print("[install_hooks] SKIP: 未检测到 .git/hooks，跳过安装（非 Git 仓库环境）")
        return 0

    source_lf = SOURCE.read_bytes().replace(b"\r\n", b"\n")

    if TARGET.is_file():
        if TARGET.read_bytes().replace(b"\r\n", b"\n") == source_lf:
            print(f"[install_hooks] OK: 钩子已安装且为最新: {TARGET}")
            return 0
        print(f"[install_hooks] WARN: {TARGET} 已存在且内容与源不同，未覆盖。")
        print("[install_hooks]       如需强制安装，请先手工删除该文件后重跑本脚本。")
        return 0

    TARGET.write_bytes(source_lf)
    if os.name != "nt":
        os.chmod(TARGET, 0o755)
    print(f"[install_hooks] OK: 已安装 pre-commit 钩子 -> {TARGET}")
    print("[install_hooks]     commit 前自动跑 pytest unit + vitest；SKIP_PRECOMMIT=1 可跳过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
