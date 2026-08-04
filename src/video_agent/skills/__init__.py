"""
Skills 系统 — 纯 prompt 预设。

重要变更（用户要求）：代码内置 Skill（编剧/分镜师/制片 Agent）已彻底移除，
不再提供类定义与默认注册；下拉框、Skill 目录、read_skill 均只认
data/skills/*.md 文档 Skill（用户可见可编辑，改文档即改流程）。
本模块仅保留 BaseSkill/SkillRegistry 基础设施，当前无任何内置注册项。
"""
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.utils.prompts import load_prompt


class BaseSkill:
    """Skill 基类 — 每个 Skill 对应一种 Agent 角色预设（纯数据，无执行逻辑）"""

    name: str = ""
    display_name: str = ""
    description: str = ""
    # prompt 文件（相对于 prompts/ 目录），如 "skills/story-generator.md"
    prompt_file: str = ""

    # state 字段 → skill 输入的映射（可选，预留）
    input_mapping: Dict[str, str] = {}
    # skill 输出 → state 字段的映射（可选，预留）
    output_mapping: Dict[str, str] = {}

    @property
    def system_prompt(self) -> str:
        """从 prompts/skills/*.md 加载角色提示词（Rule6: prompt 外置）"""
        return load_prompt(self.prompt_file).strip() if self.prompt_file else ""

    def to_config(self) -> Dict[str, str]:
        """返回前端 Skill 下拉框所需的配置"""
        return {
            "id": self.name,
            "name": self.display_name,
            "description": self.description,
            "system_prompt": self.system_prompt,
        }


class SkillRegistry:
    """Skill 注册器 — 单例。

    注意：当前无任何内置注册项。编剧/分镜师/制片三个代码 Skill 已按用户
    要求彻底删除（类定义、默认注册、提示词文件均已移除），
    请勿重新添加内置 Skill 到前端下拉。
    """

    _skills: Dict[str, BaseSkill] = {}

    @classmethod
    def register(cls, skill: BaseSkill):
        if not skill.name:
            raise ValueError("Skill must have a valid 'name' attribute.")
        cls._skills[skill.name] = skill
        logger.debug(f"[Skills] Registered: {skill.name} ({skill.display_name})")

    @classmethod
    def get(cls, name: str) -> Optional[BaseSkill]:
        return cls._skills.get(name)

    @classmethod
    def get_all(cls) -> List[BaseSkill]:
        return list(cls._skills.values())

    @classmethod
    def get_all_configs(cls) -> List[Dict[str, str]]:
        """返回所有 Skill 的前端配置列表"""
        return [s.to_config() for s in cls._skills.values()]

    @classmethod
    def reset(cls):
        """清空注册表（测试用）"""
        cls._skills = {}
