"""
/api/plugins + /api/skills — 技能配置端点

Skill 下拉数据 = 仅文档 Skill（data/skills/*.md）。
代码内置 Skill（编剧/分镜师/制片）已按用户要求彻底移除，不得再回到下拉框。
文档 Skill 的 system_prompt 即文档全文——用户改文档就是改流程。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from loguru import logger

from src.video_agent.web.skill_docs import (
    get_skill_doc,
    list_skill_docs,
    list_skill_doc_history,
    save_skill_doc,
    delete_skill_doc,
)

router = APIRouter()


@router.get("/plugins/ftdyb-agent/config")
async def get_agent_config():
    """前端 agentSkillSelect 下拉框数据源：仅文档 Skill（用户可见可编辑）。

    历史教训：代码 Skill（SkillRegistry）曾在改造计划中被加回下拉，
    导致用户删过的「编剧/分镜师/制片 Agent」复活。现永久移除。
    """
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
    return {"skills": doc_skills}


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


@router.get("/skills/docs/{slug}/history")
async def get_skill_doc_history(slug: str):
    """Skill 文档历史版本（新→旧，含全文；前端可查看/回滚）"""
    try:
        return {"versions": list_skill_doc_history(slug)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/skills/docs/{slug}")
async def delete_one_skill_doc(slug: str):
    """删除指定 Skill 文档"""
    try:
        delete_skill_doc(slug)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


class SkillFormatRequest(BaseModel):
    content: str


_FORMAT_SYSTEM = """你是一个 Skill 文档格式化专家。用户会给你一段文本（可能是任意格式的流程说明、提示词、规则等），
请将其整理为以下标准 Skill Markdown 格式：

# Skill 名称

> 调用规则：一句话说明何时使用本 Skill

## 流程规划

### 步骤一
...

### 步骤二
...

要求：
- 保留原文的核心内容和逻辑，不要编造新内容
- 用中文输出
- 只输出整理后的 Markdown，不要加任何解释
"""


@router.post("/skills/format")
async def format_skill_content(body: SkillFormatRequest):
    """用 LLM 将任意文本整理为标准 Skill markdown 格式（LLM 不可用时返回原文）"""
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="内容不能为空")
    try:
        from src.video_agent.adapters.factory import AdapterFactory
        adapter = AdapterFactory.create("chat")
        messages = [
            {"role": "system", "content": _FORMAT_SYSTEM},
            {"role": "user", "content": body.content},
        ]
        result = await adapter.generate(messages, temperature=0.3)
        formatted = (result.text or "").strip()
        if formatted:
            return {"content": formatted}
    except Exception as e:
        logger.warning(f"[SkillFormat] LLM 整理失败，返回原文: {e}")
    return {"content": body.content}
