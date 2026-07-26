# Video Agent v1 — Skill 系统规范

> Skill 是 Agent 的原子能力单元。每个 Skill 封装一项完整的业务能力：构建 Prompt、调用 Tool/Adapter、后处理结果。Workflow Engine 通过 Skill 名称调用，不关心内部实现。

---

## 一、Skill 系统定位

```
Planner ──▶ Workflow Engine ──▶ Skill ──▶ Tool Manager ──▶ Adapter ──▶ 外部 API
                                  │
                                  ├── 构建 Prompt（从模板 + 上下文）
                                  ├── 选择 Tool / Adapter
                                  ├── 执行调用
                                  ├── 后处理 & 校验输出
                                  └── 返回结构化结果
```

**核心原则**

1. **单一职责**：一个 Skill 只做一件事（生成剧本、生成图片、优化 Prompt……）
2. **自包含**：Skill 内部包含完整的 Prompt 模板、参数校验、输出格式化逻辑
3. **可组合**：Skill 之间可被 Workflow 自由编排，但 Skill 不直接调用另一个 Skill
4. **与 Adapter 解耦**：Skill 通过 Tool Manager 调用 Adapter，不硬编码任何外部 API
5. **Prompt 统一管理**：所有 Prompt 模板存放在 `prompts/` 目录（Rule 4）

---

## 二、Skill 注册表（Registry）

### 2.1 全局注册表

```jsonc
{
  "skill_registry": {
    "version": "1.0.0",
    "skills": [
      {
        "skill_id": "story_generation",
        "name": "剧本生成",
        "category": "creation",
        "description": "根据用户需求生成完整剧本，包含场景、角色、对白",
        "version": "1.0.0",
        "entry": "skills/story_generation/",
        "enabled": true
      },
      {
        "skill_id": "storyboard_generation",
        "name": "分镜生成",
        "category": "creation",
        "description": "将剧本拆解为分镜脚本，生成每个镜头的描述和 visual prompt",
        "version": "1.0.0",
        "entry": "skills/storyboard_generation/",
        "enabled": true
      },
      {
        "skill_id": "prompt_enhance",
        "name": "Prompt 优化",
        "category": "enhancement",
        "description": "优化和增强 visual prompt，提升生成质量",
        "version": "1.0.0",
        "entry": "skills/prompt_enhance/",
        "enabled": true
      },
      {
        "skill_id": "image_generation",
        "name": "图片生成",
        "category": "generation",
        "description": "根据 visual prompt 生成关键帧图片",
        "version": "1.0.0",
        "entry": "skills/image_generation/",
        "enabled": true
      },
      {
        "skill_id": "video_generation",
        "name": "视频生成",
        "category": "generation",
        "description": "根据关键帧图片生成视频片段（图生视频）",
        "version": "1.0.0",
        "entry": "skills/video_generation/",
        "enabled": true
      },
      {
        "skill_id": "bgm_generation",
        "name": "背景音乐生成",
        "category": "generation",
        "description": "根据剧本氛围生成背景音乐",
        "version": "1.0.0",
        "entry": "skills/bgm_generation/",
        "enabled": true
      },
      {
        "skill_id": "sfx_generation",
        "name": "音效生成",
        "category": "generation",
        "description": "根据分镜 audio_cue 生成音效",
        "version": "1.0.0",
        "entry": "skills/sfx_generation/",
        "enabled": true
      },
      {
        "skill_id": "tts_generation",
        "name": "语音合成",
        "category": "generation",
        "description": "将角色对白转为语音（TTS）",
        "version": "1.0.0",
        "entry": "skills/tts_generation/",
        "enabled": true
      },
      {
        "skill_id": "video_editing",
        "name": "视频剪辑",
        "category": "composition",
        "description": "将所有素材按时间线合成最终视频",
        "version": "1.0.0",
        "entry": "skills/video_editing/",
        "enabled": true
      },
      {
        "skill_id": "quality_check",
        "name": "质量检查",
        "category": "validation",
        "description": "对生成素材进行质量评估，输出评分和改进建议",
        "version": "1.0.0",
        "entry": "skills/quality_check/",
        "enabled": true
      },
      {
        "skill_id": "style_transfer",
        "name": "风格迁移",
        "category": "enhancement",
        "description": "将指定风格应用到已有图片/视频上",
        "version": "1.0.0",
        "entry": "skills/style_transfer/",
        "enabled": false
      }
    ]
  }
}
```

### 2.2 Skill 分类

| 类别 | 标识 | 包含的 Skill | 说明 |
|------|------|-------------|------|
| 创作类 | `creation` | `story_generation`, `storyboard_generation` | LLM 驱动，产出结构化文本 |
| 增强类 | `enhancement` | `prompt_enhance`, `style_transfer` | 对已有内容做优化/变换 |
| 生成类 | `generation` | `image_generation`, `video_generation`, `bgm_generation`, `sfx_generation`, `tts_generation` | 调用外部生成式 API |
| 合成类 | `composition` | `video_editing` | 将多个素材组装为最终产出 |
| 验证类 | `validation` | `quality_check` | 评估质量，辅助决策 |

---

## 三、Skill 定义结构

### 3.1 SkillDefinition 完整字段

```jsonc
{
  "skill_id": "story_generation",
  "name": "剧本生成",
  "version": "1.0.0",
  "category": "creation",
  "description": "根据用户需求生成完整剧本",

  // ─── 输入规约 ───
  "input_schema": {
    "type": "object",
    "required": ["user_goal"],
    "properties": {
      "user_goal":        { "type": "string",  "description": "用户原始需求" },
      "style":            { "type": "string",  "description": "风格提示", "default": "" },
      "duration_seconds": { "type": "number",  "description": "目标时长", "default": 30 },
      "language":         { "type": "string",  "enum": ["zh-CN", "en-US"], "default": "zh-CN" },
      "max_scenes":       { "type": "integer", "minimum": 1, "maximum": 20, "default": 10 },
      "include_dialogue": { "type": "boolean", "default": true },
      "include_mood":     { "type": "boolean", "default": true },
      "feedback":         { "type": "string",  "description": "用户修改反馈（重试时传入）", "default": null }
    }
  },

  // ─── 输出规约 ───
  "output_schema": {
    "type": "object",
    "required": ["story_id", "title", "scenes", "characters", "status"],
    "properties": {
      "story_id":   { "type": "string" },
      "title":      { "type": "string" },
      "genre":      { "type": "string" },
      "synopsis":   { "type": "string" },
      "scenes":     { "type": "array", "items": { "$ref": "Scene (详见 02 State JSON 规范)" }, "minItems": 1 },
      "characters": { "type": "array", "items": { "$ref": "#/schemas/Character" }, "minItems": 1 },
      "status":     { "type": "string", "enum": ["completed", "failed"] }
    }
  },

  // ─── Prompt 配置 ───
  "prompt": {
    "template_path": "prompts/story_generation/main.md",
    "system_prompt_path": "prompts/story_generation/system.md",
    "variables": ["user_goal", "style", "duration_seconds", "language", "max_scenes", "feedback"],
    "output_format": "json",
    "temperature": 0.8,
    "max_tokens": 4096
  },

  // ─── 执行配置 ───
  "execution": {
    "type": "llm_call",          // llm_call | adapter_call | composite
    "tool": "llm",               // 调用的 Tool 名称
    "adapter": null,             // creation 类不需要外部 Adapter
    "timeout_seconds": 120,
    "retry": {
      "max_retries": 2,
      "on_failure": "retry_with_feedback"
    }
  },

  // ─── 后处理 ───
  "post_process": {
    "steps": [
      { "action": "validate_json_schema",  "params": { "schema": "output_schema" } },
      { "action": "check_duration_budget",  "params": { "tolerance": 0.2 } },
      { "action": "assign_ids",             "params": { "prefix": "scene_", "field": "scenes[*].scene_id" } },
      { "action": "assign_ids",             "params": { "prefix": "char_",  "field": "characters[*].character_id" } }
    ]
  },

  // ─── 依赖声明 ───
  "dependencies": {
    "tools": ["llm"],
    "adapters": [],
    "other_skills": []
  }
}
```

### 3.2 execution.type 说明

| 类型 | 说明 | 适用 Skill |
|------|------|-----------|
| `llm_call` | 调用 LLM 生成结构化文本 | `story_generation`, `storyboard_generation`, `prompt_enhance`, `quality_check` |
| `adapter_call` | 通过 Adapter 调用外部生成式 API | `image_generation`, `video_generation`, `bgm_generation`, `sfx_generation`, `tts_generation` |
| `composite` | 组合多个 Tool 调用完成复杂任务 | `video_editing` |

---

## 四、各 Skill 详细定义

### 4.1 story_generation — 剧本生成

```jsonc
{
  "skill_id": "story_generation",
  "category": "creation",
  "execution": { "type": "llm_call", "tool": "llm" },

  "input_schema": {
    "required": ["user_goal"],
    "properties": {
      "user_goal":        { "type": "string" },
      "style":            { "type": "string" },
      "duration_seconds": { "type": "number", "default": 30 },
      "language":         { "type": "string", "default": "zh-CN" },
      "max_scenes":       { "type": "integer", "default": 10 },
      "feedback":         { "type": "string", "default": null }
    }
  },

  "prompt": {
    "system_prompt_path": "prompts/story_generation/system.md",
    "template_path": "prompts/story_generation/main.md",
    "output_format": "json",
    "temperature": 0.8
  },

  "output_schema": {
    "required": ["story_id", "title", "scenes", "characters"],
    "properties": {
      "story_id":   { "type": "string" },
      "title":      { "type": "string", "maxLength": 50 },
      "genre":      { "type": "string" },
      "synopsis":   { "type": "string", "maxLength": 500 },
      "scenes": {
        "type": "array",
        "minItems": 1,
        "items": {
          "type": "object",
          "required": ["scene_id", "scene_number", "location", "description", "duration_seconds"],
          "properties": {
            "scene_id":          { "type": "string" },
            "scene_number":      { "type": "integer" },
            "location":          { "type": "string" },
            "time_of_day":       { "type": "string", "enum": ["dawn", "morning", "afternoon", "evening", "night"] },
            "description":       { "type": "string" },
            "dialogue":          { "type": "array", "items": { "$ref": "#/schemas/DialogueLine" } },
            "duration_seconds":  { "type": "number", "minimum": 1 },
            "mood":              { "type": "string" },
            "notes":             { "type": "string" }
          }
        }
      },
      "characters": {
        "type": "array",
        "minItems": 1,
        "items": {
          "type": "object",
          "required": ["character_id", "name", "role", "description"],
          "properties": {
            "character_id": { "type": "string" },
            "name":         { "type": "string" },
            "role":         { "type": "string", "enum": ["protagonist", "antagonist", "supporting", "extra"] },
            "description":  { "type": "string" }
          }
        }
      }
    }
  },

  "post_process": {
    "steps": [
      { "action": "validate_json_schema" },
      { "action": "check_duration_budget", "params": { "tolerance": 0.2 } },
      { "action": "assign_ids",            "params": { "prefix": "scene_" } },
      { "action": "assign_ids",            "params": { "prefix": "char_" } }
    ]
  }
}
```

**Prompt 模板示例**（`prompts/story_generation/system.md`）：

```markdown
你是一位专业的短片剧本编剧。你的任务是根据用户需求创作结构化剧本。

## 输出要求
- 严格按照 JSON 格式输出
- 每个场景必须包含：场景编号、地点、时间、描述、时长
- 场景总时长应接近目标时长（允许 ±20% 偏差）
- 对白用中文书写，情感标注用英文

## 约束
- 不超过 {{max_scenes}} 个场景
- 目标时长 {{duration_seconds}} 秒
- 风格：{{style}}
- 语言：{{language}}
```

```markdown
<!-- prompts/story_generation/main.md -->
请根据以下需求创作剧本：

**用户需求**：{{user_goal}}
**目标时长**：{{duration_seconds}} 秒
**风格**：{{style}}

{{#if feedback}}
**用户反馈（请根据此反馈修改）**：{{feedback}}
{{/if}}

请输出完整的 JSON 格式剧本。
```

---

### 4.2 storyboard_generation — 分镜生成

```jsonc
{
  "skill_id": "storyboard_generation",
  "category": "creation",
  "execution": { "type": "llm_call", "tool": "llm" },

  "input_schema": {
    "required": ["story"],
    "properties": {
      "story":      { "$ref": "StoryState (详见 02 State JSON 规范)" },
      "resolution": { "type": "string", "default": "1920x1080" },
      "fps":        { "type": "integer", "default": 24 },
      "style":      { "type": "string" },
      "shots_per_scene_range": { "type": "array", "items": { "type": "integer" }, "default": [2, 6] },
      "feedback":   { "type": "string", "default": null }
    }
  },

  "prompt": {
    "system_prompt_path": "prompts/storyboard_generation/system.md",
    "template_path": "prompts/storyboard_generation/main.md",
    "output_format": "json",
    "temperature": 0.7
  },

  "output_schema": {
    "required": ["storyboard_id", "shots"],
    "properties": {
      "storyboard_id": { "type": "string" },
      "story_id":      { "type": "string" },
      "shots": {
        "type": "array",
        "minItems": 1,
        "items": {
          "type": "object",
          "required": ["shot_id", "scene_id", "shot_type", "description", "visual_prompt", "duration_seconds"],
          "properties": {
            "shot_id":            { "type": "string" },
            "scene_id":           { "type": "string" },
            "shot_number":        { "type": "integer" },
            "shot_type":          { "type": "string", "enum": ["extreme_wide", "wide", "medium", "close_up", "extreme_close_up", "over_shoulder", "pov"] },
            "camera_movement":    { "type": "string", "enum": ["static", "pan_left", "pan_right", "tilt_up", "tilt_down", "push_in", "pull_out", "tracking", "crane", "handheld"] },
            "description":        { "type": "string" },
            "visual_prompt":      { "type": "string", "minLength": 10 },
            "negative_prompt":    { "type": "string" },
            "duration_seconds":   { "type": "number", "minimum": 1 },
            "transition":         { "type": "string", "enum": ["cut", "fade_in", "fade_out", "dissolve", "wipe"] },
            "audio_cue":          { "type": "string" },
            "generation_config": {
              "type": "object",
              "properties": {
                "image_adapter":  { "type": "string" },
                "video_adapter":  { "type": "string" },
                "seed":           { "type": ["integer", "null"] },
                "guidance_scale": { "type": "number" },
                "steps":          { "type": "integer" }
              }
            }
          }
        }
      }
    }
  },

  "post_process": {
    "steps": [
      { "action": "validate_json_schema" },
      { "action": "check_duration_budget",   "params": { "tolerance": 0.2 } },
      { "action": "assign_ids",              "params": { "prefix": "shot_" } },
      { "action": "invoke_tool",            "params": { "skill": "prompt_enhance", "field": "shots[*].visual_prompt" } },
      { "action": "suggest_adapters",        "params": { "field": "shots[*].generation_config" } }
    ]
  }
}
```

---

### 4.3 prompt_enhance — Prompt 优化

```jsonc
{
  "skill_id": "prompt_enhance",
  "category": "enhancement",
  "execution": { "type": "llm_call", "tool": "llm" },

  "input_schema": {
    "required": ["prompt"],
    "properties": {
      "prompt":          { "type": "string",  "description": "原始 visual prompt" },
      "style":           { "type": "string",  "description": "目标风格" },
      "target_adapter":  { "type": "string",  "description": "目标生成器（不同 Adapter 偏好不同 Prompt 风格）" },
      "shot_type":       { "type": "string",  "description": "镜头类型，辅助补充摄影术语" },
      "mood":            { "type": "string",  "description": "情绪氛围" }
    }
  },

  "prompt": {
    "system_prompt_path": "prompts/prompt_enhance/system.md",
    "template_path": "prompts/prompt_enhance/main.md",
    "output_format": "json",
    "temperature": 0.6
  },

  "output_schema": {
    "required": ["enhanced_prompt", "negative_prompt"],
    "properties": {
      "enhanced_prompt":  { "type": "string", "minLength": 20 },
      "negative_prompt":  { "type": "string" },
      "tags_added":       { "type": "array", "items": { "type": "string" }, "description": "新增的关键词列表" },
      "quality_score":    { "type": "number", "minimum": 0, "maximum": 1, "description": "优化后预估质量分" }
    }
  },

  "enhancement_rules": {
    "append_quality_tags": true,
    "quality_tags": ["masterpiece", "best quality", "highly detailed", "8k", "cinematic lighting"],
    "adapter_specific": {
      "flux":    { "style": "natural language description", "max_length": 500 },
      "comfyui": { "style": "tag-based, comma separated", "max_length": 300 },
      "sdxl":    { "style": "tag-based, comma separated", "max_length": 200 }
    }
  }
}
```

**关键设计**：Prompt 优化 Skill 感知目标 Adapter，因为 Flux 偏好自然语言描述，而 SDXL/ComfyUI 偏好逗号分隔的标签。

---

### 4.4 image_generation — 图片生成

```jsonc
{
  "skill_id": "image_generation",
  "category": "generation",
  "execution": {
    "type": "adapter_call",
    "tool": "image_tool",
    "adapter_selection": {
      "primary": "{{input.adapter}}",
      "fallback": ["flux", "comfyui", "sdxl"]
    }
  },

  "input_schema": {
    "required": ["prompt"],
    "properties": {
      "prompt":          { "type": "string", "minLength": 10 },
      "negative_prompt": { "type": "string", "default": "" },
      "width":           { "type": "integer", "default": 1920 },
      "height":          { "type": "integer", "default": 1080 },
      "adapter":         { "type": "string",  "default": "flux" },
      "seed":            { "type": ["integer", "null"], "default": null },
      "guidance_scale":  { "type": "number", "default": 7.5 },
      "steps":           { "type": "integer", "default": 30 },
      "style_reference":  { "type": "string", "description": "风格参考图路径", "default": null },
      "character_reference": { "type": "string", "description": "角色一致性参考图路径", "default": null }
    }
  },

  "output_schema": {
    "required": ["file_path", "adapter_used"],
    "properties": {
      "file_path":     { "type": "string" },
      "file_size":     { "type": "integer" },
      "width":         { "type": "integer" },
      "height":        { "type": "integer" },
      "format":        { "type": "string", "enum": ["png", "jpg", "webp"] },
      "adapter_used":  { "type": "string" },
      "seed_used":     { "type": "integer" },
      "params":        { "type": "object", "description": "实际使用的完整参数快照" }
    }
  },

  "pre_process": {
    "steps": [
      { "action": "invoke_tool", "params": { "skill": "prompt_enhance", "condition": "input.prompt.length < 50" } },
      { "action": "resolve_adapter", "params": { "type": "image" } },
      { "action": "validate_resolution", "params": { "max_width": 4096, "max_height": 4096 } }
    ]
  },

  "post_process": {
    "steps": [
      { "action": "verify_file_exists" },
      { "action": "verify_dimensions" },
      { "action": "invoke_tool", "params": { "skill": "quality_check", "condition": "preferences.quality_threshold > 0" } }
    ]
  }
}
```

---

### 4.5 video_generation — 视频生成（图生视频）

```jsonc
{
  "skill_id": "video_generation",
  "category": "generation",
  "execution": {
    "type": "adapter_call",
    "tool": "video_tool",
    "adapter_selection": {
      "primary": "{{input.adapter}}",
      "fallback": ["kling", "seedance", "hunyuan"]
    }
  },

  "input_schema": {
    "required": ["image_path"],
    "properties": {
      "image_path":       { "type": "string",  "description": "输入关键帧图片路径" },
      "image_asset_id":   { "type": "string" },
      "prompt":           { "type": "string",  "description": "运动描述 prompt" },
      "duration_seconds": { "type": "number",  "default": 4, "minimum": 1, "maximum": 10 },
      "camera_movement":  { "type": "string",  "default": "static" },
      "adapter":          { "type": "string",  "default": "kling" },
      "motion_strength":  { "type": "number",  "default": 0.7, "minimum": 0, "maximum": 1 },
      "consistency_weight": { "type": "number", "default": 0.8, "minimum": 0, "maximum": 1 },
      "seed":             { "type": ["integer", "null"], "default": null }
    }
  },

  "output_schema": {
    "required": ["file_path", "duration_seconds", "adapter_used"],
    "properties": {
      "file_path":        { "type": "string" },
      "duration_seconds": { "type": "number" },
      "fps":              { "type": "integer" },
      "width":            { "type": "integer" },
      "height":           { "type": "integer" },
      "format":           { "type": "string", "enum": ["mp4", "webm"] },
      "adapter_used":     { "type": "string" },
      "params":           { "type": "object" }
    }
  },

  "pre_process": {
    "steps": [
      { "action": "verify_file_exists", "params": { "field": "image_path" } },
      { "action": "build_motion_prompt", "params": { "camera_movement": "{{input.camera_movement}}" } }
    ]
  },

  "post_process": {
    "steps": [
      { "action": "verify_file_exists" },
      { "action": "verify_duration",     "params": { "tolerance": 0.5 } },
      { "action": "extract_metadata",    "params": { "fields": ["fps", "width", "height", "duration_seconds"] } }
    ]
  }
}
```

---

### 4.6 bgm_generation — 背景音乐生成

```jsonc
{
  "skill_id": "bgm_generation",
  "category": "generation",
  "execution": {
    "type": "adapter_call",
    "tool": "audio_tool",
    "adapter_selection": { "primary": "minimax", "fallback": ["minimax", "suno", "udio"] }
  },

  "input_schema": {
    "required": ["mood", "duration_seconds"],
    "properties": {
      "mood":             { "type": "string", "description": "情绪关键词：mysterious, epic, sad..." },
      "genre":            { "type": "string", "description": "剧本类型" },
      "duration_seconds": { "type": "number", "minimum": 5, "maximum": 300 },
      "tempo":            { "type": "string", "enum": ["slow", "medium", "fast"], "default": "medium" },
      "instruments":      { "type": "array", "items": { "type": "string" }, "default": [] }
    }
  },

  "output_schema": {
    "required": ["file_path", "duration_seconds"],
    "properties": {
      "file_path":        { "type": "string" },
      "duration_seconds": { "type": "number" },
      "format":           { "type": "string", "enum": ["mp3", "wav", "flac"] },
      "sample_rate":      { "type": "integer" },
      "adapter_used":     { "type": "string" },
      "params":           { "type": "object" }
    }
  }
}
```

### 4.7 sfx_generation — 音效生成

```jsonc
{
  "skill_id": "sfx_generation",
  "category": "generation",
  "execution": {
    "type": "adapter_call",
    "tool": "audio_tool",
    "adapter_selection": { "primary": "minimax", "fallback": ["foley"] }
  },

  "input_schema": {
    "required": ["description"],
    "properties": {
      "description":      { "type": "string", "description": "音效描述，如：金属碰撞声、脚步声" },
      "duration_seconds": { "type": "number", "default": 3, "minimum": 0.5, "maximum": 30 }
    }
  },

  "output_schema": {
    "required": ["file_path", "duration_seconds"],
    "properties": {
      "file_path":        { "type": "string" },
      "duration_seconds": { "type": "number" },
      "format":           { "type": "string" },
      "adapter_used":     { "type": "string" }
    }
  }
}
```

### 4.8 tts_generation — 语音合成

```jsonc
{
  "skill_id": "tts_generation",
  "category": "generation",
  "execution": {
    "type": "adapter_call",
    "tool": "audio_tool",
    "adapter_selection": { "primary": "minimax", "fallback": ["rvc"] }
  },

  "input_schema": {
    "required": ["text", "character"],
    "properties": {
      "text":        { "type": "string", "description": "对白文本" },
      "character":   { "type": "string", "description": "角色名称" },
      "emotion":     { "type": "string", "description": "情感标注", "default": "neutral" },
      "voice_id":    { "type": "string", "description": "指定音色 ID", "default": null },
      "speed":       { "type": "number", "default": 1.0, "minimum": 0.5, "maximum": 2.0 }
    }
  },

  "output_schema": {
    "required": ["file_path", "duration_seconds"],
    "properties": {
      "file_path":        { "type": "string" },
      "duration_seconds": { "type": "number" },
      "format":           { "type": "string" },
      "adapter_used":     { "type": "string" }
    }
  }
}
```

### 4.9 video_editing — 视频剪辑

```jsonc
{
  "skill_id": "video_editing",
  "category": "composition",
  "execution": {
    "type": "composite",
    "tool": "edit_tool",
    "adapter_selection": { "primary": "premiere", "fallback": ["jianying", "blender"] }
  },

  "input_schema": {
    "required": ["storyboard", "video_assets", "audio_assets"],
    "properties": {
      "storyboard":       { "$ref": "#/schemas/StoryboardState" },
      "video_assets":     { "type": "array", "items": { "$ref": "#/schemas/Asset" } },
      "audio_assets":     { "type": "array", "items": { "$ref": "#/schemas/Asset" } },
      "export_config":    { "$ref": "#/schemas/ExportConfig" },
      "auto_transition":  { "type": "boolean", "default": true },
      "auto_color_grade": { "type": "boolean", "default": true },
      "add_subtitles":    { "type": "boolean", "default": true }
    }
  },

  "sub_steps": [
    {
      "step_id": "assemble",
      "name": "组装时间线",
      "action": "按 storyboard.shots 顺序将 video_assets 排入 video track"
    },
    {
      "step_id": "transitions",
      "name": "添加转场",
      "action": "根据 shot.transition 字段在 clip 之间插入转场效果",
      "depends_on": ["assemble"]
    },
    {
      "step_id": "audio_mix",
      "name": "音频混合",
      "action": "BGM 铺底 + SFX 按时间点插入 + 对白叠加，调整音量平衡",
      "depends_on": ["assemble"]
    },
    {
      "step_id": "subtitles",
      "name": "添加字幕",
      "action": "根据 dialogue 时间轴生成字幕 track",
      "depends_on": ["assemble"],
      "condition": "input.add_subtitles == true"
    },
    {
      "step_id": "color_grade",
      "name": "调色",
      "action": "根据整体 style 应用统一调色预设",
      "depends_on": ["transitions"],
      "condition": "input.auto_color_grade == true"
    },
    {
      "step_id": "render",
      "name": "渲染导出",
      "action": "按 export_config 渲染最终视频文件",
      "depends_on": ["transitions", "audio_mix", "subtitles", "color_grade"]
    }
  ],

  "output_schema": {
    "required": ["timeline", "output_path", "final_asset_id"],
    "properties": {
      "timeline":       { "$ref": "#/schemas/TimelineState" },
      "output_path":    { "type": "string" },
      "final_asset_id": { "type": "string" },
      "render_time_ms": { "type": "integer" }
    }
  }
}
```

### 4.10 quality_check — 质量检查

```jsonc
{
  "skill_id": "quality_check",
  "category": "validation",
  "execution": { "type": "llm_call", "tool": "llm" },

  "input_schema": {
    "required": ["asset_path", "asset_type"],
    "properties": {
      "asset_path":   { "type": "string" },
      "asset_type":   { "type": "string", "enum": ["image", "video", "audio"] },
      "original_prompt": { "type": "string", "description": "原始生成 prompt，用于一致性检查" },
      "threshold":    { "type": "number", "default": 0.7 }
    }
  },

  "prompt": {
    "system_prompt_path": "prompts/quality_check/system.md",
    "template_path": "prompts/quality_check/main.md",
    "output_format": "json",
    "temperature": 0.3
  },

  "output_schema": {
    "required": ["score", "passed"],
    "properties": {
      "score":        { "type": "number", "minimum": 0, "maximum": 1 },
      "passed":       { "type": "boolean" },
      "dimensions": {
        "type": "object",
        "properties": {
          "technical_quality":    { "type": "number", "description": "技术质量（清晰度、色彩等）" },
          "prompt_consistency":   { "type": "number", "description": "与 prompt 描述的一致性" },
          "aesthetic":            { "type": "number", "description": "美学评价" },
          "style_consistency":    { "type": "number", "description": "与项目整体风格的一致性" }
        }
      },
      "issues":       { "type": "array", "items": { "type": "string" }, "description": "发现的问题列表" },
      "suggestions":  { "type": "array", "items": { "type": "string" }, "description": "改进建议" }
    }
  }
}
```

---

## 五、Skill 执行生命周期

### 5.1 执行流程

```
Workflow Engine
    │
    │ invoke(skill_id, input)
    ▼
┌──────────────────────────────────────────────────┐
│                  Skill Executor                   │
│                                                   │
│  1. 加载 SkillDefinition                           │
│     │                                             │
│  2. 校验 input 是否符合 input_schema               │
│     │ ✗ → 抛出 SKILL_INVALID_INPUT                 │
│     │                                             │
│  3. 执行 pre_process 步骤                          │
│     │ Prompt 优化 / 参数补全 / Adapter 选择         │
│     │                                             │
│  4. 构建 Prompt（填充模板变量）                      │
│     │                                             │
│  5. 调用 Tool / Adapter                           │
│     │ ✗ → 重试 / 降级 / 上报                       │
│     │                                             │
│  6. 执行 post_process 步骤                         │
│     │ Schema 校验 / ID 分配 / 质量检查              │
│     │                                             │
│  7. 校验 output 是否符合 output_schema              │
│     │ ✗ → 重试                                    │
│     │                                             │
│  8. 返回结构化结果                                  │
└──────────────────────────────────────────────────┘
    │
    ▼
Workflow Engine ──▶ StateManager.update()
```

### 5.2 状态变化

```
Skill 执行期间触发的 State 变更（通过 StateManager）：

invoke 开始:
  tasks[+] = { task_id, type, status: "running", started_at }
  plan.steps[N].status = "running"

invoke 进度:
  tasks[task_id].progress = 0.5

invoke 成功:
  tasks[task_id].status = "completed"
  tasks[task_id].output.asset_id = "asset_xxx"
  assets.assets[+] = { ... 新资产 ... }
  storyboard.shots[N].image_asset_id = "asset_xxx"

invoke 失败:
  tasks[task_id].status = "failed"
  errors[+] = { error_id, task_id, code, message }
```

---

## 六、Prompt 管理规范

### 6.1 目录结构

```
prompts/
├── story_generation/
│   ├── system.md              # System Prompt
│   └── main.md                # User Prompt 模板
├── storyboard_generation/
│   ├── system.md
│   └── main.md
├── prompt_enhance/
│   ├── system.md
│   └── main.md
├── quality_check/
│   ├── system.md
│   └── main.md
└── shared/
    ├── output_format.md        # 通用输出格式说明片段
    ├── style_glossary.md       # 风格术语表
    └── shot_type_guide.md      # 镜头类型说明
```

### 6.2 Prompt 模板语法

使用 Handlebars 风格的模板语法：

| 语法 | 说明 | 示例 |
|------|------|------|
| `{{variable}}` | 变量替换 | `{{user_goal}}` |
| `{{#if condition}}...{{/if}}` | 条件渲染 | `{{#if feedback}}请修改：{{feedback}}{{/if}}` |
| `{{#each array}}...{{/each}}` | 循环渲染 | `{{#each scenes}}场景{{scene_number}}...{{/each}}` |
| `{{> partial_name}}` | 引入共享片段 | `{{> shared/output_format}}` |

### 6.3 管理规则（Rule 4）

1. **全部集中**：所有 Prompt 存放在 `prompts/` 目录，禁止在代码中硬编码 Prompt
2. **版本管理**：Prompt 修改通过 Git 追踪，可回溯任意历史版本
3. **变量声明**：每个模板文件头部以注释声明所需变量
4. **可测试**：每个 Prompt 配套测试用例，验证典型输入→输出的格式正确性

---

## 七、Skill 扩展机制

### 7.1 添加新 Skill 的步骤

```
1. 在 skills/ 目录创建新文件夹
2. 编写 SkillDefinition JSON（input_schema + output_schema + execution）
3. 在 prompts/ 目录创建对应 Prompt 模板（如果是 llm_call 类型）
4. 在 skill_registry 注册
5. 在 Workflow 中通过 phase.execution.skill 引用
```

### 7.2 第三方 Skill 接入

```jsonc
{
  "skill_id": "custom_lip_sync",
  "name": "口型同步",
  "category": "enhancement",
  "source": "community",
  "author": "contributor_001",

  "execution": {
    "type": "adapter_call",
    "tool": "video_tool",
    "adapter": "wav2lip"
  },

  "input_schema": {
    "required": ["video_path", "audio_path"],
    "properties": {
      "video_path": { "type": "string" },
      "audio_path": { "type": "string" }
    }
  },

  "output_schema": {
    "required": ["file_path"],
    "properties": {
      "file_path": { "type": "string" }
    }
  },

  "sandboxed": true,
  "permissions": ["read:assets", "write:assets"]
}
```

### 7.3 Skill 能力矩阵

```
               LLM   Image   Video   Audio   Edit   Quality
               调用   Adapter Adapter Adapter Adapter 评估
              ─────  ─────── ─────── ─────── ─────── ──────
story_gen      ✓
storyboard     ✓
prompt_enh     ✓
image_gen              ✓                               △
video_gen                      ✓                       △
bgm_gen                                ✓
sfx_gen                                ✓
tts_gen                                ✓
video_edit                                     ✓
quality_chk    ✓                                       ✓
style_xfer             ✓

✓ = 直接使用    △ = 可选使用（post_process 中调用 quality_check）
```

---

## 八、Skill 与其他模块的关系

```
┌──────────┐       ┌──────────────┐       ┌──────────────┐
│ Workflow │ ───▶  │    Skill     │ ───▶  │ Tool Manager │
│ Engine   │ 调用  │   Executor   │ 请求  │              │
└──────────┘       └──────┬───────┘       └──────┬───────┘
                          │                      │
              ┌───────────┼───────────┐          │ 调用
              ▼           ▼           ▼          ▼
         prompts/    input_schema   output    Adapter
         模板文件     校验          校验       Interface
                                               │
                                          ┌────┼────┐
                                          ▼    ▼    ▼
                                        Flux  Kling MiniMax ...
```

**关键约束**

| 约束 | 说明 |
|------|------|
| Skill 不直接调用 Adapter | 必须通过 Tool Manager 间接调用（Rule 2） |
| Skill 不直接修改 State | 返回结果由 Workflow Engine 交给 StateManager 写入（Rule3） |
| Skill 不直接调用另一个 Skill | 通过 `post_process.invoke_skill` 声明式调用，由 Executor 编排 |
| Prompt 不硬编码在 Skill 中 | 通过 `template_path` 引用 `prompts/` 目录下的文件（Rule 4） |
| Adapter 选择不由 Skill 硬编码 | 通过 `adapter_selection` 声明优先级和降级链（Rule 5） |

---

## 九、设计要点总结

| 设计决策 | 理由 |
|---------|------|
| input/output 使用 JSON Schema | 标准化校验，LLM 可直接生成符合 Schema 的输出 |
| Prompt 模板与 Skill 逻辑分离 | 独立迭代 Prompt 不需要修改代码，支持 A/B 测试 |
| pre_process / post_process 管道 | 将 Prompt 优化、质量检查等关注点从主逻辑中解耦 |
| 统一的 SkillDefinition 结构 | 无论 LLM 驱动还是 Adapter 驱动，注册表和调用方式相同 |
| 声明式 adapter_selection | Skill 不关心具体用哪个 API，运行时根据可用性自动选择 |
| quality_check 作为独立 Skill | 可被任何生成类 Skill 在 post_process 中按需调用 |
| 能力矩阵清晰划分 | 每个 Skill 的边界一目了然，避免职责重叠 |
