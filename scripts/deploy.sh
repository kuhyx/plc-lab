#!/bin/bash
# Deploy plc-lab: the Automation deck is the only thing of this repo that runs
# anywhere (AnkiDroid syncs it from the self-hosted anki-syncserver). Check
# every card against its source, build the package, import it into the sync
# server. Idempotent: note ids are stable, so a rerun updates in place. The
# import exits non-zero unless a fresh download shows the server has the deck.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_DIR
readonly VENV_PY="${REPO_DIR}/.venv/bin/python"
# System python: anki 25.09.2 lives there, not in the dev venv.
readonly SYSTEM_PY="/usr/bin/python3"

cd "${REPO_DIR}"
if [[ ! -x "${VENV_PY}" ]]; then
    scripts/setup_dev.sh
fi
"${SYSTEM_PY}" -c 'import anki' 2>/dev/null ||
    "${SYSTEM_PY}" -m pip install --user --break-system-packages 'anki==25.9.2'
systemctl --user is-active --quiet anki-syncserver.service

"${VENV_PY}" -m plc_lab check
"${VENV_PY}" -m plc_lab build
"${SYSTEM_PY}" scripts/import_to_server.py "$@"
