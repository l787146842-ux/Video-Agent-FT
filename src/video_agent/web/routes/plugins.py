"""
/api/plugins + /api/skills — 技能配置端点

Skill 下拉数据 = 文档 Skill（data/skills/*.md，排前、默认选中）+ 代码 Skill（SkillRegistry）。
文档 Skill 的 system_prompt 即文档全文——用户改文档就是改流程。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.video_agent.skills import SkillRegistry
from src.video_agent.web.skill_docs import (
    get_skill_doc,
    list_skill_docs,
    save_skill_doc,
)

router = APIRouter()


@router.get("/plugins/flova-agent/config")
async def get_agent_config():
    """前端 agentSkillSelect 下拉框数据源（文档 Skill 优先）"""
    doc_skills = [
        {
            "id": d["id"],
            "name": d["name"],
            "description": d["description"],
            "system_prompt": d["content"],
            "source": "doc",
            "slug": d["slug"],
        }
        for d in list_skill_docs()
    ]
    code_skills = [{**cfg, "source": "code"} for cfg in SkillRegistry.get_all_configs()]
    return {"skills": doc_skills + code_skills}


@router.get("/skills/docs")
async def get_skill_docs():
    """文档面板：Skill 文档列表（含全文）"""
    return {"docs": list_skill_docs()}


class SkillDocSave(BaseModel):
    content: str


@router.put("/skills/docs/{slug}")
async def put_skill_doc(slug: str, body: SkillDocSave):
    """保存 Skill 文档（新建或覆盖）"""
    try:
        doc = save_skill_doc(slug, body.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "doc": doc}


@router.get("/skills/docs/{slug}")
async def get_one_skill_doc(slug: str):
    try:
        doc = get_skill_doc(slug)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not doc:
        raise HTTPException(status_code=404, detail=f"Skill 文档 '{slug}' 不存在")
    return doc
