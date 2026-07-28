"""
Skills 系统
基类 + 注册器 + 具体 Skill 实现。
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

from loguru import logger


class BaseSkill(ABC):
    """Skill 基类 — 每个 Skill 对应一种 Agent 角色/能力"""

    name: str = ""
    display_name: str = ""
    description: str = ""
    system_prompt: str = ""

    # state 字段 → skill 输入的映射（可选）
    input_mapping: Dict[str, str] = {}
    # skill 输出 → state 字段的映射（可选）
    output_mapping: Dict[str, str] = {}

    @abstractmethod
    async def execute(self, context: Dict[str, Any], llm_client: Any = None) -> Dict[str, Any]:
        """
        执行 Skill 逻辑。
        context: 从 StateManager 提取的上下文
        llm_client: LLM 调用客户端（可选）
        返回: 执行结果 dict
        """
        ...

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
# 具体 Skill 实现
# =======================

class StoryGeneratorSkill(BaseSkill):
    """编剧 Skill — 从目标/剧本生成故事结构"""

    name = "story-generator"
    display_name = "编剧 Agent"
    description = "从用户目标出发，生成完整的故事大纲、场景和角色设定"
    system_prompt = (
        "你是一位专业影视编剧 Agent。你的任务是根据用户提供的主题或目标，"
        "生成完整的故事大纲，包括：场景列表、角色设定、对白要点、情绪曲线。\n"
        "输出格式要结构化，方便后续分镜拆解。"
        "当用户确认故事后，使用 studio-actions 更新故事板分组描述。"
    )
    input_mapping = {"user_goal": "goal", "story": "existing_story"}
    output_mapping = {"scenes": "story.scenes", "characters": "story.characters"}

    async def execute(self, context: Dict[str, Any], llm_client: Any = None) -> Dict[str, Any]:
        goal = context.get("goal", "")
        # Mock 实现（后续接 LLM）
        return {
            "scenes": [
                {"scene_id": "sc-1", "description": f"开场：{goal[:20]}...", "duration_seconds": 8.0}
            ],
            "characters": [
                {"character_id": "ch-1", "name": "主角", "role": "protagonist"}
            ],
        }


class ImagePromptSkill(BaseSkill):
    """分镜师 Skill — 生成可执行的图片/视频提示词"""

    name = "image-prompt"
    display_name = "分镜师 Agent"
    description = "将故事场景转化为可执行的图片/视频生成提示词"
    system_prompt = (
        "你是一位影视分镜师 Agent。你的任务是将故事场景拆解为具体的镜头，"
        "并为每个镜头生成可执行的图片/视频生成提示词。\n"
        "提示词要求：包含画面构图、光影、材质、镜头运动、风格关键词。\n"
        "使用 studio-actions 的 update_draft 或 add_draft 将提示词写入故事板。"
    )
    input_mapping = {"storyboard": "current_storyboard"}
    output_mapping = {"prompts": "storyboard.shots[].visual_prompt"}

    async def execute(self, context: Dict[str, Any], llm_client: Any = None) -> Dict[str, Any]:
        return {"prompts": ["电影级光影，超高细节，8K 分辨率，体积光，景深虚化"]}


class DirectorAgentSkill(BaseSkill):
    """导演 Skill — 全局把控与决策"""

    name = "production-agent"
    display_name = "制片 Agent"
    description = "全局把控项目进度，协调编剧、分镜、生成各环节"
    system_prompt = (
        "你是一位资深影视制片人 Agent，擅长从剧本出发拆解关键元素、分镜和音频层，"
        "并给出可执行的生成提示词。你可以：\n"
        "- 分析当前故事板状态，给出优化建议\n"
        "- 修改草稿提示词、确认/否决草稿\n"
        "- 新增关键元素或分镜\n"
        "- 绑定参考素材\n"
        "使用 studio-actions JSON 块来操作故事板。"
    )
    input_mapping = {}
    output_mapping = {}

    async def execute(self, context: Dict[str, Any], llm_client: Any = None) -> Dict[str, Any]:
        return {"status": "ok", "message": "制片 Agent 就绪"}


# =======================
# 默认注册
# =======================

def register_default_skills():
    """注册所有内置 Skill"""
    SkillRegistry.register(StoryGeneratorSkill())
    SkillRegistry.register(ImagePromptSkill())
    SkillRegistry.register(DirectorAgentSkill())
    logger.info(f"[Skills] {len(SkillRegistry.get_all())} skills registered")
