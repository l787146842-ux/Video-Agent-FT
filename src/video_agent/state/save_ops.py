"""版本闸与防抖落盘域（自 manager.py 切出）。

职责：StateManager 的持久化防护簇——版本账本闸（乐观锁防旧盖新）、
防抖合并落盘（高频路径不阻塞事件循环）、磁盘账本读取与陈旧重载。

本模块只依赖 StateManager 的既有接口/内部属性（同包受控访问），
不反向 import manager（类级账本经
``type(svc)._board_versions`` 访问），无循环依赖。
"""
import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from src.video_agent.exceptions import StateError

from .repository import StateRepository

if TYPE_CHECKING:  # 仅类型标注用，运行期不 import manager（防循环）
    from .manager import StateManager

# 落盘防抖窗口（秒）：合并短窗口内的多次变更统一写一次盘，
# 避免 add_chat_message / Agent 动作等高频路径全量双写阻塞事件循环
_SAVE_DEBOUNCE_SECONDS = 0.3


def disk_board_version(svc: "StateManager", project_id: str) -> int:
    """索引落盘的项目版本号（读不到为 0）。"""
    try:
        index = svc._repo.read_index()
        for p in index.get("projects", []):
            if p["id"] == project_id:
                return int(p.get("board_version") or 0)
    except (TypeError, ValueError) as _e:
        logger.debug("[manager] 忽略异常: {}", _e)
    return 0


def save(svc: "StateManager") -> bool:
    """持久化：写入当前项目 + 更新 index 时间戳（经 repo 接口；
    sqlite 后端下唯一落盘点为 state.sqlite3，
    save_compat 在 sqlite 仓库为空实现）

    返回是否真正落盘：版本闸放弃写入时返回 False（调用方据此判冲突，
    破坏性写入路径不得静默放行）。

    版本账本闸（任务级隔离后全局单例在任务期间不刷新，
    切换/保存若用过期内存回写会抹掉后台任务的新数据）：磁盘账本比
    本实例已知号新 → 别的实例已写更新，放弃本次写入，防旧实例盖新实例。
    """
    pid = svc._active_project_id
    board_versions = type(svc)._board_versions
    try:
        index = svc._repo.read_index()
        disk_v = 0
        for p in index.get("projects", []):
            if p["id"] == pid:
                try:
                    disk_v = int(p.get("board_version") or 0)
                except (TypeError, ValueError):
                    disk_v = 0
                break
        if svc._known_version is not None and disk_v > svc._known_version:
            logger.warning(
                f"[StateManager] 放弃过期写入：项目 {pid} 磁盘账本 {disk_v} "
                f"新于本实例已知 {svc._known_version}（别的实例写过更新数据）"
            )
            svc._known_version = disk_v
            return False
        svc._repo.save_project(pid, svc._raw_state)
        svc._repo.save_compat(svc._raw_state)
        # 版号 +1 并随索引落盘（重启继承；读取/加载不触发递增）；
        # 取磁盘与进程内账本的较大者，保证两本不分裂
        v = max(disk_v, board_versions.get(pid, 0)) + 1
        for p in index.get("projects", []):
            if p["id"] == pid:
                p["updated_at"] = StateRepository.now_iso()
                board_versions[p["id"]] = v
                p["board_version"] = v
                break
        svc._repo.write_index(index)
        svc._known_version = v
        # 状态变更时失效上下文缓存
        svc._context_cache.clear()
        logger.debug("[StateManager] Saved")
        return True
    except Exception as e:
        logger.error(f"[StateManager] Save failed: {e}")
        raise StateError(f"状态持久化失败: {e}") from e


def reload_if_stale(svc: "StateManager") -> bool:
    """磁盘账本比本实例已知号新（别的实例——如后台任务专属实例——写过
    更新数据）时，从磁盘重载活跃项目状态，保证只读路径（context-usage
    等）不返回陈旧值。返回是否重载。

    本实例尚有防抖挂起写（_save_dirty）时跳过，避免冲掉未落盘的本地变更。
    """
    if svc._save_dirty:
        return False
    pid = svc._active_project_id
    if not pid:
        return False
    disk_v = disk_board_version(svc, pid)
    if svc._known_version is not None and disk_v <= svc._known_version:
        return False
    loaded = svc._repo.load_project(pid)
    if loaded is None:
        return False
    svc._raw_state = loaded
    svc._known_version = disk_v
    svc._state_dirty = True
    svc._context_cache.clear()
    svc._clear_undo_redo()
    svc._ensure_conversations()
    return True


def board_version(svc: "StateManager") -> int:
    """当前项目版本号（同项目所有实例共享一本账，重启从落盘继承）。"""
    board_versions = type(svc)._board_versions
    pid = svc._active_project_id
    if pid in board_versions:
        return board_versions[pid]
    try:
        index = svc._repo.read_index()
        v = int(next(
            (p.get("board_version") for p in index.get("projects", [])
             if p.get("id") == pid),
            0,
        ) or 0)
    except (TypeError, ValueError):
        v = 0
    board_versions[pid] = v
    return v


async def save_async(svc: "StateManager") -> bool:
    """异步立即落盘：写盘移 worker 线程，避免在 async 链路中阻塞事件循环。

    用于路由层显式保存（用户编辑保存等需要即时持久性保证的路径）。
    返回是否真正落盘（同 save）。
    """
    return await asyncio.to_thread(save, svc)


def save_debounced(svc: "StateManager") -> None:
    """防抖落盘：合并 300ms 窗口内的多次变更，统一写一次盘（写盘移 worker 线程）。

    用于 add_chat_message / Agent 动作执行等高频路径。
    无运行中事件循环时（CLI / 同步测试路径）退化为立即同步落盘，保证持久性语义。
    """
    svc._save_dirty = True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        svc._save_dirty = False
        save(svc)
        return
    if svc._save_flush_task is None or svc._save_flush_task.done():
        svc._save_flush_task = loop.create_task(_debounced_flush(svc))


async def _debounced_flush(svc: "StateManager") -> None:
    """防抖任务：窗口过后把脏状态一次性落盘（失败仅记录，下次变更会再触发）"""
    try:
        await asyncio.sleep(_SAVE_DEBOUNCE_SECONDS)
        if svc._save_dirty:
            svc._save_dirty = False
            await asyncio.to_thread(save, svc)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"[StateManager] 防抖落盘失败: {e}")


def flush_save(svc: "StateManager") -> None:
    """立即冲刷防抖落盘的挂起变更（服务关闭 / 需要持久性保证时调用）"""
    was_dirty = svc._save_dirty
    svc._save_dirty = False
    if svc._save_flush_task is not None and not svc._save_flush_task.done():
        svc._save_flush_task.cancel()
    svc._save_flush_task = None
    if was_dirty:
        save(svc)
