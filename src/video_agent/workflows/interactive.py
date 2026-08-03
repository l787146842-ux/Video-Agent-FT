"""
交互式工作流引擎管理（单例）。

从 web/routes/workflow.py 抽出，解决 tools → routes 循环依赖。
tools/document_tools.py 和 routes/workflow.py 均从此模块导入。
"""
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS
from src.video_agent.web.actions import StudioActionExecutor
from src.video_agent.web.generation import (
    GenerationError,
    call_chat_completion,
    generate_image_via_provider,
)
from src.video_agent.web.provider_config import is_mock_provider
from src.video_agent.utils.prompts import load_prompt
from src.video_agent.workflows.engine import WorkflowEngine
from src.video_agent.workflows.models import (
    PhaseDefinition,
    PhaseExecution,
    RetryPolicy,
    WorkflowContextConfig,
    WorkflowDefinition,
)

# 每次工作流最多真实生成的图片数，防止失控消耗
MAX_IMAGES_PER_RUN = 4

# Studio Action 协议 prompt（直接从 prompts/ 加载，避免从 routes 导入产生循环依赖）
STUDIO_ACTION_PROTOCOL_PROMPT = load_prompt("planner/system.md")


# ---------- 工作流定义 ----------

def build_workflow_definition() -> WorkflowDefinition:
    """六阶段流水线：story → storyboard → (image, audio) → video → edit"""
    def phase(pid: str, name: str, deps: List[str]) -> PhaseDefinition:
        return PhaseDefinition(
            phase_id=pid,
            name=name,
            depends_on=deps,
            execution=PhaseExecution(skill=pid),
            timeout_seconds=600,
        )

    return WorkflowDefinition(
        workflow_id="wf_studio_pipeline",
        name="Studio Production Pipeline",
        context=WorkflowContextConfig(
            max_parallel_tasks=2,
            timeout_seconds=1800,
            retry_policy=RetryPolicy(max_retries=1, backoff="linear", base_delay_seconds=2),
        ),
        phases=[
            phase("story", "编剧", []),
            phase("storyboard", "分镜拆解", ["story"]),
            phase("image", "关键帧生成", ["storyboard"]),
            phase("audio", "音频合成", ["storyboard"]),
            phase("video", "视频生成", ["image"]),
            phase("edit", "剪辑合成", ["video", "audio"]),
        ],
    )


# ---------- 执行器构建 ----------

def build_executors(
    svc: StateManager,
    executor: StudioActionExecutor,
    run_ctx: Dict[str, Any],
    chat_provider: str,
    chat_model: str,
    image_provider: str,
    image_model: str,
    goal_getter: Callable[[], str],
    phase_configs: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Callable]:
    """构建六阶段执行器字典（统一实现，消除重复）

    Args:
        phase_configs: 阶段级模型配置覆盖，格式：
            {"story": {"provider": "openai", "model": "gpt-4o"},
             "image": {"provider": "volcengine", "model": "..."}}
            为空时所有阶段使用全局 provider/model。
    """
    phase_configs = phase_configs or {}
    has_llm = bool(chat_provider) and not is_mock_provider(chat_provider, chat_model)
    has_image = bool(image_provider) and not is_mock_provider(image_provider, image_model)

    def _resolve_chat(phase_id: str, phase: Optional[PhaseDefinition] = None) -> tuple:
        """解析阶段级 chat provider/model 覆盖

        优先级：phase_configs（API 运行时覆盖）> phase.llm_config（工作流定义）> 全局默认
        """
        cfg = phase_configs.get(phase_id, {})
        llm_cfg = phase.llm_config if phase and phase.llm_config else None
        p = (cfg.get("provider", "")
             or (llm_cfg.provider if llm_cfg and llm_cfg.adapter_type == "chat" else "")
             or chat_provider)
        m = (cfg.get("model", "")
             or (llm_cfg.model if llm_cfg and llm_cfg.adapter_type == "chat" else "")
             or chat_model)
        return p, m

    def _resolve_image(phase_id: str, phase: Optional[PhaseDefinition] = None) -> tuple:
        """解析阶段级 image provider/model 覆盖

        优先级：phase_configs（API 运行时覆盖）> phase.llm_config（工作流定义）> 全局默认
        """
        cfg = phase_configs.get(phase_id, {})
        llm_cfg = phase.llm_config if phase and phase.llm_config else None
        p = (cfg.get("provider", "")
             or (llm_cfg.provider if llm_cfg and llm_cfg.adapter_type == "image_generation" else "")
             or image_provider)
        m = (cfg.get("model", "")
             or (llm_cfg.model if llm_cfg and llm_cfg.adapter_type == "image_generation" else "")
             or image_model)
        return p, m

    async def exec_story(phase: PhaseDefinition, context: Dict[str, Any]) -> Dict[str, Any]:
        p, m = _resolve_chat("story", phase)
        if not p or is_mock_provider(p, m):
            return {"skipped": True, "detail": "未配置真实 LLM 供应商，编剧阶段跳过"}
        goal = goal_getter()
        content, _finish = await call_chat_completion(
            p, m,
            [
                {"role": "system", "content": (
                    "你是专业影视编剧。根据用户目标输出一份简洁的故事大纲："
                    "包含主题、3-6 个场景（每个场景一句话描述 + 时长建议）、整体情绪曲线。"
                    "只输出大纲文本，不要输出 JSON。"
                )},
                {"role": "user", "content": f"创作目标：{goal}\n\n当前工作台状态：\n{svc.build_agent_context('bound')}"},
            ],
            max_tokens=2048,
        )
        run_ctx["outline"] = content.strip()
        svc.add_chat_message("agent", f"【工作流·编剧】故事大纲：\n\n{run_ctx['outline']}")
        return {"detail": f"故事大纲已生成（{len(run_ctx['outline'])} 字）"}

    async def exec_storyboard(phase: PhaseDefinition, context: Dict[str, Any]) -> Dict[str, Any]:
        p, m = _resolve_chat("storyboard", phase)
        if not p or is_mock_provider(p, m):
            return {"skipped": True, "detail": "未配置真实 LLM 供应商，分镜拆解跳过"}
        goal = goal_getter()
        system = (
            STUDIO_ACTION_PROTOCOL_PROMPT.strip()
            + "\n\n当前工作台状态 JSON：\n" + svc.build_agent_context("bound")
        )
        user = (
            f"请根据以下故事大纲拆解关键元素与分镜，用 add_group 创建分组，"
            f"每个分组携带含可执行 prompt 的 draft。目标：{goal}\n\n大纲：\n"
            + (run_ctx["outline"] or "（无大纲，请直接根据目标拆解）")
        )
        content, _finish = await call_chat_completion(
            p, m,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=8192,
        )
        actions = executor.parse_actions_from_reply(content)
        actions = [a for a in actions if str(a.get("action", "")).lower() != "continue"]
        applied = executor.execute(actions)
        if applied == 0:
            raise GenerationError("LLM 未产出有效的 studio-actions（可能被截断或格式错误）")
        return {"detail": f"已新增 {applied} 个故事板分组/草稿"}

    async def exec_image(phase: PhaseDefinition, context: Dict[str, Any]) -> Dict[str, Any]:
        img_p, img_m = _resolve_image("image", phase)
        if not img_p or is_mock_provider(img_p, img_m):
            return {"skipped": True, "detail": "未配置真实生图供应商，关键帧生成跳过"}
        targets = []
        groups = svc.get_groups()
        for cat in (CAT_KEY_ELEMENTS, CAT_SHOTS):
            for group in groups.get(cat, []):
                for draft in group.get("drafts", []):
                    if draft.get("prompt") and not draft.get("imgUrl") and draft.get("mediaType") == "image":
                        targets.append(draft)
        targets = targets[:MAX_IMAGES_PER_RUN]
        if not targets:
            return {"detail": "没有待生成的关键帧（所有草稿已有图片）"}

        ok, failed_msgs = 0, []
        for draft in targets:
            try:
                url = await generate_image_via_provider(
                    img_p, img_m, draft["prompt"],
                    size=draft.get("size", "1280x720"),
                    aspect_ratio=draft.get("aspectRatio", "16:9"),
                )
                draft["imgUrl"] = url
                draft["tag"] = "已生成"
                svc.save()
                ok += 1
            except GenerationError as e:
                failed_msgs.append(str(e))
        if ok == 0:
            raise GenerationError("全部关键帧生成失败：" + "；".join(failed_msgs[:2]))
        detail = f"已生成 {ok}/{len(targets)} 张关键帧"
        if failed_msgs:
            detail += f"（{len(failed_msgs)} 张失败）"
        return {"detail": detail}

    async def exec_not_implemented(phase: PhaseDefinition, context: Dict[str, Any]) -> Dict[str, Any]:
        reasons = {
            "video": "真实视频供应商尚未接入服务端",
            "audio": "音频合成尚未接入服务端",
            "edit": "剪辑合成尚未接入服务端",
        }
        return {"skipped": True, "detail": reasons.get(phase.phase_id, "尚未实现") + "，跳过"}

    return {
        "story": exec_story,
        "storyboard": exec_storyboard,
        "image": exec_image,
        "video": exec_not_implemented,
        "audio": exec_not_implemented,
        "edit": exec_not_implemented,
    }


# ---------- 交互式引擎单例 ----------

_interactive_engine: Optional[WorkflowEngine] = None


def _find_first_provider(kind: str) -> tuple:
    """从 api_providers.json 找第一个可用的非 mock 供应商，返回 (provider_id, model)"""
    from src.video_agent.web.provider_config import load_api_providers, CLI_PROTOCOLS
    for p in load_api_providers():
        if not p.get("enabled", True):
            continue
        if p.get("protocol") == "mock":
            continue
        pid = p.get("id", "")
        if kind == "chat":
            models = p.get("chat_models", [])
            if models and (p.get("base_url") or p.get("protocol") in CLI_PROTOCOLS):
                return pid, models[0]
        elif kind == "image":
            models = p.get("image_models", [])
            if models:
                return pid, models[0]
    return "", ""


def _build_interactive_executors():
    """为交互式引擎构建真实执行器（使用配置中第一个可用供应商）"""
    svc = StateManager.get_instance()
    executor = StudioActionExecutor(svc)
    run_ctx: Dict[str, Any] = {"outline": ""}

    chat_provider, chat_model = _find_first_provider("chat")
    image_provider, image_model = _find_first_provider("image")

    return build_executors(
        svc, executor, run_ctx,
        chat_provider=chat_provider,
        chat_model=chat_model,
        image_provider=image_provider,
        image_model=image_model,
        goal_getter=lambda: svc.state_dict.get("user_goal", "") or svc.state_dict.get("project_name", ""),
    )


def get_interactive_engine() -> WorkflowEngine:
    """获取/创建交互式工作流引擎实例（带真实执行器）"""
    global _interactive_engine
    if _interactive_engine is None:
        executors = _build_interactive_executors()

        async def phase_executor(phase: PhaseDefinition, context: Dict[str, Any]):
            return await executors[phase.phase_id](phase, context)

        _interactive_engine = WorkflowEngine(build_workflow_definition(), phase_executor=phase_executor)
    return _interactive_engine


def reset_interactive_engine() -> None:
    """重置交互引擎单例（项目切换/新建/删除后调用）。

    引擎持有 completed_phases / failed_phases / _awaiting_confirmation 等运行态，
    不重置会把上一项目的进度污染到新项目（step 直接返回 done 或跳过阶段）。
    """
    global _interactive_engine
    if _interactive_engine is not None:
        logger.info("[Workflow] 项目变更，重置交互工作流引擎")
    _interactive_engine = None
