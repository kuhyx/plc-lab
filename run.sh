#!/bin/bash

# ============================================================================
# Open the Automation tutor (the +1 h gaming / +60 min shutdown earner).
#
# If the live server answers, just open it. Otherwise start it from the frozen
# live release (never the working tree), deploying one first if none exists.
# The server is detached, so closing this terminal never kills a session
# mid-block. Clicked from the i3 bar and the control panel too.
# ============================================================================

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO
readonly PY="$REPO/.venv/bin/python"
readonly PORT="${TUTOR_PORT:-8778}"
readonly URL="http://127.0.0.1:$PORT/"
readonly LIVE_ROOT="${TUTOR_LIVE_ROOT:-$HOME/.local/lib/automation-tutor-live}"
readonly LOG_DIR="${TUTOR_LOG_DIR:-$HOME/.local/state/automation_tutor}"
OPEN=1

usage() {
    echo "Usage: $(basename "$0") [--no-open]"
    echo "  --no-open   start the tutor if needed and print its URL only"
    exit 0
}

is_up() {
    curl -sf -m 2 "${URL}api/state" >/dev/null
}

wait_up() {
    local _
    for _ in {1..40}; do
        is_up && return 0
        sleep 0.5
    done
    return 1
}

# Same detached launch as scripts/tutor_deploy.sh, from the current release.
start_server() {
    if [[ ! -d "$LIVE_ROOT/current" ]]; then
        echo "No live release yet; deploying one."
        "$REPO/scripts/tutor_deploy.sh" --port "$PORT"
        return
    fi
    mkdir -p "$LOG_DIR"
    (cd "$LIVE_ROOT/current" && exec setsid -f "$PY" -m plc_lab.tutor \
        --port "$PORT" >>"$LOG_DIR/server.log" 2>&1 </dev/null)
}

main() {
    if is_up; then
        echo "Tutor already running."
    else
        echo "Starting tutor from $(readlink -f "$LIVE_ROOT/current" || echo 'a new release')..."
        start_server
        wait_up || { echo "Tutor did not start; see $LOG_DIR/server.log" >&2; exit 1; }
    fi
    echo "Tutor: $URL"
    if [[ $OPEN -eq 1 ]]; then
        setsid -f xdg-open "$URL" >/dev/null 2>&1
    fi
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-open) OPEN=0; shift ;;
        -h | --help) usage ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

main
