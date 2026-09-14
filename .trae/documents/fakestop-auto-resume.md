# 假停自动续跑（dsh 同款门禁 + 全局设置开关）实施计划

## Context

9999 项目实测：模型中途「光说不做」（正文说继续建组、工具调用零下发）导致回合静默终止，用户须手动发「继续」，且续跑后再次假停。34 次探针复刻 + 抓包取证已定论：停 itself 是上游瞬时故障，但「停了之后系统怎么办」是平台语义。dsh 的范式 = turn 收尾前过一道「门禁」，门禁拒绝收尾就自动拉模型续跑（带上限防失控）。用户裁决：装同款，开关放全局设置，触发条件用「话里有继续意向」（扩充词表），开关默认关。

## 设计总览

- **策略层决策，循环层执行**：现有假停策略（`round_end_policies.py` 的 `_cond_aborted_continuation_audit`）已有全部命中条件（skill 激活 + applied==0 + 承诺措辞），扩展它输出续跑意图；`agent_loop` 读回后机械续跑。
- **落点**：`RoundEndContext.continue_turn`（L149 已声明、全仓无读写的死字段）——天然落点，零新增输出通道。
- **上限**：每回合最多自动续跑 2 次（模块常量），耗尽回落现状（收尾 + 「继续」按钮兜底）。
- **开关**：新全局布尔设置 `fakestop_auto_resume_enabled`，默认 False，前端全局设置页加开关，照 `model_fallback_enabled` 现成管线。

## 改动清单（按序执行）

### 1. `src/video_agent/config.py`
- L283 `chat_image_enabled` 后加字段：`fakestop_auto_resume_enabled: bool = False`
- `SETTINGS_GROUPS` 的 `agent` 组（L441-443 附近）追加该键（循环行为开关，非 LLM 适配）。

### 2. `src/video_agent/core/round_end_policies.py`
- **扩充 `_CONTINUATION_PROMISE_RE`（L76-79）**，追加三族（实测漏网句式）：
  ```python
  r"继续(?:第[一二三四五六七八九十\d]+批)?[：:]|"
  r"第[一二三四五六七八九十\d]+批(?:到来|已?落账|开始)|"
  r"执行\s*\d+\s*个(?:操作|工具)"
  ```
  注意：裸「继续」不匹配（要求冒号/批次锚定），防误伤普通应答。
- **模块常量**（正则附近）：`FAKESTOP_AUTO_RESUME_MAX = 2`
- **`RoundEndContext` 加输入字段**（L141 `applied` 后）：`resumes_used: int = 0`（I-1.4 一等字段）。
- **`_apply_aborted_continuation_audit`（L472-477）开头分支**：
  ```python
  if settings.fakestop_auto_resume_enabled and ctx.resumes_used < FAKESTOP_AUTO_RESUME_MAX:
      ctx.continue_turn = True
      logger.info(...)
      return
  ```
  其余保持按钮现状（flag OFF / 满顶回落）。条件函数不动。
- **requires（L496-497）追加 `"resumes_used"`**——否则 import 期 `_validate_policy_table` 拦截（预期防线）。`settings` 已 import（L38）。

### 3. `src/video_agent/web/routes/runtime_settings.py`（4 处一行）
`_BOOL_KEYS`（L39）、`RuntimeSettingsUpdate`（L67-68 后）、`RuntimeSettings`（L100-101 后）、`_current_dict`（L136-137 后）各加一行。PUT 归一与启动回放遍历 `_BOOL_KEYS`，零改动。

### 4. `src/video_agent/core/agent_loop.py`
- import 追加 `FAKESTOP_AUTO_RESUME_MAX`。
- `step = 0`（L397 旁）加局部计数 `_fakestop_resumes = 0`（每 turn 天然重置，勿提升模块级）。
- `RoundEndContext` 构造（L673-687）加 `resumes_used=_fakestop_resumes`。
- **正常收尾段（L705-709）改分支**——必须位于确认/hard_break break（L695-704）之后，确认卡优先于续跑：
  ```python
  if _re_ctx.continue_turn:
      _fakestop_resumes += 1
      await emit(status_event("agent.fakestopResume",
          f"检测到模型未执行操作即收尾，已自动续跑（第 {_fakestop_resumes}/{FAKESTOP_AUTO_RESUME_MAX} 次）",
          {"count": _fakestop_resumes, "cap": FAKESTOP_AUTO_RESUME_MAX}))
      messages.append({"role": "assistant", "content": content or ""})
      _resume_note = load_prompt_section("planner/feedback.md", "FAKESTOP_RESUME_NOTE")
      if not _resume_note:  # 仿 L776-780 缺失兜底
          logger.warning("[AgentLoop] FAKESTOP_RESUME_NOTE 分节缺失，使用占位文案")
          _resume_note = "（系统提醒：上一条回复未执行任何工具操作。）"
      messages.append({"role": "user", "content": _resume_note})
      tracer.end_step(step, actions_applied=0, finish_reason="fakestop_resume",
                      token_usage=step_tokens, cached_tokens=step_cached)
      continue
  tracer.end_step(... 原 L707-709 不变 ...)
  break
  ```
- 文本累积已成立：L689 `result.text = _re_ctx.result_text` 在续跑块前执行，pre-resume 可见文本入账；后续轮由 false_claim_audit / FC 累积续拼。
- assistant 消息 content-only 无 tool_calls，OpenAI 语义合法（对齐 L637-643 注释口径）。

### 5. `prompts/planner/feedback.md`（L74 `EMPTY_RESPONSE_FALLBACK` 后加节）
```
## FAKESTOP_RESUME_NOTE
（系统机械提醒：你上一条回复未执行任何工具操作。若任务尚未完成，请立即发出所需的工具调用继续执行；若确已完成，请明确回复任务已完成并简述结果。）
```

### 6. 生成类型
`python scripts/gen_api_types.py` 重生成 `src/web/types/api.generated.ts`（禁手改）。现有 trace/sse 一致性测试只断言字段存在性，安全。

### 7. `src/web/components/layout/GlobalSettingsView.tsx`
L194「自动切换」section 后照抄 L178-194 结构插入：
- 标题：**假停自动续跑**
- 绑定：`aria-pressed={gs()!.fakestop_auto_resume_enabled}`，`onClick={() => set({ fakestop_auto_resume_enabled: !gs()!.fakestop_auto_resume_enabled })}`
- hint：「开启时，模型口头承诺继续却未执行任何操作即收尾的假停轮，系统自动注入提醒让模型续跑（每回合最多 2 次）；关闭时仅提供『继续』按钮。仅 Skill 流程中生效。」
store / api 层零改动（已核实）。改后需 `npm run build`（UI 变更经用户目测确认，宪法 §3.1）。

### 8. 测试
- `tests/unit/test_fc_leak_fakestop.py` 新增（settings 覆写用 `object.__setattr__` + teardown 还原，仿 `test_config_fallback_switch.py`）：
  - flag ON + `resumes_used=0` → `ctx.continue_turn is True` 且无 continue 按钮
  - flag ON + `resumes_used=2` → 回落按钮路径（cap 钉死）
  - 环级：首轮假停文本 + 次轮正常 → steps==2、messages 含 nudge、result.text 两段齐备
  - 三连假停 → 第三轮回落按钮
- runtime settings 测试（有现成文件则追加，否则新建）：GET 默认 False / PUT 生效落盘 / 启动回放。
- 既有 `test_pure_text_round_is_terminal`、按钮路径测试默认 OFF 保持绿（语义回归钉）。

### 9. 留痕
`CHANGELOG.md` 登记本批次（裁决：装 dsh 同款门禁、开关默认关、触发词表扩充；沿用现有批次格式）。

## 验证序列
1. 定点：`python -m pytest tests/unit/test_fc_leak_fakestop.py tests/unit/test_round_end_policies.py tests/unit/test_agent_loop.py -q -n 8 --dist loadfile` + runtime settings 相关测试
2. `python scripts/gen_api_types.py` → `npx tsc --noEmit`
3. `python scripts/acceptance.py --quick`（只认退出码 0）
4. `npm run build` → 重启后端 → 全局设置开开关 → 手动 smoke（真实对话触发续跑）→ **UI 变更经你目测确认**

## 风险与对策
- **无限续跑**：计数器为 run_agent_loop 局部 + cap 2 回落按钮，结构封死。
- **确认卡/hard_break**：续跑块物理位于其 break 之后，优先级天然正确，勿上移。
- **正则误触**：smoke 若误触再收紧词表，禁止放水。
- **流式视觉**：续跑前后两段 delta 均正常流式下发，与既有 FC 多步轮同机制；smoke 目测气泡拼接。
- **I-1.4**：`resumes_used` 访问必须登记 requires，import 期红是预期拦截。

## 交付
两个独立 commit：① 今日已过验收的 P0 取证补丁（agent_loop 步日志 + 抓包 footer 计数）；② 本特性。commit 前等你确认。
