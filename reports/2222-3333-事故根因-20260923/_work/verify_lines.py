# -*- coding: utf-8 -*-
"""行号自检：核对 03 报告中引用的 (文件, 行号, 片段) 是否成立（只读）。"""
import io

CHECKS = [
    ("src/video_agent/tools/video/generate_video.py", 18, "image_url"),
    ("src/video_agent/tools/video/generate_video.py", 17, "class GenerateVideoParams"),
    ("src/video_agent/tools/storyboard_tools.py", 435, "media_type not in"),
    ("src/video_agent/tools/storyboard_tools.py", 457, "all_keyelements"),
    ("src/video_agent/tools/storyboard_tools.py", 50, "def _desc_before_summary"),
    ("src/video_agent/tools/storyboard_tools.py", 357, "class StoryboardDeleteGroupTool"),
    ("src/video_agent/state/storyboard_ops.py", 276, "def delete_draft"),
    ("src/video_agent/state/storyboard_ops.py", 319, "def append_draft"),
    ("src/video_agent/core/fc_tool_runner.py", 60, "PARALLEL_POOL_LIMIT"),
    ("src/video_agent/core/fc_tool_runner.py", 806, "_tool_fail_counts"),
    ("src/video_agent/core/fc_feedback.py", 79, "连续失败 2 次"),
    ("src/video_agent/core/fc_feedback.py", 448, "fail_count >= 2"),
    ("src/video_agent/core/subagent.py", 173, "STAGE_CARD_MEDIA: Dict"),
    ("src/video_agent/core/fc_gates.py", 381, "def card_media_gate"),
    ("src/video_agent/core/fc_gates.py", 403, "not allowed"),
    ("src/video_agent/core/fc_gates.py", 420, "else"),
    ("src/video_agent/state/models.py", 62, "media_type"),
    ("src/video_agent/state/models.py", 73, "img_url"),
    ("src/video_agent/state/models.py", 74, "video_url"),
    ("src/video_agent/state/models.py", 75, "audio_url"),
    ("src/video_agent/tools/document_tools.py", 657, "class ImageGenerateTool"),
    ("src/video_agent/tools/document_tools.py", 605, "parallel_safe"),
    ("src/video_agent/web/generation_channel.py", 129, "当前版本无真实音频文件生成调用"),
    ("src/video_agent/web/task_manager.py", 384, "def writeback_if_complete"),
    ("src/web/components/middle-panel/ParamControls.tsx", 108, "selectedType === 'shot'"),
    ("src/web/components/middle-panel/ParamControls.tsx", 121, "keyElement"),
    ("src/web/components/middle-panel/GenTypeTabs.tsx", 10, "video"),
    ("src/web/components/middle-panel/GenTypeTabs.tsx", 11, "audio"),
    ("src/web/components/middle-panel/MediaViewer.tsx", 155, "keyElement"),
    ("src/web/components/middle-panel/MediaViewer.tsx", 89, "accept"),
    ("src/web/components/left-panel/DraftCard.tsx", 92, "isVoiceCard"),
    ("src/web/lib/generate-actions.ts", 24, "关键元素"),
    ("src/web/lib/generate-actions.ts", 90, "分镜"),
    ("src/web/lib/generate-actions.ts", 169, "音频"),
    ("src/video_agent/core/planner.py", 393, "_apply_stage_card_media"),
    ("src/video_agent/core/provider_config.py", 227, "CAT_KEY_ELEMENTS"),
    ("src/video_agent/core/provider_config.py", 230, "CAT_SHOTS"),
    ("src/video_agent/core/provider_config.py", 237, "CAT_AUDIO_ITEMS"),
    ("prompts/planner/subagent.md", 70, "分批做"),
    ("prompts/planner/skill_runtime.md", 14, "思考同样分批"),
    ("src/video_agent/config.py", 132, "llm_output_limit"),
]

bad = 0
for path, line, frag in CHECKS:
    try:
        lines = io.open(path, encoding="utf-8").read().split("\n")
    except Exception as e:
        print("MISSING FILE", path, e)
        bad += 1
        continue
    text = lines[line - 1] if 0 < line <= len(lines) else "<OUT OF RANGE>"
    ok = frag in text
    if not ok:
        bad += 1
    print(("OK  " if ok else "BAD "), f"{path}:{line}", "|", text.strip()[:95])
print("\nBAD COUNT =", bad, "of", len(CHECKS))
