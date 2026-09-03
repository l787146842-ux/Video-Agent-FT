"""类别 Key 字面量门禁（前后端双面；P1 机械化根治 + 前端批次1 扩面）。

状态类别键（keyElements/shots/audioItems）的单一事实源是常量，产品代码出现带引号的
类别字面量即违规（宪法 §6 配置表纪律）。函数级测试照不出此类漂移，以 grep 门禁钉死
（G4 同类全覆盖）。

后端（src/video_agent，*.py）：
    单一事实源 = state/models.py 的 CAT_KEY_ELEMENTS / CAT_SHOTS / CAT_AUDIO_ITEMS
    （pydantic alias 亦在彼）。白名单仅 models.py（常量定义处）。

前端（src/web，*.ts/*.tsx，SolidJS）：
    单一事实源 = src/web/lib/state-keys.ts 的同名 CAT_* 常量；该文件为永久合法出口
    （WHITELIST_FE），产品代码应引用常量而非裸字面量。
    扫描面仅产品代码，不含测试夹具（__tests__ / *.test.ts(x)）——与后端仅扫
    src/video_agent 产品代码、tests/ 在扫描面外一致；测试夹具用字面量构造 setState
    输入属正常。
    其余存量合法点登记于「收缩型基线」scripts/category_keys_frontend_baseline.txt
    （只减不增，与 func_imports_baseline.txt 同机制）：合法存量两类——
      ① TS 类型联合位置（如 Pick<..., 'keyElements' | 'shots'>、返回值类型），
         纯类型位无法引用运行时 CAT_* 常量；
      ② subTab UI 页签标识（'keyElements' | 'shots' | 'audio'），与类别 Key 同名但
         语义不同（其音频档位为 'audio' 而非 'audioItems'），不复用本模块常量。
    基线键粒度 = rel:literal:count（忽略行号，容忍行漂移；count = 该文件该字面量
    允许出现次数上限）。次数维度是防「基线搭车」的关键：键只到 rel:literal 时，
    同文件新增同类硬编码会被既有条目静默吸收逃逸。判定为
    counts[key] <= baseline_count[key]，超出即失败（未登记的 key 上限视为 0）；
    --refresh 只剔除已消失条目、计数只下调。旧格式条目（无 count）视为上限 0
    （fail-closed），须跑 --refresh 迁移登记计数。

fail-closed（与 check_layer_imports / check_prompt_literals / check_web_chat_bypass
同一范式）：「扫不动」不等于「没问题」。后端声明的扫描目录不存在 → 直接计失败；
--refresh 遇到空扫描集（src/web 缺失/不可读）→ 拒绝把存量 allowlist 收缩为空。

输出纯 ASCII（N1/N7 教训机制延续）。

用法：
    python scripts/check_category_keys.py            # 门禁检查（退出码非 0 即失败）
    python scripts/check_category_keys.py --refresh  # 清偿后剔除已消失条目、下调计数（只减）
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATTERN = re.compile(r"""["'](keyElements|shots|audioItems)["']""")

# ===== 后端（src/video_agent，*.py）=====
# 注：SCAN_DIR / WHITELIST_BE 名称为 canary（tests/unit/test_gate_canaries.py）
# monkeypatch 契约的一部分，不得重命名。
SCAN_DIR = ROOT / "src" / "video_agent"
WHITELIST_BE = {"src/video_agent/state/models.py"}

# ===== 前端（src/web，*.ts/*.tsx）=====
# 扫描目录在 scan_frontend() 内按调用时的 ROOT 派生（尊重 canary 的 ROOT monkeypatch）。
FE_SUFFIXES = {".ts", ".tsx"}
# 永久合法出口：前端 CAT_* 常量定义处
WHITELIST_FE = {"src/web/lib/state-keys.ts"}
# 收缩型基线（只减不增）：存量合法点（类型联合位置 / subTab 页签标识）
BASELINE_FE = pathlib.Path(__file__).resolve().parent / "category_keys_frontend_baseline.txt"


def _is_fe_test(rel: str) -> bool:
    """测试夹具不在扫描面（与后端 tests/ 在扫描面外一致）。"""
    return "__tests__" in rel.split("/") or rel.endswith(".test.ts") or rel.endswith(".test.tsx")


def scan_backend() -> list:
    violations = []
    for p in sorted(SCAN_DIR.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel in WHITELIST_BE:
            continue
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if PATTERN.search(line):
                violations.append(f"  {rel}:{lineno}: {line.strip()[:90]}")
    return violations


def scan_frontend() -> dict:
    """返回前端产品代码中类别 Key 字面量的出现次数 {rel:literal -> count}。

    计数维度防「基线搭车」：同文件新增同类硬编码不再被既有条目吸收。
    扫描目录按调用时的 ROOT 派生，尊重 canary 对 ROOT 的 monkeypatch（临时 ROOT 下
    无 src/web 则返回空 dict，不干扰后端 canary 断言）。"""
    hits: dict = {}
    scan_dir = ROOT / "src" / "web"
    if not scan_dir.is_dir():
        return hits
    for p in sorted(scan_dir.rglob("*")):
        if p.suffix not in FE_SUFFIXES or not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel in WHITELIST_FE or _is_fe_test(rel):
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            for m in PATTERN.finditer(line):
                key = f"{rel}:{m.group(1)}"
                hits[key] = hits.get(key, 0) + 1
    return hits


def read_baseline_raw() -> list:
    """返回基线文件原始非空行（含注释头），用于 --refresh 保留文档注释。"""
    if not BASELINE_FE.exists():
        return []
    return [ln.rstrip() for ln in BASELINE_FE.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _parse_baseline_entry(line: str):
    """解析基线条目 -> (key, allowed_count)。

    现行格式 rel:literal:count（count = 允许出现次数上限）。旧格式 rel:literal
    无计数维度 -> allowed_count=0（fail-closed：任何出现都超限），迫使跑
    --refresh 迁移登记计数，不得继续以「无上限」吸收新增硬编码。
    """
    head, sep, tail = line.rpartition(":")
    if sep and tail.isdigit():
        return head, int(tail)
    return line, 0


def read_baseline() -> dict:
    """返回基线 {rel:literal -> 允许次数上限}（剔除注释头与空行）。"""
    out: dict = {}
    for ln in read_baseline_raw():
        if ln.lstrip().startswith("#"):
            continue
        key, count = _parse_baseline_entry(ln.strip())
        out[key] = count
    return out


def refresh_frontend_baseline() -> int:
    """只减不增：剔除已自然消失（产品代码改用 CAT_* 常量）的存量条目，
    计数只下调，绝不收编新增违规。保留注释头（# 开头行）。

    双向守卫（两侧都不得把「扫不动」当成「可清零」）：
      - 基线空 -> 拒绝（无从收缩，且会把全部存量误判为新增）；
      - 扫描空（如 src/web 缺失）-> 拒绝（否则全部存量条目被抹成注释头）。
    旧格式条目（allowed==0 仅来自旧格式）在本次刷新迁移登记为当前观测次数。
    """
    baseline = read_baseline()
    if not baseline:
        print(f"[check_category_keys] WARNING: frontend baseline missing or empty "
              f"({BASELINE_FE.name}); refuse to regenerate an empty allowlist "
              f"(would misjudge all existing entries as new violations). "
              f"Restore from git first.")
        return 1
    cur = scan_frontend()
    if not cur:
        print(f"[check_category_keys] WARNING: frontend scan returned zero hits "
              f"(src/web missing or unreadable); refuse to shrink the allowlist to "
              f"empty (would wipe all {len(baseline)} existing entries into the "
              f"comment header). Check the scan surface first.")
        return 1
    kept = []
    for key in sorted(baseline):
        observed = cur.get(key)
        if observed is None:
            continue  # 已自然消失 -> 剔除
        allowed = baseline[key]
        kept.append(f"{key}:{observed if allowed == 0 else min(allowed, observed)}")
    header = [ln for ln in read_baseline_raw() if ln.lstrip().startswith("#")]
    BASELINE_FE.write_text("\n".join(header + kept) + "\n", encoding="utf-8")
    print(f"[check_category_keys] frontend baseline shrink: {len(baseline)} -> {len(kept)} "
          f"entries (shrink-only; counts lowered only)")
    return 0


def main() -> int:
    if "--refresh" in sys.argv:
        return refresh_frontend_baseline()

    # fail-closed：后端扫描目录不存在 = 扫描面失效，不得当作「没有硬编码」。
    # （前端 src/web 缺失已由 refresh_frontend_baseline 的空扫描守卫拦下：
    #   拒绝把存量 allowlist 收缩为空。）
    surface = []
    if not SCAN_DIR.is_dir():
        try:
            rel_dir = SCAN_DIR.relative_to(ROOT).as_posix()
        except ValueError:
            rel_dir = str(SCAN_DIR)
        surface.append(f"  {rel_dir}: __missing_scan_dir__: declared backend scan dir "
                       f"missing (scan surface broken, not a pass)")

    be_violations = scan_backend()
    base = read_baseline()
    counts = scan_frontend()
    fe_over = sorted(
        ((k, c, base.get(k, 0)) for k, c in counts.items() if c > base.get(k, 0)),
        key=lambda t: t[0])

    if surface or be_violations or fe_over:
        if surface:
            print(f"[check_category_keys] FAIL - scan surface broken "
                  f"({len(surface)} problem(s)):")
            print("\n".join(surface))
            print("payoff: a missing scan dir means nothing was checked; that is never "
                  "evidence of compliance (fail-closed).")
        if be_violations:
            print(f"[check_category_keys] FAIL - backend category-key literals outside "
                  f"models.py ({len(be_violations)} hit(s)):")
            print("\n".join(be_violations))
            print("payoff: use CAT_KEY_ELEMENTS / CAT_SHOTS / CAT_AUDIO_ITEMS "
                  "from src.video_agent.state.models")
        if fe_over:
            print(f"[check_category_keys] FAIL - frontend category-key literals over "
                  f"baseline allowance ({len(fe_over)} key(s)):")
            for key, observed, allowed in fe_over:
                rel, literal = key.rsplit(":", 1)
                print(f"  {rel}: '{literal}' x{observed} (baseline allows {allowed})")
            print("payoff: import CAT_KEY_ELEMENTS / CAT_SHOTS / CAT_AUDIO_ITEMS "
                  "from '@/lib/state-keys'; legitimate type-union / subTab sites go "
                  "into scripts/category_keys_frontend_baseline.txt as "
                  "rel:literal:count (shrink-only; counts lowered only)")
        return 1

    print(f"[check_category_keys] PASS - backend clean (only models.py); "
          f"frontend clean (only state-keys.ts + {len(base)} counted baseline entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
