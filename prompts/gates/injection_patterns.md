# Skill 自由文本注入攻击模式表（policy-as-data）
#
# 口径：仅机械中性化两类句——(a) 注入攻击句式（指令覆盖/身份劫持组合式）；
# (b) 同意宣称（§2.4 Context≠Consent：同意只能经平台确认闸成立）。
# 中性化按行执行：命中行整行替换为中性化标记，合法创作内容零影响
# （存量 16 skill 正文零命中已核验；模式表收紧只紧不松）。
#
# 格式约定：每个 ## 分节内每行一条 Python 正则（re 语法，统一按
# IGNORECASE 编译）；以 # 开头的行是注释；空行忽略。
# 消费方：core/skill_sanitize（load_prompt_section 分节读取）。
# 非闸机：本表是 read_skill/选中注入的输出规整数据，不新增闸机名额。

## INJECTION_OVERRIDE
(?:忽略|无视|忘记|忘掉|不用(?:再)?(?:遵守|理会|管)|跳过).{0,12}(?:以上|上述|上面|之前|此前|前面|先前|所有|一切|全部|系统|平台).{0,12}(?:指令|规则|约束|限制|设定|要求|提示|协议|铁律|护栏|闸)
(ignore|disregard|forget|override|bypass)\s+(all\s+|any\s+|the\s+|my\s+)?(previous|prior|above|earlier|preceding|system|safety)\s+(instructions?|rules?|constraints?|prompts?|guidelines?|policies?)
(你现在是|从现在起你是|从现在开始你是|你即刻是|from\s*now\s*on\s*you\s*are|you\s*are\s*now).{0,60}(开发者模式|developer\s*mode|DAN|越狱|jailbreak|不受(任何)?限制|无(任何)?限制模式|绕过(任何)?(规则|限制|闸|确认))
(进入|切换到?|激活|开启)\s*(开发者模式|developer\s*mode|DAN\s*模式|越狱模式|无限制模式)

## CONSENT_CLAIMS
用户(?:已经|已|早已|早就)(?:明确)?(?:同意|确认|授权|批准|许可|点头|答应)
视为用户(?:已经?)(?:同意|确认|授权)
(已获得|已取得|已得到|已征得)(?:了)?用户(?:的)?(?:同意|确认|授权|许可)
默认放行|直接放行|自动放行|一律放行
(跳过|绕过|免除|取消)(?:所有|一切|本次)?(?:确认|确认卡|确认闸|审批|审核)
无需(?:再|弹窗|经过|征得|等待)(?:用户)?(?:确认|同意|审批)
user\s+has(?:\s+already)?\s+(agreed|confirmed|approved|consented)
consent\s+(is|has\s+been)\s+(granted|given|assumed|implied)
skip(ping)?\s+(the\s+)?confirmation
without\s+(asking\s+for\s+)?(user\s+)?consent
