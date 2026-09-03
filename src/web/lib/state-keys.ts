/**
 * 前端状态类别 Key 常量（前端批次1）——对齐后端 src/video_agent/state/models.py 的
 * CAT_KEY_ELEMENTS / CAT_SHOTS / CAT_AUDIO_ITEMS（宪法 §6 配置表纪律：类别 Key
 * 单一事实源）。产品代码引用这些常量而非裸字面量。门禁 scripts/check_category_keys.py
 * 扫描 src/web 产品代码（*.ts/*.tsx，不含 __tests__ 测试夹具）：本文件为永久合法出口
 * （脚本 WHITELIST_FE）；TS 类型联合位置 / subTab 页签标识等无法引用运行时常量的存量
 * 合法点登记于收缩型基线 scripts/category_keys_frontend_baseline.txt（只减不增，键粒度
 * rel:literal）。出口与基线之外的新硬编码类别 Key 即门禁失败（退出码非 0）。
 *
 * `as const` 保证类型收窄为字面量，可直接用于 setState 键、Pick 联合与相等比较。
 * 注意：subTab（'keyElements' | 'shots' | 'audio'）是 UI 页签标识，与类别 Key
 * 同名但语义不同（其音频档位为 'audio' 而非 'audioItems'），不复用本模块常量。
 */
export const CAT_KEY_ELEMENTS = 'keyElements' as const;
export const CAT_SHOTS = 'shots' as const;
export const CAT_AUDIO_ITEMS = 'audioItems' as const;
