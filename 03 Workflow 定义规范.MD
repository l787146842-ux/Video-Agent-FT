# Video Agent v1 — Workflow 定义规范

> Workflow Engine 是 Agent Runtime 层的执行引擎，负责将 Planner 的计划拆解为可执行的阶段，按依赖关系调度，驱动整个视频生产流水线。
>
> 本文档中的 `$ref` 引用（如 `"$ref": "#/phase_definitions/story"`）为**示意性伪引用**，用于表达结构关系。实际实现中应替换为具体的 Phase 配置内联或由 Workflow 加载器解析。

---

## 一、Workflow 总览

### 1.1 六大阶段（Phase）

```
用户需求
  │
  ▼
┌──────────────────────────────────────────────────────────────┐
│                     Workflow Engine                          │
│                                                              │
│  ① Story ──▶ ② Storyboard ──▶ ③ Image ──▶ ④ Video           │
│                                    │                         │
│                                    ├──▶ ⑤ Audio（可并行）     │
│                                    │                         │
│                                    ▼                         │
│                                ⑥ Edit                        │
│                                    │                         │
│                                    ▼                         │
│                               最终输出                        │
└──────────────────────────────────────────────────────────────┘
```

| 阶段 | 输入 | 输出 | 依赖 |
|------|------|------|------|
| ① Story | `user_goal` | `StoryState` | 无 |
| ② Storyboard | `StoryState` | `StoryboardState` | ① |
| ③ Image | `StoryboardState.shots[]` | `AssetState[type=image]` | ② |
| ④ Video | `AssetState[type=image]` | `AssetState[type=video]` | ③ |
| ⑤ Audio | `StoryState` + `StoryboardState` | `AssetState[type=audio]` | ② （与③④可并行） |
| ⑥ Edit | 全部 `AssetState` | `TimelineState` + 最终视频文件 | ④ ⑤ |

### 1.2 核心原则

1. **声明式定义**：Workflow 用 JSON 声明阶段和依赖关系，Engine 负责调度执行
2. **状态驱动**：每个 Phase 从 State 读取输入，将结果写回 State（通过 StateManager）
3. **可恢复**：任何阶段失败后可从断点恢复，不需要重新执行已完成的阶段
4. **可并行**：无依赖关系的阶段自动并行执行（如 Image/Audio）
5. **可插拔**：每个阶段的具体实现由 Skill 提供，Workflow 只关心编排

---

## 二、Workflow 定义结构

### 2.1 WorkflowDefinition

```jsonc
{
  "workflow_id": "wf_video_standard",
  "name": "标准视频生产流水线",
  "version": "1.0.0",
  "description": "从用户需求到最终视频的完整生产流程",

  "triggers": {
    "on": "project_created",                  // 触发条件
    "condition": "project.status == 'planning'"
  },

  "context": {
    "project_id": "{{project_id}}",           // 运行时注入
    "max_parallel_tasks": 2,
    "timeout_seconds": 3600,
    "retry_policy": {
      "max_retries": 3,
      "backoff": "exponential",               // fixed | linear | exponential
      "base_delay_seconds": 5
    }
  },

  "phases": [
    { "$ref": "#/phase_definitions/story" },
    { "$ref": "#/phase_definitions/storyboard" },
    { "$ref": "#/phase_definitions/image" },
    { "$ref": "#/phase_definitions/video" },
    { "$ref": "#/phase_definitions/audio" },
    { "$ref": "#/phase_definitions/edit" }
  ],

  "on_complete": {
    "action": "notify_user",
    "params": { "message": "视频制作完成！" }
  },
  "on_failure": {
    "action": "pause_and_report",
    "params": { "escalate_to": "planner" }
  }
}
```

### 2.2 PhaseDefinition

每个阶段的完整定义：

```jsonc
{
  "phase_id": "phase_story",
  "name": "Story",
  "display_name": "剧本生成",
  "type": "skill_invoke",                // skill_invoke | parallel_batch | human_review | conditional

  "depends_on": [],                      // 依赖的 phase_id 列表

  "input_mapping": {
    "user_goal": "$.project.user_goal",
    "style_hint": "$.project.plan.style",
    "duration": "$.project.plan.duration_seconds"
  },

  "execution": {
    "skill": "story_generation",         // 调用的 Skill 名称
    "adapter": null,                     // 不需要外部适配器
    "params": {
      "language": "zh-CN",
      "max_scenes": 10
    }
  },

  "output_mapping": {
    "$.project.story": "{{skill_output}}"
  },

  "validation": {
    "rules": [
      { "check": "output.scenes.length > 0",    "error": "剧本必须包含至少一个场景" },
      { "check": "output.characters.length > 0", "error": "剧本必须包含至少一个角色" },
      { "check": "total_duration_within(0.8, 1.2, target)", "error": "场景总时长偏差超过20%" }
    ]
  },

  "review": {
    "required": false,                   // 是否需要用户确认
    "auto_approve_if": "preferences.auto_approve == true"
  },

  "retry": {
    "inherit": true,                     // 继承 workflow 级别策略
    "on_failure": "retry_with_feedback"  // retry | retry_with_feedback | skip | abort
  },

  "timeout_seconds": 120,

  "hooks": {
    "before": "log('开始生成剧本...')",
    "after": "log('剧本生成完成，共 {{output.scenes.length}} 个场景')"
  }
}
```

---

## 三、六大阶段详细定义

### 3.1 Phase: Story（剧本生成）

```jsonc
{
  "phase_id": "phase_story",
  "name": "Story",
  "display_name": "剧本生成",
  "type": "skill_invoke",
  "depends_on": [],

  "input_mapping": {
    "user_goal": "$.project.user_goal",
    "style": "$.project.plan.style",
    "duration_seconds": "$.project.plan.duration_seconds",
    "user_preferences": "$.project.metadata.preferences"
  },

  "execution": {
    "skill": "story_generation",
    "params": {
      "language": "zh-CN",
      "max_scenes": 10,
      "include_dialogue": true,
      "include_mood": true
    }
  },

  "output_mapping": {
    "$.project.story": "{{result}}",
    "$.project.story.status": "completed"
  },

  "validation": {
    "rules": [
      { "check": "result.scenes.length >= 1",                     "error": "STORY_NO_SCENES" },
      { "check": "result.characters.length >= 1",                 "error": "STORY_NO_CHARACTERS" },
      { "check": "sum(result.scenes[*].duration_seconds) > 0",    "error": "STORY_NO_DURATION" }
    ]
  },

  "review": {
    "required": true,
    "prompt": "请确认剧本是否符合你的预期，可以提出修改意见：",
    "max_revisions": 3,
    "auto_approve_if": "preferences.auto_approve == true"
  },

  "timeout_seconds": 120
}
```

### 3.2 Phase: Storyboard（分镜生成）

```jsonc
{
  "phase_id": "phase_storyboard",
  "name": "Storyboard",
  "display_name": "分镜脚本",
  "type": "skill_invoke",
  "depends_on": ["phase_story"],

  "input_mapping": {
    "story": "$.project.story",
    "resolution": "$.project.plan.resolution",
    "fps": "$.project.plan.fps",
    "style": "$.project.plan.style"
  },

  "execution": {
    "skill": "storyboard_generation",
    "params": {
      "shots_per_scene_range": [2, 6],
      "generate_visual_prompts": true,
      "generate_negative_prompts": true,
      "suggest_adapters": true,
      "prompt_optimization_skill": "prompt_enhance"
    }
  },

  "output_mapping": {
    "$.project.storyboard": "{{result}}"
  },

  "validation": {
    "rules": [
      { "check": "result.shots.length >= 1",                                        "error": "SB_NO_SHOTS" },
      { "check": "every(result.shots, s => s.visual_prompt.length > 10)",            "error": "SB_EMPTY_PROMPT" },
      { "check": "every(result.shots, s => s.shot_type in VALID_SHOT_TYPES)",        "error": "SB_INVALID_SHOT_TYPE" },
      { "check": "abs(sum(result.shots[*].duration_seconds) - plan.duration_seconds) / plan.duration_seconds < 0.2", "error": "SB_DURATION_MISMATCH" }
    ]
  },

  "review": {
    "required": true,
    "prompt": "分镜脚本已生成，请确认各镜头描述和提示词：",
    "max_revisions": 3,
    "auto_approve_if": "preferences.auto_approve == true"
  },

  "timeout_seconds": 180
}
```

### 3.3 Phase: Image（关键帧生成）

```jsonc
{
  "phase_id": "phase_image",
  "name": "Image",
  "display_name": "关键帧生成",
  "type": "parallel_batch",
  "depends_on": ["phase_storyboard"],

  "batch_source": "$.project.storyboard.shots",
  "batch_key": "shot_id",
  "max_parallel": "{{context.max_parallel_tasks}}",

  "per_item": {
    "input_mapping": {
      "prompt": "{{item.visual_prompt}}",
      "negative_prompt": "{{item.negative_prompt}}",
      "width": "{{plan.resolution.split('x')[0]}}",
      "height": "{{plan.resolution.split('x')[1]}}",
      "adapter": "{{item.generation_config.image_adapter}}",
      "seed": "{{item.generation_config.seed}}",
      "guidance_scale": "{{item.generation_config.guidance_scale}}",
      "steps": "{{item.generation_config.steps}}"
    },

    "execution": {
      "skill": "image_generation",
      "adapter_selection": {
        "primary": "{{item.generation_config.image_adapter}}",
        "fallback": ["flux", "comfyui", "sdxl"]
      }
    },

    "output_mapping": {
      "$.project.assets.assets[+]": {
        "asset_id": "{{generated_asset_id}}",
        "type": "image",
        "source_shot_id": "{{item.shot_id}}",
        "file_path": "{{output.file_path}}",
        "adapter_used": "{{output.adapter_used}}",
        "generation_params": "{{output.params}}",
        "status": "ready"
      },
      "$.project.storyboard.shots[shot_id={{item.shot_id}}].image_asset_id": "{{generated_asset_id}}",
      "$.project.storyboard.shots[shot_id={{item.shot_id}}].status": "image_ready"
    },

    "validation": {
      "rules": [
        { "check": "output.file_exists == true",   "error": "IMG_FILE_MISSING" },
        { "check": "output.width == expected_width", "error": "IMG_WRONG_SIZE" }
      ]
    },

    "on_item_failure": {
      "action": "retry_with_fallback",
      "fallback_adapter_order": ["flux", "comfyui", "sdxl"],
      "max_retries": 3
    }
  },

  "review": {
    "required": true,
    "prompt": "关键帧已生成，请逐张确认。不满意的可标记重新生成：",
    "allow_selective_retry": true,
    "auto_approve_if": "preferences.auto_approve == true"
  },

  "timeout_seconds": 600
}
```

### 3.4 Phase: Video（图生视频）

```jsonc
{
  "phase_id": "phase_video",
  "name": "Video",
  "display_name": "视频片段生成",
  "type": "parallel_batch",
  "depends_on": ["phase_image"],

  "batch_source": "$.project.storyboard.shots[?status=='image_ready']",
  "batch_key": "shot_id",
  "max_parallel": "{{context.max_parallel_tasks}}",

  "per_item": {
    "input_mapping": {
      "image_asset_id": "{{item.image_asset_id}}",
      "image_path": "$.project.assets.assets[asset_id={{item.image_asset_id}}].file_path",
      "prompt": "{{item.visual_prompt}}",
      "duration_seconds": "{{item.duration_seconds}}",
      "camera_movement": "{{item.camera_movement}}",
      "adapter": "{{item.generation_config.video_adapter}}"
    },

    "execution": {
      "skill": "video_generation",
      "adapter_selection": {
        "primary": "{{item.generation_config.video_adapter}}",
        "fallback": ["kling", "seedance", "hunyuan"]
      },
      "params": {
        "motion_strength": 0.7,
        "consistency_weight": 0.8
      }
    },

    "output_mapping": {
      "$.project.assets.assets[+]": {
        "asset_id": "{{generated_asset_id}}",
        "type": "video",
        "source_shot_id": "{{item.shot_id}}",
        "file_path": "{{output.file_path}}",
        "duration_seconds": "{{output.duration_seconds}}",
        "adapter_used": "{{output.adapter_used}}",
        "status": "ready"
      },
      "$.project.storyboard.shots[shot_id={{item.shot_id}}].video_asset_id": "{{generated_asset_id}}",
      "$.project.storyboard.shots[shot_id={{item.shot_id}}].status": "video_ready"
    },

    "on_item_failure": {
      "action": "retry_with_fallback",
      "fallback_adapter_order": ["kling", "seedance", "hunyuan"],
      "max_retries": 3
    }
  },

  "review": {
    "required": true,
    "prompt": "视频片段已生成，请确认运动效果和画面质量：",
    "allow_selective_retry": true,
    "auto_approve_if": "preferences.auto_approve == true"
  },

  "timeout_seconds": 1200
}
```

### 3.5 Phase: Audio（音频生成）

```jsonc
{
  "phase_id": "phase_audio",
  "name": "Audio",
  "display_name": "音频生成",
  "type": "parallel_batch",
  "depends_on": ["phase_storyboard"],          // 注意：不依赖 Image/Video，可并行

  "batch_source": [
    {
      "type": "bgm",
      "source": "$.project.story",
      "description": "根据剧本整体氛围生成背景音乐"
    },
    {
      "type": "sfx",
      "source": "$.project.storyboard.shots[?audio_cue != null]",
      "description": "根据分镜的 audio_cue 生成音效"
    },
    {
      "type": "dialogue",
      "source": "$.project.story.scenes[?dialogue.length > 0]",
      "description": "根据对白生成 TTS 语音"
    }
  ],
  "max_parallel": "{{context.max_parallel_tasks}}",

  "per_item": {
    "execution_by_type": {
      "bgm": {
        "skill": "bgm_generation",
        "adapter_selection": {
          "primary": "minimax",
          "fallback": ["suno", "stable_audio"]    // 补充备选供应商
        },
        "input_mapping": {
          "mood": "{{story.scenes[0].mood}}",
          "genre": "{{story.genre}}",
          "duration_seconds": "{{plan.duration_seconds}}"
        }
      },
      "sfx": {
        "skill": "sfx_generation",
        "adapter_selection": {
          "primary": "minimax",
          "fallback": ["foley"]
        },
        "input_mapping": {
          "description": "{{item.audio_cue}}",
          "duration_seconds": "{{item.duration_seconds}}"
        }
      },
      "dialogue": {
        "skill": "tts_generation",
        "adapter_selection": {
          "primary": "minimax",
          "fallback": ["rvc"]
        },
        "input_mapping": {
          "text": "{{item.dialogue[*].line}}",
          "character": "{{item.dialogue[*].character}}",
          "emotion": "{{item.dialogue[*].emotion}}"
        }
      }
    },

    "output_mapping": {
      "$.project.assets.assets[+]": {
        "asset_id": "{{generated_asset_id}}",
        "type": "audio",
        "category": "{{item_type}}",
        "source_shot_id": "{{item.shot_id || null}}",
        "file_path": "{{output.file_path}}",
        "duration_seconds": "{{output.duration_seconds}}",
        "adapter_used": "{{output.adapter_used}}",
        "status": "ready"
      }
    },

    "on_item_failure": {
      "action": "retry",
      "max_retries": 2
    }
  },

  "review": {
    "required": false,
    "auto_approve_if": "true"
  },

  "timeout_seconds": 600
}
```

### 3.6 Phase: Edit（合成剪辑）

```jsonc
{
  "phase_id": "phase_edit",
  "name": "Edit",
  "display_name": "合成剪辑",
  "type": "skill_invoke",
  "depends_on": ["phase_video", "phase_audio"],    // 等待视频和音频都完成

  "input_mapping": {
    "storyboard": "$.project.storyboard",
    "video_assets": "$.project.assets.assets[?type=='video' && status=='ready']",
    "audio_assets": "$.project.assets.assets[?type=='audio' && status=='ready']",
    "export_config": "$.project.timeline.export_config"
  },

  "execution": {
    "skill": "video_editing",
    "adapter_selection": {
      "primary": "premiere",
      "fallback": ["jianying", "blender"]     // 剪映、Blender
    },
    "params": {
      "auto_transition": true,
      "auto_color_grade": true,
      "add_subtitles": true,
      "subtitle_style": "default"
    }
  },

  "sub_steps": [
    {
      "step": "assemble_timeline",
      "description": "按分镜顺序排列视频片段到时间线",
      "output": "timeline_draft"
    },
    {
      "step": "add_transitions",
      "description": "根据分镜定义添加转场效果",
      "input": "timeline_draft",
      "output": "timeline_with_transitions"
    },
    {
      "step": "mix_audio",
      "description": "混音：BGM + 音效 + 对白，调整音量平衡",
      "input": "timeline_with_transitions",
      "output": "timeline_with_audio"
    },
    {
      "step": "add_subtitles",
      "description": "根据对白时间轴添加字幕",
      "input": "timeline_with_audio",
      "output": "timeline_final"
    },
    {
      "step": "render_export",
      "description": "渲染导出最终视频文件",
      "input": "timeline_final",
      "output": "final_video"
    }
  ],

  "output_mapping": {
    "$.project.timeline": "{{result.timeline}}",
    "$.project.timeline.status": "completed",
    "$.project.assets.assets[+]": {
      "asset_id": "{{result.final_asset_id}}",
      "type": "project_file",
      "file_path": "{{result.output_path}}",
      "status": "ready"
    }
  },

  "review": {
    "required": true,
    "prompt": "最终视频已生成，请预览确认：",
    "allow_revision": true,
    "auto_approve_if": "false"
  },

  "timeout_seconds": 1800
}
```

---

## 四、Workflow 执行引擎规范

### 4.1 执行模型

```
          Workflow Engine
               │
       ┌───────┴───────┐
       │   Scheduler    │
       │   (调度器)     │
       └───────┬───────┘
               │
    ┌──────────┼──────────┐
    ▼          ▼          ▼
 Phase A    Phase B    Phase C     ← 按依赖关系并行/串行
    │          │          │
    ▼          ▼          ▼
 Executor  Executor  Executor     ← 每个 Phase 一个执行器
    │          │          │
    ▼          ▼          ▼
  Skill      Skill      Skill     ← 实际能力调用
    │          │          │
    ▼          ▼          ▼
 Adapter   Adapter    Adapter     ← 外部 API 调用
```

### 4.2 调度算法

```python
# 伪代码：Workflow Scheduler 核心逻辑

def run_workflow(workflow_def, project_state):
    phases = topological_sort(workflow_def.phases)    # 按依赖拓扑排序
    completed = set()
    failed_fatal = set()
    running = {}

    while completed | failed_fatal != set(all_phase_ids):
        # 找出所有依赖已满足、尚未启动的阶段
        ready = [
            p for p in phases
            if p.phase_id not in completed
            and p.phase_id not in failed_fatal
            and p.phase_id not in running
            and all(dep in completed for dep in p.depends_on)
        ]

        # 如果没有可启动阶段且没有运行中阶段，说明存在不可恢复的阻塞
        if not ready and not running:
            trigger_on_failure(workflow_def, reason="所有剩余阶段被失败的依赖阻塞")
            break

        # 启动就绪阶段
        for phase in ready:
            running[phase.phase_id] = execute_phase_async(phase, project_state)
            state_manager.update(f"plan.steps[{phase.phase_id}].status", "running")

        # 等待任一阶段完成
        done_id, result = await wait_any(running)
        del running[done_id]

        if result.success:
            completed.add(done_id)
            state_manager.update(f"plan.steps[{done_id}].status", "completed")
            apply_output_mapping(result, workflow_def.phases[done_id])
        else:
            outcome = handle_failure(done_id, result, workflow_def)
            if outcome == "fatal":
                failed_fatal.add(done_id)
                state_manager.update(f"plan.steps[{done_id}].status", "failed")
            # outcome == "retry" 时，handle_failure 内部已重新入队到 running

    if not failed_fatal:
        trigger_on_complete(workflow_def)
    else:
        trigger_on_failure(workflow_def, failed_phases=failed_fatal)
```

### 4.3 Phase 类型说明

| 类型 | 说明 | 使用场景 |
|------|------|---------|
| `skill_invoke` | 调用单个 Skill 完成 | Story、Storyboard、Edit |
| `parallel_batch` | 对集合中每个元素并行执行 Skill | Image、Video、Audio |
| `human_review` | 暂停等待用户确认/修改 | 任何阶段的 review 环节 |
| `conditional` | 根据条件选择不同执行路径 | 高级流程控制 |

### 4.4 parallel_batch 执行细节

```
shots = [shot_001, shot_002, shot_003, shot_004, shot_005]
max_parallel = 2

执行时序：
t0:  [shot_001 ▶ running]  [shot_002 ▶ running]   shot_003 waiting   shot_004 waiting   shot_005 waiting
t1:  [shot_001 ✓ done]     [shot_002 ▶ running]   [shot_003 ▶ running]  shot_004 waiting   shot_005 waiting
t2:  [shot_001 ✓ done]     [shot_002 ✓ done]      [shot_003 ▶ running]  [shot_004 ▶ running]  shot_005 waiting
t3:  [shot_001 ✓ done]     [shot_002 ✓ done]      [shot_003 ✓ done]     [shot_004 ▶ running]  [shot_005 ▶ running]
t4:  全部完成
```

---

## 五、错误处理与恢复策略

### 5.1 故障处理层次

```
Level 1: 任务重试（同 Adapter）
    ↓ 失败
Level 2: Adapter 降级（换备选 Adapter）
    ↓ 失败
Level 3: Planner 介入（调整策略，如降低分辨率、简化 Prompt）
    ↓ 失败
Level 4: 用户介入（暂停流程，请求人工决策）
```

### 5.2 重试策略配置

```jsonc
{
  "retry_policy": {
    "max_retries": 3,
    "backoff": "exponential",
    "base_delay_seconds": 5,          // 重试间隔：5s → 10s → 20s

    "retryable_errors": [
      "ADAPTER_TIMEOUT",
      "ADAPTER_RATE_LIMIT",
      "ADAPTER_INVALID_RESPONSE"
    ],
    "non_retryable_errors": [
      "ADAPTER_AUTH_FAIL",
      "GENERATION_NSFW",
      "RESOURCE_EXHAUSTED"
    ]
  }
}
```

### 5.3 Adapter 降级策略

```jsonc
{
  "fallback_chains": {
    "image": {
      "chain": ["flux", "comfyui", "sdxl"],
      "strategy": "next_on_failure"           // 当前失败才切换下一个
    },
    "video": {
      "chain": ["kling", "seedance", "hunyuan"],
      "strategy": "next_on_failure"
    },
    "audio": {
      "chain": ["minimax", "suno", "stable_audio"],
      "strategy": "next_on_failure"
    },
    "edit": {
      "chain": ["premiere", "jianying", "blender"],
      "strategy": "next_on_failure"
    }
  }
}
```

### 5.4 断点恢复

Workflow 支持从任意断点恢复：

```jsonc
{
  "resume_config": {
    "workflow_id": "wf_video_standard",
    "project_id": "proj_20260725_abc123",
    "resume_from": "phase_image",             // 从这个阶段开始恢复
    "skip_completed_items": true,             // 跳过 batch 中已完成的 item
    "reuse_approved_assets": true             // 复用已被用户确认的资产
  }
}
```

恢复逻辑：

```
1. 读取 ProjectState 快照
2. 检查每个 Phase 的 status：
   - completed → 跳过
   - running / failed → 标记为 resume 目标
   - pending → 保持
3. 对 parallel_batch 类 Phase：
   - 已完成的 item → 跳过
   - 失败 / 未开始的 item → 重新执行
4. 恢复调度循环
```

---

## 六、用户交互节点（Human-in-the-Loop）

### 6.1 Review 节点

每个 Phase 可配置 `review` 节点，暂停执行等待用户确认。

```jsonc
{
  "review": {
    "required": true,
    "prompt": "请确认生成结果：",
    "options": [
      { "action": "approve",   "label": "确认通过" },
      { "action": "retry",     "label": "重新生成",    "params": { "feedback": "{{user_input}}" } },
      { "action": "edit",      "label": "手动修改",    "params": { "field": "{{user_selected}}" } },
      { "action": "skip",      "label": "跳过此项" },
      { "action": "abort",     "label": "终止流程" }
    ],
    "timeout_seconds\": 86400,             // 24小时无响应自动暂停（非自动通过）
    "timeout_action": "pause",             // pause | auto_approve — 默认暂停流程并通知用户
    "max_revisions": 3,                   // 最多修改 3 轮
    "auto_approve_if": "preferences.auto_approve == true"
  }
}
```

### 6.2 Review 流程

```
Phase 执行完成
      │
      ▼
  review.required == true ?
      │
   ┌──┴──┐
   │ Yes  │  No ──▶ 继续下一 Phase
   │      │
   ▼      
 展示结果给用户
      │
      ▼
 用户选择操作
      │
 ┌────┼────┬────┐
 ▼    ▼    ▼    ▼
approve retry edit abort
 │    │    │    │
 │    │    │    └──▶ 终止 Workflow
 │    │    └──▶ 修改参数 → 重新执行当前 Phase
 │    └──▶ 附加反馈 → 重新执行当前 Phase
 └──▶ 继续下一 Phase
```

### 6.3 反馈驱动重试

用户 retry 时可附加反馈，传递给 Skill 优化生成：

```jsonc
{
  "retry_with_feedback": {
    "shot_id": "shot_003",
    "feedback": "颜色太暗了，需要更明亮的光线",
    "action": "merge_into_prompt",
    "original_prompt": "dark corridor...",
    "enhanced_prompt": "dark corridor with bright overhead lighting..."
  }
}
```

---

## 七、Workflow 变体

### 7.1 标准流程（默认）

```
Story → Storyboard →  Image  → Video → Edit
                   └→ Audio ─────────┘
```

### 7.2 快速预览流程

跳过 Audio，降低分辨率，用于快速验证视觉方向。

```jsonc
{
  "workflow_id": "wf_quick_preview",
  "name": "快速预览",
  "phases": [
    { "phase_id": "phase_story",      "depends_on": [] },
    { "phase_id": "phase_storyboard", "depends_on": ["phase_story"] },
    {
      "phase_id": "phase_image_preview",
      "depends_on": ["phase_storyboard"],
      "overrides": {
        "execution.params.resolution": "512x288",
        "execution.params.steps": 15
      }
    }
  ]
}
```

### 7.3 仅音频流程

只生成音频（BGM + 音效 + 配音），用于已有视频素材的场景。

```jsonc
{
  "workflow_id": "wf_audio_only",
  "name": "仅音频",
  "phases": [
    { "phase_id": "phase_story",      "depends_on": [] },
    { "phase_id": "phase_audio",      "depends_on": ["phase_story"] }
  ]
}
```

### 7.4 单镜头重做流程

重新生成单个镜头的 Image + Video，不影响其他镜头。

```jsonc
{
  "workflow_id": "wf_reshoot",
  "name": "单镜头重做",
  "context": {
    "target_shot_id": "{{shot_id}}"
  },
  "phases": [
    {
      "phase_id": "phase_image_reshoot",
      "type": "skill_invoke",
      "depends_on": [],
      "execution": {
        "skill": "image_generation",
        "input_filter": "shot_id == '{{context.target_shot_id}}'"
      }
    },
    {
      "phase_id": "phase_video_reshoot",
      "type": "skill_invoke",
      "depends_on": ["phase_image_reshoot"],
      "execution": {
        "skill": "video_generation",
        "input_filter": "shot_id == '{{context.target_shot_id}}'"
      }
    }
  ]
}
```

---

## 八、Workflow 与其他模块的关系

```
┌─────────┐
│ Planner │──── 创建 Workflow 实例，决定使用哪个 Workflow 变体
└────┬────┘
     │ 启动
     ▼
┌──────────────┐
│   Workflow   │──── 读取 State 获取输入
│   Engine     │──── 调用 Skill 执行具体能力
│              │──── 通过 StateManager 写回结果
│              │──── 遇到错误上报 Planner 决策
└──────┬───────┘
       │
  ┌────┼────┬──────────┐
  ▼    ▼    ▼          ▼
Skill  Tool  Adapter   StateManager
系统   Manager         │
       │               │
       ▼               ▼
  外部 API          State JSON
```

**职责边界**

| 模块 | 职责 | 不做什么 |
|------|------|---------|
| **Planner** | 决定用哪个 Workflow、传什么参数 | 不直接调用 Adapter |
| **Workflow Engine** | 编排 Phase 执行顺序、管理并行/重试 | 不做具体生成逻辑 |
| **Skill** | 封装单个能力的完整逻辑（Prompt构建 + 调用 + 后处理） | 不管其他 Skill 的执行顺序 |
| **Adapter** | 统一接口调用外部 API | 不做业务逻辑判断 |
| **StateManager** | 状态的唯一写入点 | 不做调度/执行 |

---

## 九、Workflow 事件系统

### 9.1 事件定义

Workflow 执行过程中产生的事件，供 UI / 日志 / Planner 消费。

| 事件 | 触发时机 | 载荷 |
|------|---------|------|
| `workflow.started` | Workflow 开始执行 | `{ workflow_id, project_id }` |
| `workflow.completed` | 所有 Phase 完成 | `{ workflow_id, duration_ms }` |
| `workflow.failed` | Workflow 不可恢复地失败 | `{ workflow_id, error }` |
| `phase.started` | Phase 开始 | `{ phase_id, phase_name }` |
| `phase.completed` | Phase 完成 | `{ phase_id, output_summary }` |
| `phase.failed` | Phase 失败 | `{ phase_id, error, retry_count }` |
| `task.progress` | 生成进度更新 | `{ task_id, progress, shot_id }` |
| `review.requested` | 等待用户确认 | `{ phase_id, review_data }` |
| `review.responded` | 用户已响应 | `{ phase_id, action, feedback }` |
| `adapter.fallback` | Adapter 降级 | `{ from_adapter, to_adapter, reason }` |
| `cost.updated` | 费用变更 | `{ api_call, cost_usd, total_cost }` |

### 9.2 事件流示例

```
[10:00:00] workflow.started       { wf_video_standard, proj_abc123 }
[10:00:01] phase.started          { phase_story, "剧本生成" }
[10:00:45] phase.completed        { phase_story, "3 scenes, 2 characters" }
[10:00:45] review.requested       { phase_story, "请确认剧本..." }
[10:02:30] review.responded       { phase_story, "approve" }
[10:02:31] phase.started          { phase_storyboard, "分镜脚本" }
[10:03:15] phase.completed        { phase_storyboard, "8 shots" }
[10:03:15] review.requested       { phase_storyboard, "请确认分镜..." }
[10:05:00] review.responded       { phase_storyboard, "approve" }
[10:05:01] phase.started          { phase_image, "关键帧生成" }
[10:05:01] phase.started          { phase_audio, "音频生成" }         ← 并行启动
[10:05:01] task.progress          { task_001, 0.0, shot_001 }
[10:05:20] task.progress          { task_001, 0.5, shot_001 }
[10:05:40] task.progress          { task_001, 1.0, shot_001 }
[10:05:41] adapter.fallback       { "seedance", "kling", "timeout" }  ← 自动降级
...
[10:15:00] phase.completed        { phase_image, "8 images ready" }
[10:16:00] phase.completed        { phase_audio, "1 bgm + 5 sfx" }
[10:16:01] phase.started          { phase_video, "视频片段生成" }
...
[10:25:00] phase.completed        { phase_video, "8 clips" }
[10:25:01] phase.started          { phase_edit, "合成剪辑" }
[10:28:00] phase.completed        { phase_edit, "final_output.mp4" }
[10:28:00] review.requested       { phase_edit, "请确认最终视频" }
[10:30:00] review.responded       { phase_edit, "approve" }
[10:30:00] workflow.completed     { wf_video_standard, 1800000ms }
[10:30:00] cost.updated           { total: 12 calls, $2.45 }
```

---

## 十、设计要点总结

| 设计决策 | 理由 |
|---------|------|
| 声明式 Phase 定义 + 引擎调度 | Planner 只需选择 Workflow 变体，不关心执行细节 |
| `depends_on` 依赖图 | 自动推导并行机会（Audio 与 Image/Video 并行） |
| `parallel_batch` 类型 | 多 Shot 并行生成，充分利用并发，但受 `max_parallel` 控制 |
| 三级 fallback（重试→换 Adapter→Planner 介入） | 最大化自动恢复能力，减少用户干预 |
| Review 节点可选 + `auto_approve` | 适配不同用户偏好：全自动 vs 逐步确认 |
| `input_mapping` / `output_mapping` 用 JSONPath | 解耦 Phase 和 State 结构，Phase 不直接操作 State |
| Workflow 变体（标准/快速预览/仅音频/单镜头重做） | 覆盖常见场景，Planner 按需选择 |
| 事件系统 | UI 实时展示进度，Planner 可订阅事件做动态决策 |
