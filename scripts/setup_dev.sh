#!/bin/bash
# ============================================================================
# setup_dev.sh -- the dev venv the pre-commit gate and the test suite run in.
#
# .venv holds plc-lab (editable)
# plus the pinned test and lint tools. Idempotent.
# ============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_DIR
readonly VENV="${REPO_DIR}/.venv"

if [[ ! -x "${VENV}/bin/python" ]]; then
    python3 -m venv "$VENV"
fi
"${VENV}/bin/python" -m pip install --quiet --upgrade pip
"${VENV}/bin/python" -m pip install --quiet -e "${REPO_DIR}[dev]"
"${VENV}/bin/python" -c "import plc_lab, genanki, pytest, mypy, pylint; print('dev venv OK')"
