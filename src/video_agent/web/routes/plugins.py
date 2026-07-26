"""
/api/plugins — 插件/技能配置端点
前端 agentSkillSelect 下拉框数据源。
数据源：SkillRegistry（动态注册）。
"""
from fastapi import APIRouter

from src.video_agent.skills import SkillRegistry

router = APIRouter()


@router.get("/plugins/flova-agent/config")
async def get_agent_config():
    """前端 loadCanvasApiConfig() 中 skillsRes 调用"""
    return {"skills": SkillRegistry.get_all_configs()}
