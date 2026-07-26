"""
/api/gemini-cli, /api/codex, /api/jimeng — CLI 工具状态检测端点
前端"检测 CLI"按钮调用，判断本机是否已安装对应 CLI。
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from loguru import logger

router = APIRouter()

# help 端点的 command 参数只允许简单的子命令名，防止把任意参数透传给本机 CLI
_SAFE_SUBCOMMAND_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,30}$")


def _help_args(command: str) -> list[str]:
    """校验并构造 help 参数：空 → --help；子命令 → <sub> --help；其他一律拒绝"""
    if not command:
        return ["--help"]
    if not _SAFE_SUBCOMMAND_RE.match(command):
        raise HTTPException(status_code=400, detail="command 仅允许字母/数字/连字符的子命令名")
    return [command, "--help"]


def _find_exe(name: str, winget_pattern: str = "") -> str | None:
    """在 PATH 中查找可执行文件，找不到则尝试 WinGet 包目录"""
    exe = shutil.which(name)
    if exe:
        return exe
    # Windows WinGet 安装路径
    if winget_pattern:
        local_app = os.getenv("LOCALAPPDATA", "")
        if local_app:
            import glob
            pattern = os.path.join(local_app, winget_pattern)
            matches = sorted(glob.glob(pattern), reverse=True)
            if matches:
                return matches[0]
    return None


def _run_version(exe_path: str, args: list[str] | None = None) -> str:
    """运行 CLI 获取版本号"""
    cmd = [exe_path] + (args or ["--version"])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        output = (result.stdout or result.stderr or "").strip()
        # 取第一行作为版本信息
        return output.splitlines()[0] if output else ""
    except Exception as e:
        logger.debug(f"[CLI] 获取版本失败: {e}")
        return ""


# ---------- Gemini CLI (agy) ----------
@router.get("/gemini-cli/status")
async def gemini_cli_status():
    """检测 Antigravity CLI (agy) 是否已安装"""
    exe = _find_exe("agy", r"Microsoft\WinGet\Packages\Google.AntigravityCLI_*\agy.exe")
    if not exe:
        return {"installed": False, "version": "", "path": "", "message": "未找到 agy，请先运行 CLI\\windows\\gemini\\1-install_gemini_cli.bat"}

    version = _run_version(exe)
    return {
        "installed": True,
        "version": version,
        "path": exe,
        "message": f"Antigravity CLI 已就绪",
    }


@router.get("/gemini-cli/help")
async def gemini_cli_help(command: str = ""):
    """获取 gemini CLI 帮助输出"""
    exe = _find_exe("agy", r"Microsoft\WinGet\Packages\Google.AntigravityCLI_*\agy.exe")
    if not exe:
        return {"output": "agy 未安装", "ok": False}

    args = _help_args(command)
    try:
        result = subprocess.run(
            [exe] + args,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        output = result.stdout or result.stderr or "(无输出)"
        return {"output": output, "ok": True}
    except Exception as e:
        return {"output": str(e), "ok": False}


# ---------- Codex CLI ----------
@router.get("/codex/status")
async def codex_cli_status():
    """检测 OpenAI Codex CLI 是否已安装"""
    exe = _find_exe("codex", r"Microsoft\WinGet\Packages\OpenAI.Codex_*\codex.exe")
    if not exe:
        # 也尝试 npm 全局安装路径
        exe = _find_exe("codex.cmd") or _find_exe("codex")
    if not exe:
        return {"installed": False, "version": "", "path": "", "message": "未找到 codex CLI"}

    version = _run_version(exe)
    return {
        "installed": True,
        "version": version,
        "path": exe,
        "message": "Codex CLI 已就绪",
    }


@router.get("/codex/help")
async def codex_cli_help(command: str = ""):
    """获取 codex CLI 帮助输出"""
    exe = _find_exe("codex") or _find_exe("codex.cmd")
    if not exe:
        return {"output": "codex 未安装", "ok": False}

    args = _help_args(command)
    try:
        result = subprocess.run(
            [exe] + args,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        output = result.stdout or result.stderr or "(无输出)"
        return {"output": output, "ok": True}
    except Exception as e:
        return {"output": str(e), "ok": False}


# ---------- 即梦 CLI (dreamina) ----------
@router.get("/jimeng/status")
async def jimeng_cli_status():
    """检测即梦 CLI (dreamina) 是否已安装及登录状态"""
    exe = _find_exe("dreamina") or _find_exe("dreamina.cmd")
    if not exe:
        return {"installed": False, "logged_in": False, "version": "", "path": "", "message": "未找到 dreamina CLI"}

    version = _run_version(exe)

    # 尝试检测登录状态
    logged_in = False
    raw = ""
    try:
        result = subprocess.run(
            [exe, "whoami"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        raw = (result.stdout or result.stderr or "").strip()
        logged_in = result.returncode == 0 and "not logged in" not in raw.lower()
    except Exception:
        pass

    return {
        "installed": True,
        "logged_in": logged_in,
        "version": version,
        "path": exe,
        "raw": raw,
        "message": "已登录" if logged_in else "未登录，请执行 dreamina login",
    }
