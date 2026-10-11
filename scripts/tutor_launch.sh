#!/bin/bash

# ============================================================================
# Start a tutor server from a release dir, detached from the caller.
#
# Usage: tutor_launch.sh <release-dir> <port> <log-file>
#
# The server gets its own systemd user unit, so it outlives whatever started
# it: a setsid'd child stays in the caller's cgroup, and a capped or
# time-limited caller (a Claude Bash call) took the live server down with it
# when its scope was torn down (2026-10-11, SIGTERM mid-answer). Falls back to
# setsid where there is no user systemd (CI). AUTOMATION_TUTOR_* and PATH are
# passed through, since a unit does not inherit the caller's environment.
# AUTOMATION_TUTOR_DECK_SRC (the repo deck/ the card editor writes) is set by
# the callers; unset or empty, the editor is read-only.
# ============================================================================

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
readonly REPO
readonly PY="$REPO/.venv/bin/python"

main() {
    local dir="$1" port="$2" log="$3" var
    local -a env_args=(--setenv=PATH="$PATH")
    for var in AUTOMATION_TUTOR_DATA AUTOMATION_TUTOR_KEY AUTOMATION_TUTOR_IMAGE_CACHE \
        AUTOMATION_TUTOR_DECK_SRC; do
        if [[ -n "${!var:-}" ]]; then
            env_args+=(--setenv="$var=${!var}")
        fi
    done
    if systemctl --user show-environment >/dev/null 2>&1; then
        systemd-run --user --quiet --collect \
            --unit="automation-tutor-$port-$(date +%s%N)" \
            --working-directory="$dir" "${env_args[@]}" \
            -p StandardOutput="append:$log" -p StandardError="append:$log" \
            "$PY" -m plc_lab.tutor --port "$port"
    else
        (cd "$dir" && exec setsid -f "$PY" -m plc_lab.tutor --port "$port" \
            >>"$log" 2>&1 </dev/null)
    fi
}

main "$@"
