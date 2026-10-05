#!/bin/bash

# ============================================================================
# Run only the tests related to files changed vs HEAD (staged, unstaged and
# untracked). Quiet: failures plus a one-line summary. Falls back to the full
# suite when a change cannot be mapped to a test file.
# ============================================================================

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
readonly PY=".venv/bin/python"
full=0 touched=0
tests=()

while IFS= read -r f; do
    [[ -n "$f" && -e "$f" ]] || continue
    case "$f" in
        pyproject.toml | */conftest.py | plc_lab/tests/_*.py) full=1; touched=1 ;;
        plc_lab/tests/test_*.py) touched=1; tests+=("$f") ;;
        plc_lab/*.py)
            touched=1
            base="$(basename "$f" .py)"
            t="plc_lab/tests/test_${base#_}.py"
            if [[ -f "$t" ]]; then tests+=("$t"); else full=1; fi
            ;;
    esac
done < <({ git diff --name-only HEAD 2>/dev/null || git ls-files; git ls-files --others --exclude-standard; } | sort -u)

if [[ $touched -eq 0 ]]; then
    echo "no python changes vs HEAD: nothing to test"; exit 0
fi
rc=0
if [[ $full -eq 1 ]]; then
    echo "python: running full suite"
    "$PY" -m pytest -q --tb=short || rc=1
else
    mapfile -t uniq < <(printf '%s\n' "${tests[@]}" | sort -u)
    echo "python: ${#uniq[@]} test file(s)"
    "$PY" -m pytest -q --tb=short --no-cov "${uniq[@]}" || rc=1
fi
[[ $rc -eq 0 ]] && echo "test-changed: pass" || echo "test-changed: FAIL"
exit $rc
