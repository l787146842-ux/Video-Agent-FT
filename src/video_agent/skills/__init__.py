"""
Skills 系统 — 纯 prompt 预设。

定位（FIX_PLAN P1-13）：Skill 是前端角色预设的载体，system_prompt 统一外置到
prompts/skills/*.md（Rule6），经 load_prompt() 加载；不再提供 mock execute()
假象——真正生效路径是 prompt 经前端 extra_system 注入 Planner。
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
    """Skill 注册器 — 单例"""

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


# =======================
# 具体 Skill 预设
# =======================

class StoryGeneratorSkill(BaseSkill):
    """编剧 Skill — 从目标/剧本生成故事结构"""

    name = "story-generator"
    display_name = "编剧 Agent"
    description = "从用户目标出发，生成完整的故事大纲、场景和角色设定"
    prompt_file = "skills/story-generator.md"
    input_mapping = {"user_goal": "goal", "story": "existing_story"}
    output_mapping = {"scenes": "story.scenes", "characters": "story.characters"}


class ImagePromptSkill(BaseSkill):
    """分镜师 Skill — 生成可执行的图片/视频提示词"""

    name = "image-prompt"
    display_name = "分镜师 Agent"
    description = "将故事场景转化为可执行的图片/视频生成提示词"
    prompt_file = "skills/image-prompt.md"
    input_mapping = {"storyboard": "current_storyboard"}
    output_mapping = {"prompts": "storyboard.shots[].visual_prompt"}


class DirectorAgentSkill(BaseSkill):
    """导演 Skill — 全局把控与决策"""

    name = "production-agent"
    display_name = "制片 Agent"
    description = "全局把控项目进度，协调编剧、分镜、生成各环节"
    prompt_file = "skills/production-agent.md"
    input_mapping = {}
    output_mapping = {}


# =======================
# 默认注册
# =======================

def register_default_skills():
    """注册所有内置 Skill"""
    SkillRegistry.register(StoryGeneratorSkill())
    SkillRegistry.register(ImagePromptSkill())
    SkillRegistry.register(DirectorAgentSkill())
    logger.info(f"[Skills] {len(SkillRegistry.get_all())} skills registered")
