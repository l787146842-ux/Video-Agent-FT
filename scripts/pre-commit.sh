#!/bin/sh
# Local pre-commit hook (plan P1-3): run fast test subset before commit.
#
# Install (one-time): copy this file to .git/hooks/pre-commit
#   Windows PowerShell:  Copy-Item scripts/pre-commit.sh .git/hooks/pre-commit
#   Linux/macOS:         cp scripts/pre-commit.sh .git/hooks/pre-commit
#
# Escape hatch: SKIP_PRECOMMIT=1 git commit ...  (CI still runs full checks)

set -e

if [ -n "$SKIP_PRECOMMIT" ]; then
    echo "[pre-commit] SKIP_PRECOMMIT set, skipping checks"
    exit 0
fi

echo "[pre-commit] 1/2 pytest unit tests..."
python -m pytest tests/unit/ -q --tb=line
echo "[pre-commit] 2/2 vitest frontend tests..."
npx vitest run --silent

echo "[pre-commit] all checks passed"