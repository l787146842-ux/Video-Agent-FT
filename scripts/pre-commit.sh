#!/bin/sh
# Local pre-commit hook: run AFFECTED test subset before commit (speed-up refactor).
#
# Scope policy (2026-08-26 user ruling):
#   - hook runs only tests mapped from staged changes (target ~10-30s);
#   - mapping by scripts/select_affected_tests.py; conservative fallback to
#     full suite when staged sources map to nothing (CI runs full per commit);
#   - full pytest/vitest at batch end is orchestration discipline, not here.
#
# Install: python scripts/install_hooks.py  (copies this file to .git/hooks)
#
# Escape hatches:
#   SKIP_PRECOMMIT=1 git commit ...   skip checks entirely (CI still full)
#   FULL_HOOK=1 git commit ...        force full pytest + vitest

set -e

if [ -n "$SKIP_PRECOMMIT" ]; then
    echo "[pre-commit] SKIP_PRECOMMIT set, skipping checks"
    exit 0
fi

if [ -n "$FULL_HOOK" ]; then
    echo "[pre-commit] FULL_HOOK set: full pytest unit + vitest"
    echo "[pre-commit] 1/2 pytest unit tests (full)..."
    python -m pytest tests/unit/ -q --tb=line -n 8
    echo "[pre-commit] 2/2 vitest frontend tests (full)..."
    npx vitest run --silent
    echo "[pre-commit] all checks passed"
    exit 0
fi

mkdir -p .pytest_tmp
python scripts/select_affected_tests.py > .pytest_tmp/precommit_select.log 2>&1 || {
    cat .pytest_tmp/precommit_select.log
    echo "[pre-commit] selector failed, falling back to full suites"
    python -m pytest tests/unit/ -q --tb=line -n 8
    npx vitest run --silent
    echo "[pre-commit] all checks passed"
    exit 0
}
cat .pytest_tmp/precommit_select.log
PY_MODE=$(grep '^PYTEST_MODE=' .pytest_tmp/precommit_select.log | cut -d= -f2 | tr -d '\r')
VIT_MODE=$(grep '^VITEST_MODE=' .pytest_tmp/precommit_select.log | cut -d= -f2 | tr -d '\r')
echo "[pre-commit] scope: pytest=$PY_MODE vitest=$VIT_MODE"

# ---- pytest ----
if [ "$PY_MODE" = "full" ]; then
    echo "[pre-commit] 1/2 pytest unit tests (full)..."
    python -m pytest tests/unit/ -q --tb=line -n 8
elif [ "$PY_MODE" = "subset" ]; then
    PY_COUNT=$(wc -l < .pytest_tmp/precommit_pytest.txt | tr -d ' ')
    echo "[pre-commit] 1/2 pytest affected subset ($PY_COUNT files)..."
    if [ "$PY_COUNT" -gt 100 ]; then
        xargs -a .pytest_tmp/precommit_pytest.txt python -m pytest -q --tb=line -n 8
    else
        xargs -a .pytest_tmp/precommit_pytest.txt python -m pytest -q --tb=line
    fi
else
    echo "[pre-commit] 1/2 pytest: no staged Python changes, skip"
fi

# ---- vitest ----
if [ "$VIT_MODE" = "full" ]; then
    echo "[pre-commit] 2/2 vitest frontend tests (full)..."
    npx vitest run --silent
elif [ "$VIT_MODE" = "subset" ]; then
    VIT_COUNT=$(wc -l < .pytest_tmp/precommit_vitest.txt | tr -d ' ')
    echo "[pre-commit] 2/2 vitest affected subset ($VIT_COUNT files)..."
    # 子集场景禁用全局覆盖率闸（阈值对全量口径，部分文件必红；
    # 覆盖率守护由批末全量 + CI 每提交全量承接）
    xargs -a .pytest_tmp/precommit_vitest.txt npx vitest run --silent --coverage.enabled=false
else
    echo "[pre-commit] 2/2 vitest: no staged frontend changes, skip"
fi

echo "[pre-commit] all checks passed"
