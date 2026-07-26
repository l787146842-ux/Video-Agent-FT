"""
Studio State Service
统一管理 Studio 前端的内存态数据 + StateManager 持久化。
所有路由共享同一个 StudioStateService 实例。
"""
import asyncio
import json
import os
import time
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.utils.fileio import atomic_write_text


# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
WORKSPACE_DIR = PROJECT_ROOT / "workspace"

# 默认 demo 数据（首次启动时使用）
_DEFAULT_STATE: Dict[str, Any] = {
    "project_id": "proj_001",
    "project_name": "深空探险三体",
    "status": "idle",
    "keyElements": [
        {
            "id": "ke-1",
            "title": "人物设定：探险队长罗林",
            "desc": "穿着重型外骨骼战甲，眼神坚毅，面部有微小机械疤痕，带高科技全息单镜片。",
            "drafts": [
                {
                    "id": "ke-1-d1",
                    "label": "草稿1 - 概念高光",
                    "tag": "推荐",
                    "mediaType": "image",
                    "imgUrl": "https://picsum.photos/id/1025/1200/800",
                    "prompt": "超高细节，探险队长罗林特写，正面视角，穿着黑色磨损外骨骼战甲，全息单镜片散发蓝光，眼神坚毅，电影级采光，8k分辨率，赛博朋克现实主义 --ar 16:9 --v 6.0",
                    "model": "Flux.1",
                    "aspectRatio": "16:9",
                    "size": "1280x720",
                    "refAssets": [],
                },
                {
                    "id": "ke-1-d2",
                    "label": "草稿2 - 战甲细节",
                    "tag": "已确认",
                    "mediaType": "image",
                    "imgUrl": "https://picsum.photos/id/1062/1200/800",
                    "prompt": "探险队长战甲金属纹理特写，带有微光粒子与机械结构拼合，真实金属光泽，硬核科幻设计 --ar 16:9",
                    "model": "Midjourney v6",
                    "aspectRatio": "16:9",
                    "size": "1280x720",
                    "refAssets": [],
                },
            ],
        },
        {
            "id": "ke-2",
            "title": "场景设定：二维化降维星云",
            "desc": "太阳系边缘被二向箔压缩形成的平面星云，颜色绚丽而诡异，毫无厚度的平面质感。",
            "drafts": [
                {
                    "id": "ke-2-d1",
                    "label": "草稿1 - 星云全景",
                    "tag": "草稿",
                    "mediaType": "image",
                    "imgUrl": "https://picsum.photos/id/1015/1200/800",
                    "prompt": "三体降维打击视觉表现，二维化的太阳系星空，极度绚丽的绚彩平坦漩涡，无深度感，空间折叠美学，高清电影剧照 --ar 21:9",
                    "model": "Nano Pro",
                    "aspectRatio": "21:9",
                    "size": "1280x544",
                    "refAssets": [],
                }
            ],
        },
    ],
    "shots": [
        {
            "id": "shot-1",
            "title": "镜头 01",
            "duration": "4.5s",
            "roughDesc": "飞船缓缓穿过降维星云边缘，产生扭曲的光晕与能量涟漪。",
            "drafts": [
                {
                    "id": "shot-1-d1",
                    "label": "分镜卡片 1",
                    "tag": "生成中",
                    "mediaType": "video",
                    "videoUrl": "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4",
                    "prompt": "镜头向前慢推，探险飞船从左向右穿过炫彩二维漩涡，船体表面泛起金色能量涟漪，流畅电影运镜，60fps，科幻大片质感",
                    "mode": "全能参考",
                    "model": "Sora",
                    "resolution": "1080p",
                    "duration": "5s",
                    "aspectRatio": "16:9",
                    "refAssets": ["https://picsum.photos/id/1015/400/300"],
                }
            ],
        },
        {
            "id": "shot-2",
            "title": "镜头 02",
            "duration": "3.0s",
            "roughDesc": "罗林队长推下推进器手柄，仪表盘指针剧烈抖动。",
            "drafts": [
                {
                    "id": "shot-2-d1",
                    "label": "分镜卡片 1",
                    "tag": "待确认",
                    "mediaType": "video",
                    "videoUrl": "",
                    "prompt": "特写镜头：硬朗的大手推下金属推进器手柄，全息控制面板红光闪烁，仪表盘指针快速飙升，镜头轻微震颤",
                    "mode": "图生视频",
                    "model": "Luma Dream Machine",
                    "resolution": "1080p",
                    "duration": "3s",
                    "aspectRatio": "16:9",
                    "refAssets": [],
                }
            ],
        },
    ],
    "audioItems": [
        {
            "id": "audio-1",
            "title": "音频层 01 - 旁白与环境音",
            "timeRange": "00:00 - 00:08",
            "prompt": "深沉压抑的宇宙低频震动配乐，伴随着高科技飞船报警蜂鸣声，以及男旁白深邃的声音：'太阳系正在坠入二维...'",
            "drafts": [
                {
                    "id": "audio-1-d1",
                    "label": "音频草稿 1",
                    "mediaType": "audio",
                    "prompt": "深沉压抑宇宙低音 + 高科技报警音 + 男声独白：'太阳系正在坠入二维...'",
                    "mode": "多模态音频生成",
                    "model": "ElevenLabs",
                    "timbre": "深邃男声 (Deep Narrator)",
                    "refAssets": [],
                }
            ],
        }
    ],
    "assets": [
        {"id": "ast-1", "name": "罗林肖像参考.png", "type": "image", "isBound": True, "url": "https://picsum.photos/id/1025/400/300"},
        {"id": "ast-2", "name": "星云纹理背景.jpg", "type": "image", "isBound": True, "url": "https://picsum.photos/id/1015/400/300"},
        {"id": "ast-3", "name": "飞船引擎音效.mp3", "type": "audio", "isBound": False, "url": ""},
        {"id": "ast-4", "name": "二向箔降维渲染.mp4", "type": "video", "isBound": False, "url": "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4"},
        {"id": "ast-5", "name": "空间站草图.jpg", "type": "image", "isBound": False, "url": "https://picsum.photos/id/1062/400/300"},
    ],
    "chatMessages": [
        {
            "sender": "agent",
            "text": "你好！我是你的 AI 编剧与导演助手。我已经根据《深空探险三体》剧本提取出了 2 个关键元素、2 个关键分镜和音频层。你可以点击左侧草稿卡片进行预览，或者直接告诉我需要调整什么！",
        }
    ],
}


class StudioStateService:
    """
    单例式状态服务 — 所有路由共享。
    内存态 + 多项目 JSON 文件持久化。
    """

    _instance: Optional["StudioStateService"] = None

    def __init__(self, base_dir: Optional[Path] = None):
        # base_dir 可注入（测试用临时目录），默认 workspace/
        base = Path(base_dir) if base_dir else WORKSPACE_DIR
        self._workspace_dir = base
        self._state_file = base / "studio_state.json"          # 兼容旧版单文件
        self._projects_dir = base / "projects"
        self._index_file = self._projects_dir / "index.json"

        # 供 async 路由在「变更 + 落盘」临界区使用，避免并发请求交叉写
        self.lock = asyncio.Lock()

        self._state: Dict[str, Any] = {}
        self._active_project_id: str = ""
        self._load()

    @classmethod
    def get_instance(cls) -> "StudioStateService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def state(self) -> Dict[str, Any]:
        return self._state

    @property
    def active_project_id(self) -> str:
        return self._active_project_id

    # ---------- 项目索引管理 ----------

    def _read_index(self) -> Dict[str, Any]:
        """读取 projects/index.json"""
        if self._index_file.exists():
            try:
                return json.loads(self._index_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"[StudioState] Failed to read index: {e}")
        return {"active_project_id": "", "projects": []}

    def _write_index(self, index: Dict[str, Any]):
        """写入 projects/index.json（原子写）"""
        atomic_write_text(self._index_file, json.dumps(index, ensure_ascii=False, indent=2))

    def _now_iso(self) -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # ---------- 持久化 ----------

    def _load(self):
        """加载：优先从 projects/index.json 找活跃项目，否则迁移旧 studio_state.json"""
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        self._projects_dir.mkdir(parents=True, exist_ok=True)

        index = self._read_index()
        active_id = index.get("active_project_id", "")
        projects = index.get("projects", [])

        # 已有项目索引
        if active_id and projects:
            self._active_project_id = active_id
            if self._load_from_project_dir(active_id):
                logger.info(f"[StudioState] Loaded project: {active_id}")
                return

        # 迁移旧 studio_state.json 为第一个项目
        if self._state_file.exists():
            try:
                old_state = json.loads(self._state_file.read_text(encoding="utf-8"))
                pid = old_state.get("project_id", f"proj-{int(time.time())}")
                pname = old_state.get("project_name", "迁移项目")
                self._state = old_state
                self._active_project_id = pid
                self._save_to_project_dir(pid)
                self._write_index({
                    "active_project_id": pid,
                    "projects": [{"id": pid, "name": pname, "created_at": self._now_iso(), "updated_at": self._now_iso()}]
                })
                logger.info(f"[StudioState] Migrated legacy state to project: {pid}")
                return
            except Exception as e:
                logger.warning(f"[StudioState] Migration failed: {e}")

        # 全新初始化：创建 demo 项目
        self._state = json.loads(json.dumps(_DEFAULT_STATE))
        self._active_project_id = self._state.get("project_id", "proj_001")
        self._save_to_project_dir(self._active_project_id)
        self._write_index({
            "active_project_id": self._active_project_id,
            "projects": [{"id": self._active_project_id, "name": self._state.get("project_name", "Demo"), "created_at": self._now_iso(), "updated_at": self._now_iso()}]
        })
        self._save_compat()
        logger.info("[StudioState] Initialized with default demo project")

    def _save_to_project_dir(self, project_id: str):
        """将内存状态写入对应项目目录（原子写）"""
        pdir = self._projects_dir / project_id
        atomic_write_text(pdir / "state.json", json.dumps(self._state, ensure_ascii=False, indent=2))

    def _load_from_project_dir(self, project_id: str) -> bool:
        """从项目目录加载状态到内存"""
        sfile = self._projects_dir / project_id / "state.json"
        if not sfile.exists():
            return False
        try:
            self._state = json.loads(sfile.read_text(encoding="utf-8"))
            return True
        except Exception as e:
            logger.warning(f"[StudioState] Failed to load project {project_id}: {e}")
            return False

    def _save_compat(self):
        """兼容写入 studio_state.json（原子写）"""
        try:
            atomic_write_text(self._state_file, json.dumps(self._state, ensure_ascii=False, indent=2))
        except Exception:
            pass

    def save(self):
        """持久化：写入当前项目目录 + 兼容文件 + 更新 index 时间戳"""
        try:
            self._save_to_project_dir(self._active_project_id)
            self._save_compat()
            # 更新 index 中的 updated_at
            index = self._read_index()
            for p in index.get("projects", []):
                if p["id"] == self._active_project_id:
                    p["updated_at"] = self._now_iso()
                    break
            self._write_index(index)
            logger.debug("[StudioState] Saved")
        except Exception as e:
            logger.error(f"[StudioState] Save failed: {e}")

    # ---------- 多项目管理 ----------

    def list_projects(self) -> Dict[str, Any]:
        """返回所有项目列表 + 当前活跃 ID"""
        index = self._read_index()
        return {
            "active_project_id": self._active_project_id,
            "projects": index.get("projects", []),
        }

    def create_project(self, name: str) -> str:
        """新建项目：保存当前 → 创建新项目 → 切换 → 返回 project_id"""
        # 保存当前项目
        if self._active_project_id:
            self._save_to_project_dir(self._active_project_id)

        project_id = f"proj-{int(time.time())}-{random.randint(100, 999)}"
        self._state = {
            "project_id": project_id,
            "project_name": name,
            "status": "idle",
            "keyElements": [],
            "shots": [],
            "audioItems": [],
            "assets": [],
            "chatMessages": [
                {
                    "sender": "agent",
                    "text": f"你好！我是你的 AI 编剧与导演助手。项目《{name}》已创建，告诉我你的创意目标，我来帮你规划关键元素、分镜和音频层！",
                }
            ],
        }
        self._active_project_id = project_id
        self._save_to_project_dir(project_id)
        self._save_compat()

        # 更新索引
        index = self._read_index()
        index["active_project_id"] = project_id
        index.setdefault("projects", []).append({
            "id": project_id,
            "name": name,
            "created_at": self._now_iso(),
            "updated_at": self._now_iso(),
        })
        self._write_index(index)
        logger.info(f"[StudioState] Created project: {name} ({project_id})")
        return project_id

    def switch_project(self, project_id: str) -> bool:
        """切换项目：保存当前 → 加载目标"""
        if project_id == self._active_project_id:
            return True
        # 保存当前
        if self._active_project_id:
            self._save_to_project_dir(self._active_project_id)
        # 加载目标
        if not self._load_from_project_dir(project_id):
            return False
        self._active_project_id = project_id
        self._save_compat()
        # 更新索引
        index = self._read_index()
        index["active_project_id"] = project_id
        self._write_index(index)
        logger.info(f"[StudioState] Switched to project: {project_id}")
        return True

    def delete_project(self, project_id: str) -> bool:
        """删除项目（硬删除）"""
        import shutil
        index = self._read_index()
        projects = index.get("projects", [])
        # 不允许删除最后一个项目
        if len(projects) <= 1:
            return False
        # 从索引移除
        index["projects"] = [p for p in projects if p["id"] != project_id]
        # 如果删除的是当前项目，切换到第一个
        if self._active_project_id == project_id:
            new_active = index["projects"][0]["id"] if index["projects"] else ""
            index["active_project_id"] = new_active
            self._write_index(index)
            self.switch_project(new_active)
        else:
            self._write_index(index)
        # 删除目录
        pdir = self._projects_dir / project_id
        if pdir.exists():
            shutil.rmtree(pdir, ignore_errors=True)
        logger.info(f"[StudioState] Deleted project: {project_id}")
        return True

    def reset(self, project_name: str = "未命名项目", project_id: str = ""):
        """兼容旧接口：内部调用 create_project"""
        self.create_project(project_name)

    # ---------- 查询辅助 ----------

    def get_groups(self) -> Dict[str, List[Dict]]:
        return {
            "keyElements": self._state.get("keyElements", []),
            "shots": self._state.get("shots", []),
            "audioItems": self._state.get("audioItems", []),
        }

    def get_assets(self) -> List[Dict]:
        return self._state.get("assets", [])

    def get_chat_messages(self) -> List[Dict]:
        return self._state.get("chatMessages", [])

    def add_chat_message(self, sender: str, text: str):
        self._state.setdefault("chatMessages", []).append({"sender": sender, "text": text})
        self.save()

    def get_full_snapshot(self) -> Dict[str, Any]:
        """返回完整状态快照（供前端刷新）"""
        return self._state

    def build_agent_context(self, asset_mode: str = "bound") -> str:
        """构建发送给 LLM 的 Studio 状态上下文"""
        assets = self._state.get("assets", [])
        if asset_mode != "all":
            assets = [a for a in assets if a.get("isBound")]

        snapshot = {
            "keyElements": [
                {
                    "id": g["id"],
                    "title": g.get("title", ""),
                    "desc": g.get("desc", ""),
                    "drafts": [
                        {
                            "id": d["id"],
                            "label": d.get("label", ""),
                            "tag": d.get("tag", ""),
                            "mediaType": d.get("mediaType", ""),
                            "prompt": d.get("prompt", ""),
                            "model": d.get("model", ""),
                        }
                        for d in g.get("drafts", [])
                    ],
                }
                for g in self._state.get("keyElements", [])
            ],
            "shots": [
                {
                    "id": g["id"],
                    "title": g.get("title", ""),
                    "duration": g.get("duration", ""),
                    "roughDesc": g.get("roughDesc", ""),
                    "drafts": [
                        {
                            "id": d["id"],
                            "label": d.get("label", ""),
                            "tag": d.get("tag", ""),
                            "prompt": d.get("prompt", ""),
                            "model": d.get("model", ""),
                            "mode": d.get("mode", ""),
                        }
                        for d in g.get("drafts", [])
                    ],
                }
                for g in self._state.get("shots", [])
            ],
            "audioItems": [
                {
                    "id": g["id"],
                    "title": g.get("title", ""),
                    "timeRange": g.get("timeRange", ""),
                    "prompt": g.get("prompt", ""),
                    "drafts": [
                        {
                            "id": d["id"],
                            "label": d.get("label", ""),
                            "prompt": d.get("prompt", ""),
                            "model": d.get("model", ""),
                        }
                        for d in g.get("drafts", [])
                    ],
                }
                for g in self._state.get("audioItems", [])
            ],
            "assets": [
                {"id": a["id"], "name": a.get("name", ""), "type": a.get("type", ""), "isBound": a.get("isBound", False)}
                for a in assets
            ],
        }
        return json.dumps(snapshot, ensure_ascii=False, indent=2)
