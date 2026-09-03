"""前端类别 Key 门禁 canary（前端批次1：check_category_keys 扩面到 src/web）。

与 tests/unit/test_gate_canaries.py 的后端 category_keys canary 同源双向断言，但独立成文
（test_gate_canaries.py 由他路独占，本文件只覆盖前端扩面 + 收缩型基线行为）。

断言门禁的真实牙齿：
- 产品代码裸字面量、未在收缩型基线登记 -> 失败；
- 已登记基线 / 永久出口 state-keys.ts / 测试夹具 __tests__ -> 放行；
- rel:literal 粒度：同一文件出现未登记的新字面量仍失败；
- rel:literal:count 次数维度：同文件同类硬编码出现数超基线上限 -> 失败（防基线搭车）；
- 旧格式条目（无 count）fail-closed 视为上限 0 -> 失败，迫使 --refresh 迁移登记；
- --refresh 只减不增：剔除已消失条目、计数只下调，绝不收编新增违规；
- --refresh 双向守卫：基线空 或 扫描空（src/web 缺失）均拒绝，不把存量抹成注释头。
"""
import sys

import scripts.check_category_keys as gate


def _scaffold(tmp_path, monkeypatch, fe_files, baseline_lines=None, create_web=True):
    """搭建临时 ROOT：空后端扫描面 + 指定前端文件 + 指定收缩型基线。

    create_web=False 用于模拟 src/web 缺失（扫描面失效）的 fail-closed 守卫断言。
    """
    root = tmp_path
    be = root / "src" / "video_agent"
    be.mkdir(parents=True)
    web = root / "src" / "web"
    if create_web:
        web.mkdir(parents=True)
    for rel, text in fe_files.items():
        f = web / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    baseline = tmp_path / "category_keys_frontend_baseline.txt"
    baseline.write_text("\n".join(baseline_lines or []) + "\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", root)
    monkeypatch.setattr(gate, "SCAN_DIR", be)
    monkeypatch.setattr(gate, "BASELINE_FE", baseline)
    return gate


def test_frontend_literal_outside_baseline_fails(tmp_path, monkeypatch):
    _scaffold(tmp_path, monkeypatch, {"lib/foo.ts": "export const x = 'audioItems';\n"})
    assert gate.main() == 1


def test_frontend_literal_in_baseline_passes(tmp_path, monkeypatch):
    _scaffold(
        tmp_path, monkeypatch,
        {"lib/foo.ts": "export const x = 'audioItems';\n"},
        baseline_lines=["src/web/lib/foo.ts:audioItems:1"],
    )
    assert gate.main() == 0


def test_frontend_whitelist_exit_passes(tmp_path, monkeypatch):
    # state-keys.ts 是永久合法出口（WHITELIST_FE），裸字面量无需登记基线
    _scaffold(
        tmp_path, monkeypatch,
        {"lib/state-keys.ts": "export const CAT_SHOTS = 'shots' as const;\n"},
    )
    assert gate.main() == 0


def test_frontend_test_fixture_excluded(tmp_path, monkeypatch):
    # __tests__ / *.test.ts(x) 不在扫描面（与后端 tests/ 在扫描面外一致）
    _scaffold(
        tmp_path, monkeypatch,
        {
            "stores/__tests__/a.test.ts": "setState('keyElements', []);\n",
            "lib/b.test.tsx": "const x = 'shots';\n",
        },
    )
    assert gate.main() == 0


def test_frontend_new_literal_in_baselined_file_fails(tmp_path, monkeypatch):
    # rel:literal 粒度：同文件已登记 'shots'，新增 'audioItems' 仍判失败
    _scaffold(
        tmp_path, monkeypatch,
        {"lib/foo.ts": "const a = 'shots';\nconst b = 'audioItems';\n"},
        baseline_lines=["src/web/lib/foo.ts:shots:1"],
    )
    assert gate.main() == 1


def test_frontend_constant_usage_passes(tmp_path, monkeypatch):
    # 产品代码改用 CAT_* 常量（无裸字面量）-> 放行
    _scaffold(
        tmp_path, monkeypatch,
        {"lib/foo.ts": "import { CAT_SHOTS } from '@/lib/state-keys';\nexport const x = CAT_SHOTS;\n"},
    )
    assert gate.main() == 0


def test_refresh_shrink_only(tmp_path, monkeypatch):
    # --refresh 只减不增：剔除已消失条目，保留仍在条目，绝不收编新增违规
    baseline = _scaffold(
        tmp_path, monkeypatch,
        {
            "lib/foo.ts": "const a = 'shots';\n",        # 仍在 -> 保留
            "lib/new.ts": "const b = 'audioItems';\n",   # 新增违规 -> 不得收编
        },
        baseline_lines=[
            "src/web/lib/foo.ts:shots:1",
            "src/web/lib/gone.ts:keyElements:1",         # 已消失 -> 剔除
        ],
    ).BASELINE_FE
    monkeypatch.setattr(sys, "argv", ["check_category_keys.py", "--refresh"])
    assert gate.main() == 0
    kept = baseline.read_text(encoding="utf-8").splitlines()
    assert "src/web/lib/foo.ts:shots:1" in kept
    assert "src/web/lib/gone.ts:keyElements:1" not in kept
    assert not [ln for ln in kept if "new.ts" in ln], "新增违规不得被收编"


def test_refresh_refuses_empty_baseline(tmp_path, monkeypatch):
    # 基线为空时拒绝刷新（防把全部存量误判为新增）
    _scaffold(tmp_path, monkeypatch, {"lib/foo.ts": "const a = 'shots';\n"}, baseline_lines=[])
    monkeypatch.setattr(sys, "argv", ["check_category_keys.py", "--refresh"])
    assert gate.main() == 1


# ---------- 次数维度（防「基线搭车」） ----------

def test_frontend_count_over_baseline_fails(tmp_path, monkeypatch):
    # FAIL 侧：同文件同类硬编码出现数超基线上限 -> 失败（旧 set 键会静默吸收）
    _scaffold(
        tmp_path, monkeypatch,
        {"lib/foo.ts": "const a = 'shots';\nconst b = 'shots';\n"},
        baseline_lines=["src/web/lib/foo.ts:shots:1"],
    )
    assert gate.main() == 1


def test_frontend_count_within_baseline_passes(tmp_path, monkeypatch):
    # PASS 侧：出现数在上限内 -> 放行（不反噬）
    _scaffold(
        tmp_path, monkeypatch,
        {"lib/foo.ts": "const a = 'shots';\nconst b = 'shots';\n"},
        baseline_lines=["src/web/lib/foo.ts:shots:2"],
    )
    assert gate.main() == 0


def test_frontend_legacy_entry_without_count_fails(tmp_path, monkeypatch):
    # FAIL 侧：旧格式条目无计数维度 -> fail-closed 视为上限 0，迫使 --refresh 迁移
    _scaffold(
        tmp_path, monkeypatch,
        {"lib/foo.ts": "const a = 'shots';\n"},
        baseline_lines=["src/web/lib/foo.ts:shots"],
    )
    assert gate.main() == 1


def test_refresh_migrates_legacy_counts(tmp_path, monkeypatch):
    # --refresh 把旧格式条目迁移登记为当前观测次数（键集不扩张）
    baseline = _scaffold(
        tmp_path, monkeypatch,
        {"lib/foo.ts": "const a = 'shots';\nconst b = 'shots';\n"},
        baseline_lines=["src/web/lib/foo.ts:shots"],
    ).BASELINE_FE
    monkeypatch.setattr(sys, "argv", ["check_category_keys.py", "--refresh"])
    assert gate.main() == 0
    kept = baseline.read_text(encoding="utf-8").splitlines()
    assert "src/web/lib/foo.ts:shots:2" in kept


def test_refresh_never_raises_count(tmp_path, monkeypatch):
    # 计数只下调：观测数超上限时 --refresh 绝不把上限抬到观测值（不收编增长）
    baseline = _scaffold(
        tmp_path, monkeypatch,
        {"lib/foo.ts": "const a = 'shots';\nconst b = 'shots';\nconst c = 'shots';\n"},
        baseline_lines=["src/web/lib/foo.ts:shots:1"],
    ).BASELINE_FE
    monkeypatch.setattr(sys, "argv", ["check_category_keys.py", "--refresh"])
    assert gate.main() == 0
    kept = baseline.read_text(encoding="utf-8").splitlines()
    assert "src/web/lib/foo.ts:shots:1" in kept
    assert "src/web/lib/foo.ts:shots:3" not in kept


def test_refresh_lowers_count_when_cleaned(tmp_path, monkeypatch):
    # 部分清偿后 --refresh 下调计数（只减）
    baseline = _scaffold(
        tmp_path, monkeypatch,
        {"lib/foo.ts": "const a = 'shots';\n"},
        baseline_lines=["src/web/lib/foo.ts:shots:3"],
    ).BASELINE_FE
    monkeypatch.setattr(sys, "argv", ["check_category_keys.py", "--refresh"])
    assert gate.main() == 0
    kept = baseline.read_text(encoding="utf-8").splitlines()
    assert "src/web/lib/foo.ts:shots:1" in kept


# ---------- --refresh 扫描空守卫（不得把「扫不动」当成「可清零」） ----------

def test_refresh_refuses_empty_scan(tmp_path, monkeypatch):
    # FAIL 侧：src/web 缺失 -> 扫描空集，拒绝把全部存量条目抹成注释头
    baseline = _scaffold(
        tmp_path, monkeypatch, {},
        baseline_lines=["src/web/lib/foo.ts:shots:1"],
        create_web=False,
    ).BASELINE_FE
    monkeypatch.setattr(sys, "argv", ["check_category_keys.py", "--refresh"])
    assert gate.main() == 1
    kept = [ln for ln in baseline.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]
    assert kept == ["src/web/lib/foo.ts:shots:1"], "扫描空时不得收缩基线"


def test_refresh_proceeds_when_scan_nonempty(tmp_path, monkeypatch):
    # PASS 侧：扫描面正常时 --refresh 照常收缩（不反噬）
    baseline = _scaffold(
        tmp_path, monkeypatch,
        {"lib/foo.ts": "const a = 'shots';\n"},
        baseline_lines=["src/web/lib/foo.ts:shots:1", "src/web/lib/gone.ts:shots:1"],
    ).BASELINE_FE
    monkeypatch.setattr(sys, "argv", ["check_category_keys.py", "--refresh"])
    assert gate.main() == 0
    kept = [ln for ln in baseline.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]
    assert kept == ["src/web/lib/foo.ts:shots:1"]
