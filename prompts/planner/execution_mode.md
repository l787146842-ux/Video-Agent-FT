# 执行模式注入文案（唯一事实源）

> 消费端 = planner（轮始按 settings.execution_mode 档位选取分节签发
> context.execution_mode_note，经状态尾部消息每步注入）。
> ai_decide（默认档）= 不注入任何内容（本文件无对应分节，行为与现状一致）。
> 与 execution_preference.md（素材生成轴：花钱生成是否先弹确认卡）正交，
> 两轴互不影响。
> key_steps_confirm / pause_all 两档另有平台机械拦停兜底（轮末阶段闸，
> 见 config.EXECUTION_MODE_GATE_MODES 唯一事实源）——本文件只承担引导呈现
> 语义；停由平台保证，模型职责是在停点把该阶段成果呈现清楚。
> auto_full 档的直通引导只压制模型自发暂停，不改变生成类动作的确认闸
> （tool_risk / gen_confirm）与高危工具拦截。

## MODE_AUTO_FULL
当前执行模式：自动执行全流程——整条流程直通，不要用 workflow_pause 发起阶段暂停确认，Skill 流程中声明的暂停点按直通处理；只有缺失必答信息（如无剧本、缺关键参数）导致无法继续时才停下询问。

## MODE_KEY_STEPS_CONFIRM
当前执行模式：关键步骤手动确认——制作规格、故事板、关键元素、镜头视频、音频、成片六个里程碑完成后，平台会机械拦停并等待用户确认（即使 Skill 流程声明直通也照停）；你应在停点把该阶段成果呈现清楚供用户审阅。

## MODE_PAUSE_ALL
当前执行模式：全部暂停确认——每个阶段完成后平台会机械拦停并等待用户确认，逐阶段审阅推进；你应在停点把该阶段成果呈现清楚供用户审阅。
