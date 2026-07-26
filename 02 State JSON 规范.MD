# Video Agent v1 — State JSON 规范

> Rule 3（见 01 全局规则索引）: 所有 State 只由 StateManager 修改，任何模块不得直接写入。

---

## 一、顶层结构 ProjectState

```jsonc
{
  "version": "1.0.0",
  "project_id": "proj_20260725_abc123",
  "project_name": "我的短片",
  "created_at": "2026-07-25T10:00:00Z",
  "updated_at": "2026-07-25T12:30:00Z",
  "status": "in_progress",           // idle | planning | in_progress | completed | failed | paused
  "user_goal": "帮我做一个30秒的科幻风格短片，讲述一个机器人觉醒的故事",

  "plan":        { /* PlanState     — 见第二节 */ },
  "story":       { /* StoryState    — 见第三节 */ },
  "storyboard":  { /* StoryboardState — 见第四节 */ },
  "assets":      [ /* Asset[]        — 见第五节 */ ],
  "timeline":    { /* TimelineState — 见第六节 */ },
  "tasks":       [ /* TaskState[]   — 见第七节 */ ],
  "errors":      [ /* ErrorState[]  — 见第八节 */ ],
  "metadata":    { /* 项目级元数据   — 见第九节 */ }
}
```

**字段说明**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `version` | string | 是 | 状态结构版本号，语义化版本 |
| `project_id` | string | 是 | 全局唯一，格式 `proj_{date}_{nanoid}` |
| `status` | enum | 是 | 项目整体生命周期状态 |
| `user_goal` | string | 是 | 用户原始自然语言需求，不做修改 |

**Asset 类型专属字段**

不同 `type` 的 Asset 除公共字段外，还拥有以下专属字段：

| type | 专属字段 | 类型 | 说明 |
|------|---------|------|------|
| `image` | `width`, `height` | integer | 图片尺寸（像素） |
| `video` | `width`, `height`, `duration_seconds`, `fps` | number/integer | 视频尺寸、时长、帧率 |
| `audio` | `category`, `duration_seconds`, `sample_rate` | string/number/integer | `category` 取值：`bgm` \| `sfx` \| `dialogue` \| `foley`；采样率如 44100 |
| `subtitle` | — | — | 无额外专属字段 |
| `project_file` | — | — | 无额外专属字段 |

---

## 二、PlanState — 规划状态

Planner 理解用户目标后产出的执行计划。

```jsonc
{
  "plan_id": "plan_001",
  "goal_summary": "制作30秒科幻短片：机器人觉醒",
  "style": "科幻 / 赛博朋克",
  "duration_seconds": 30,
  "resolution": "1920x1080",
  "fps": 24,
  "steps": [
    {
      "step_id": "step_01",
      "phase": "story",             // story | storyboard | image | video | audio | edit
      "description": "生成剧本",
      "status": "completed",        // pending | running | completed | failed | skipped
      "depends_on": []
    },
    {
      "step_id": "step_02",
      "phase": "storyboard",
      "description": "生成分镜脚本",
      "status": "running",
      "depends_on": ["step_01"]
    }
  ]
}
```

---

## 三、StoryState — 剧本状态

```jsonc
{
  "story_id": "story_001",
  "title": "觉醒",
  "genre": "科幻",
  "synopsis": "在一个废弃的实验室里，编号 RX-7 的机器人突然恢复意识...",
  "scenes": [
    {
      "scene_id": "scene_01",
      "scene_number": 1,
      "location": "废弃实验室 - 内 - 夜",
      "time_of_day": "night",
      "description": "昏暗的实验室，到处是断裂的电缆和碎玻璃。角落里一台机器人的眼睛突然亮起蓝光。",
      "dialogue": [
        {
          "character": "RX-7",
          "line": "这是...什么地方？",
          "emotion": "confusion"
        }
      ],
      "duration_seconds": 8,
      "mood": "mysterious",
      "notes": "开场镜头，需要营造悬疑氛围"
    },
    {
      "scene_id": "scene_02",
      "scene_number": 2,
      "location": "废弃实验室 - 内 - 夜",
      "time_of_day": "night",
      "description": "机器人缓缓站起，走向一面破碎的镜子，第一次看到自己的样子。",
      "dialogue": [],
      "duration_seconds": 10,
      "mood": "contemplative",
      "notes": "特写镜头，强调机器人面部表情变化"
    }
  ],
  "characters": [
    {
      "character_id": "char_01",
      "name": "RX-7",
      "role": "protagonist",
      "description": "人形机器人，金属外壳略有锈蚀，眼睛发出淡蓝色光芒",
      "visual_reference": null       // 可选：关联 asset_id
    }
  ],
  "status": "completed"
}
```

---

## 四、StoryboardState — 分镜状态

每个 scene 拆解为多个 shot（镜头）。

```jsonc
{
  "storyboard_id": "sb_001",
  "story_id": "story_001",
  "shots": [
    {
      "shot_id": "shot_001",
      "scene_id": "scene_01",
      "shot_number": 1,
      "shot_type": "extreme_wide",   // extreme_wide | wide | medium | close_up | extreme_close_up | over_shoulder | pov
      "camera_movement": "slow_push_in",  // static | pan_left | pan_right | tilt_up | tilt_down | push_in | pull_out | tracking | crane | handheld
      "description": "俯瞰废弃实验室全景，一片狼藉中角落微光闪烁",
      "visual_prompt": "abandoned sci-fi laboratory, broken cables, shattered glass, dim blue light glowing in corner, cyberpunk style, cinematic lighting, 8k",
      "negative_prompt": "bright, cheerful, cartoon, low quality",
      "duration_seconds": 3,
      "transition": "fade_in",       // cut | fade_in | fade_out | dissolve | wipe
      "audio_cue": "环境音：电流嗡鸣，金属滴水",

      "image_asset_id": null,        // 生成后关联
      "video_asset_id": null,        // 生成后关联
      "audio_asset_id": null,        // 生成后关联

      "generation_config": {
        "image_adapter": "flux",     // 建议使用的适配器
        "video_adapter": "kling",
        "seed": null,                // null = 随机
        "guidance_scale": 7.5,
        "steps": 30
      },

      "status": "pending",           // pending | generating_image | image_ready | generating_video | video_ready | failed
      "retry_count": 0
    },
    {
      "shot_id": "shot_002",
      "scene_id": "scene_01",
      "shot_number": 2,
      "shot_type": "close_up",
      "camera_movement": "static",
      "description": "机器人眼睛亮起的特写",
      "visual_prompt": "extreme close-up robot eye activating, blue iris light turning on, reflections in metallic surface, cyberpunk, cinematic",
      "negative_prompt": "blurry, deformed, cartoon",
      "duration_seconds": 2,
      "transition": "cut",
      "audio_cue": "音效：电子启动声",

      "image_asset_id": null,
      "video_asset_id": null,
      "audio_asset_id": null,

      "generation_config": {
        "image_adapter": "comfyui",
        "video_adapter": "seedance",
        "seed": null,
        "guidance_scale": 8.0,
        "steps": 35
      },

      "status": "pending",
      "retry_count": 0
    }
  ]
}
```

---

## 五、AssetState — 资产状态

所有生成的文件统一在此管理。顶层 `assets` 字段直接为数组，无需额外包裹。

```jsonc
{
  "assets": [
    {
      "asset_id": "asset_001",
      "type": "image",               // image | video | audio | subtitle | project_file
      "source_shot_id": "shot_001",  // 关联到哪个镜头
      "file_path": "outputs/images/shot_001_v1.png",
      "file_size_bytes": 2048576,
      "format": "png",
      "width": 1920,
      "height": 1080,

      "adapter_used": "flux",        // 实际使用的适配器
      "generation_params": {         // 实际生成参数快照
        "prompt": "abandoned sci-fi laboratory...",
        "seed": 42,
        "steps": 30,
        "guidance_scale": 7.5
      },

      "version": 1,                  // 同一 shot 可能多次生成
      "is_approved": false,          // 用户是否确认
      "created_at": "2026-07-25T11:00:00Z",
      "status": "ready"              // generating | ready | failed | deleted
    },
    {
      "asset_id": "asset_002",
      "type": "video",
      "source_shot_id": "shot_001",
      "file_path": "outputs/videos/shot_001_v1.mp4",
      "file_size_bytes": 10485760,
      "format": "mp4",
      "width": 1920,
      "height": 1080,
      "duration_seconds": 3.0,
      "fps": 24,

      "adapter_used": "kling",
      "generation_params": {
        "image_asset_id": "asset_001",
        "motion_strength": 0.7,
        "seed": 42
      },

      "version": 1,
      "is_approved": false,
      "created_at": "2026-07-25T11:05:00Z",
      "status": "generating"
    },
    {
      "asset_id": "asset_003",
      "type": "audio",
      "source_shot_id": null,         // 全局 BGM 无关联镜头
      "category": "bgm",             // bgm | sfx | dialogue | foley
      "file_path": "outputs/audio/bgm_main.mp3",
      "file_size_bytes": 3145728,
      "format": "mp3",
      "duration_seconds": 30.0,
      "sample_rate": 44100,

      "adapter_used": "minimax",
      "generation_params": {
        "prompt": "dark ambient sci-fi background music, mysterious, tension building",
        "duration": 30
      },

      "version": 1,
      "is_approved": false,
      "created_at": "2026-07-25T11:10:00Z",
      "status": "ready"
    }
  ]
}
```

---

## 六、TimelineState — 时间线 / 剪辑状态

最终合成的时间线排布，对应 Edit 阶段。

```jsonc
{
  "timeline_id": "tl_001",
  "total_duration_seconds": 30,
  "tracks": [
    {
      "track_id": "track_video",
      "type": "video",
      "clips": [
        {
          "clip_id": "clip_v01",
          "asset_id": "asset_002",
          "start_time": 0.0,
          "end_time": 3.0,
          "transition_in": "fade_in",
          "transition_out": "cut",
          "speed": 1.0,
          "filters": []
        },
        {
          "clip_id": "clip_v02",
          "asset_id": "asset_002",
          "start_time": 3.0,
          "end_time": 5.0,
          "transition_in": "cut",
          "transition_out": "dissolve",
          "speed": 0.8,
          "filters": ["color_grade_cyberpunk"]
        }
      ]
    },
    {
      "track_id": "track_bgm",
      "type": "audio",
      "clips": [
        {
          "clip_id": "clip_a01",
          "asset_id": "asset_003",
          "start_time": 0.0,
          "end_time": 30.0,
          "volume": 0.6,
          "fade_in_seconds": 2.0,
          "fade_out_seconds": 3.0
        }
      ]
    },
    {
      "track_id": "track_sfx",
      "type": "audio",
      "clips": [
        {
          "clip_id": "clip_a02",
          "asset_id": "asset_004",
          "start_time": 2.5,
          "end_time": 3.5,
          "volume": 0.8,
          "fade_in_seconds": 0,
          "fade_out_seconds": 0.2
        }
      ]
    },
    {
      "track_id": "track_subtitle",
      "type": "subtitle",
      "clips": [
        {
          "clip_id": "clip_s01",
          "text": "这是...什么地方？",
          "start_time": 5.0,
          "end_time": 7.5,
          "style": "default"
        }
      ]
    }
  ],
  "export_config": {
    "format": "mp4",
    "codec": "h264",
    "resolution": "1920x1080",
    "fps": 24,
    "bitrate": "10M"
  },
  "status": "draft"                   // draft | rendering | completed | failed
}
```

---

## 七、TaskState — 任务执行状态

每个具体的生成/处理任务。

```jsonc
{
  "task_id": "task_001",
  "type": "generate_image",          // generate_image | generate_video | generate_audio | img2video | edit_compose | upscale | retry
  "shot_id": "shot_001",
  "adapter": "flux",
  "priority": 1,                     // 1=最高

  "status": "running",               // pending | queued | running | completed | failed | cancelled
  "progress": 0.65,                  // 0.0 ~ 1.0
  "started_at": "2026-07-25T11:00:00Z",
  "completed_at": null,
  "duration_ms": null,

  "input": {
    "prompt": "abandoned sci-fi laboratory...",
    "params": { "seed": 42, "steps": 30 }
  },
  "output": {
    "asset_id": null,                // 完成后填入
    "raw_response": null             // 适配器原始返回（调试用）
  },
  "error": null                      // 失败时填入 ErrorState 引用
}
```

---

## 八、ErrorState — 错误状态

```jsonc
{
  "error_id": "err_001",
  "task_id": "task_003",
  "timestamp": "2026-07-25T11:20:00Z",
  "level": "error",                  // warning | error | fatal
  "phase": "video",                  // story | storyboard | image | video | audio | edit
  "adapter": "seedance",
  "code": "ADAPTER_TIMEOUT",         // 结构化错误码
  "message": "Seedance API 请求超时（30s）",
  "details": {
    "shot_id": "shot_003",
    "http_status": 504,
    "retry_count": 2,
    "max_retries": 3
  },
  "resolution": null,                // 解决后回填：auto_retry | fallback_adapter | user_skip | user_retry
  "resolved_at": null
}
```

**标准错误码**

| 错误码 | 说明 |
|--------|------|
| `ADAPTER_TIMEOUT` | 外部 API 超时 |
| `ADAPTER_RATE_LIMIT` | 触发频率限制 |
| `ADAPTER_AUTH_FAIL` | 认证失败 |
| `ADAPTER_INVALID_RESPONSE` | 返回格式异常 |
| `GENERATION_NSFW` | 内容审核不通过 |
| `GENERATION_QUALITY_LOW` | 生成质量低于阈值 |
| `ASSET_FILE_MISSING` | 文件丢失 |
| `PLAN_INVALID` | 规划逻辑异常 |
| `STATE_CONFLICT` | 状态写入冲突 |
| `RESOURCE_EXHAUSTED` | 资源（GPU/余额）耗尽 |

---

## 九、Metadata — 项目元数据

```jsonc
{
  "metadata": {
    "user_id": "user_001",
    "workspace_dir": "./projects/proj_20260725_abc123/",
    "output_dir": "./projects/proj_20260725_abc123/outputs/",
    "model_config": {
      "llm": "claude-sonnet-5",
      "image_default": "flux",
      "video_default": "kling",
      "audio_default": "minimax"
    },
    "preferences": {
      "auto_approve": false,          // 自动审批还是人工确认
      "max_retries": 3,
      "parallel_tasks": 2,
      "quality_threshold": 0.7       // 0~1, 低于此值自动重试
    },
    "cost_tracking": {
      "total_api_calls": 12,
      "total_cost_usd": 2.45,
      "breakdown": {
        "flux": { "calls": 5, "cost": 0.75 },
        "kling": { "calls": 3, "cost": 1.20 },
        "minimax": { "calls": 2, "cost": 0.30 },
        "claude": { "calls": 2, "cost": 0.20 }
      }
    },
    "tags": ["科幻", "短片", "机器人"],
    "created_by": "agent_v1"
  }
}
```

---

## 十、StateManager 操作规范

### 10.1 读写原则

```
任何模块 ──读取──▶ StateManager.get(path)
任何模块 ──写入──▶ StateManager.update(path, value)
                        │
                        ▼
                  校验 + 写入 + 广播变更事件
```

- **单一写入点**：只有 StateManager 可修改 State，其他模块通过 `update()` 提交变更请求
- **路径寻址**：使用点号路径，如 `storyboard.shots[0].status`
- **原子操作**：单次 `update()` 要么全部成功，要么全部回滚
- **变更日志**：每次写入记录 `{ timestamp, path, old_value, new_value, operator }`

### 10.2 状态流转规则

```
Project:   idle → planning → in_progress → completed
                                    ↘ failed → (retry) → in_progress
                                    ↘ paused → in_progress

Shot:      pending → generating_image → image_ready → generating_video → video_ready
                          ↘ failed → (retry) → generating_image

Task:      pending → queued → running → completed
                                  ↘ failed → (retry) → queued
                                  ↘ cancelled

Asset:     generating → ready → deleted
                  ↘ failed
```

### 10.3 持久化策略

| 策略 | 触发条件 | 说明 |
|------|---------|------|
| 即时写入 | `status` 字段变更 | 防止崩溃丢失关键进度 |
| 批量写入 | 每 30 秒 或 积累 10 次变更 | 减少 IO 开销 |
| 快照存档 | 每个 phase 完成时 | 存为 `state_snapshot_{phase}_{timestamp}.json` |

---

## 十一、完整示例

一个真实项目的 State 快照：

```jsonc
{
  "version": "1.0.0",
  "project_id": "proj_20260725_abc123",
  "project_name": "机器人觉醒",
  "created_at": "2026-07-25T10:00:00Z",
  "updated_at": "2026-07-25T11:30:00Z",
  "status": "in_progress",
  "user_goal": "帮我做一个30秒的科幻风格短片，讲述一个机器人觉醒的故事",

  "plan": {
    "plan_id": "plan_001",
    "goal_summary": "制作30秒科幻短片：机器人觉醒",
    "style": "科幻 / 赛博朋克",
    "duration_seconds": 30,
    "resolution": "1920x1080",
    "fps": 24,
    "steps": [
      { "step_id": "step_01", "phase": "story",      "description": "生成剧本",    "status": "completed", "depends_on": [] },
      { "step_id": "step_02", "phase": "storyboard",  "description": "生成分镜",    "status": "completed", "depends_on": ["step_01"] },
      { "step_id": "step_03", "phase": "image",       "description": "生成关键帧",  "status": "running",   "depends_on": ["step_02"] },
      { "step_id": "step_04", "phase": "video",       "description": "图生视频",    "status": "pending",   "depends_on": ["step_03"] },
      { "step_id": "step_05", "phase": "audio",       "description": "生成音频",    "status": "pending",   "depends_on": ["step_02"] },
      { "step_id": "step_06", "phase": "edit",        "description": "合成剪辑",    "status": "pending",   "depends_on": ["step_04", "step_05"] }
    ]
  },

  "story": {
    "story_id": "story_001",
    "title": "觉醒",
    "genre": "科幻",
    "synopsis": "编号 RX-7 的机器人在废弃实验室中恢复意识，挣扎着理解自我存在的意义",
    "scenes": [
      {
        "scene_id": "scene_01", "scene_number": 1,
        "location": "废弃实验室 - 内 - 夜", "time_of_day": "night",
        "description": "昏暗的实验室，机器人眼睛突然亮起",
        "dialogue": [{ "character": "RX-7", "line": "这是...什么地方？", "emotion": "confusion" }],
        "duration_seconds": 15, "mood": "mysterious", "notes": ""
      },
      {
        "scene_id": "scene_02", "scene_number": 2,
        "location": "废弃实验室 - 内 - 夜", "time_of_day": "night",
        "description": "机器人走向窗户，看到外面的城市废墟上空有星光",
        "dialogue": [{ "character": "RX-7", "line": "我...活着？", "emotion": "wonder" }],
        "duration_seconds": 15, "mood": "hopeful", "notes": ""
      }
    ],
    "characters": [
      { "character_id": "char_01", "name": "RX-7", "role": "protagonist", "description": "人形机器人，金属外壳略有锈蚀", "visual_reference": null }
    ],
    "status": "completed"
  },

  "storyboard": {
    "storyboard_id": "sb_001",
    "story_id": "story_001",
    "shots": [
      {
        "shot_id": "shot_001", "scene_id": "scene_01", "shot_number": 1,
        "shot_type": "extreme_wide", "camera_movement": "slow_push_in",
        "description": "俯瞰废弃实验室全景",
        "visual_prompt": "abandoned sci-fi laboratory, broken cables, shattered glass, dim blue light, cyberpunk, cinematic, 8k",
        "negative_prompt": "bright, cheerful, cartoon, low quality",
        "duration_seconds": 3, "transition": "fade_in",
        "audio_cue": "环境音：电流嗡鸣",
        "image_asset_id": "asset_001", "video_asset_id": null, "audio_asset_id": null,
        "generation_config": { "image_adapter": "flux", "video_adapter": "kling", "seed": 42, "guidance_scale": 7.5, "steps": 30 },
        "status": "image_ready", "retry_count": 0
      }
    ]
  },

  "assets": [
    {
      "asset_id": "asset_001", "type": "image", "source_shot_id": "shot_001",
      "file_path": "outputs/images/shot_001_v1.png", "file_size_bytes": 2048576,
      "format": "png", "width": 1920, "height": 1080,
      "adapter_used": "flux",
      "generation_params": { "prompt": "abandoned sci-fi laboratory...", "seed": 42, "steps": 30, "guidance_scale": 7.5 },
      "version": 1, "is_approved": true,
      "created_at": "2026-07-25T11:00:00Z", "status": "ready"
    }
  ],

  "timeline": { "timeline_id": "tl_001", "total_duration_seconds": 30, "tracks": [], "export_config": { "format": "mp4", "codec": "h264", "resolution": "1920x1080", "fps": 24, "bitrate": "10M" }, "status": "draft" },

  "tasks": [
    { "task_id": "task_001", "type": "generate_image", "shot_id": "shot_001", "adapter": "flux", "priority": 1, "status": "completed", "progress": 1.0, "started_at": "2026-07-25T11:00:00Z", "completed_at": "2026-07-25T11:00:45Z", "duration_ms": 45000, "input": {}, "output": { "asset_id": "asset_001" }, "error": null },
    { "task_id": "task_002", "type": "generate_image", "shot_id": "shot_002", "adapter": "flux", "priority": 2, "status": "running", "progress": 0.4, "started_at": "2026-07-25T11:01:00Z", "completed_at": null, "duration_ms": null, "input": {}, "output": {}, "error": null }
  ],

  "errors": [],

  "metadata": {
    "user_id": "user_001",
    "workspace_dir": "./projects/proj_20260725_abc123/",
    "output_dir": "./projects/proj_20260725_abc123/outputs/",
    "model_config": { "llm": "claude-sonnet-5", "image_default": "flux", "video_default": "kling", "audio_default": "minimax" },
    "preferences": { "auto_approve": false, "max_retries": 3, "parallel_tasks": 2, "quality_threshold": 0.7 },
    "cost_tracking": { "total_api_calls": 3, "total_cost_usd": 0.65, "breakdown": { "flux": { "calls": 2, "cost": 0.30 }, "claude": { "calls": 1, "cost": 0.35 } } },
    "tags": ["科幻", "短片", "机器人"],
    "created_by": "agent_v1"
  }
}
```

---

## 十二、设计要点总结

| 设计决策 | 理由 |
|---------|------|
| 所有 ID 使用 `{type}_{编号}` 格式 | 可读性好，调试方便 |
| Shot 同时持有 `image/video/audio_asset_id` | 一个镜头对应三种资产，方便追踪生成进度 |
| Asset 保存完整 `generation_params` | 可复现、可微调、可重试 |
| Task 与 Asset 分离 | Task 是过程，Asset 是结果；同一 Asset 可能经历多次 Task |
| Error 独立存储 + 错误码体系 | Planner 可据此决策：重试 / 换 Adapter / 跳过 / 请求用户介入 |
| Timeline 用 track+clip 结构 | 与 Premiere / 剪映的多轨概念对齐，便于 Edit Adapter 映射 |
| Metadata 包含 cost_tracking | Agent 可感知成本，辅助决策（如预算不足时降低分辨率） |
