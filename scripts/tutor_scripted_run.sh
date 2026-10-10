#!/bin/bash

# ============================================================================
# Scripted tutor run: a simulated know-nothing learner drives the real tutor
# over HTTP against a SANDBOXED data dir and ledger key (no real gaming time
# is minted), then the transcript is adjudicated by code and the page is
# screenshotted headlessly. The server is left running only until the end.
# ============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
readonly ROOT
readonly RUN="$ROOT/build/tutor-run"
readonly PORT="${TUTOR_PORT:-8779}"
readonly PY="$ROOT/.venv/bin/python"
SERVER_PID=""

cleanup() {
    if [[ -n "$SERVER_PID" ]]; then
        kill "$SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

mkdir -p "$RUN/data" "$ROOT/build/tutor-screenshots"
rm -rf "${RUN:?}/data"
mkdir -p "$RUN/data"
head -c 32 /dev/urandom | base64 > "$RUN/test.key"
export AUTOMATION_TUTOR_DATA="$RUN/data"
export AUTOMATION_TUTOR_KEY="$RUN/test.key"

"$PY" -m plc_lab.tutor --port "$PORT" --simulate-time 2> "$RUN/server.log" &
SERVER_PID=$!
for _ in {1..40}; do
    curl -sf "http://127.0.0.1:$PORT/api/state" > /dev/null && break
    sleep 0.5
done

# The chromium wrapper returns before the PNG exists; the pipe waits for its
# "bytes written" line, so the server is never killed mid-screenshot.
# The run ends with Stop here, so the final shots open the stopped session by id.
shot() {  # shot <name> <anchor>: headless, temp profile, never the live display
    chromium --headless=new --no-sandbox --user-data-dir="$(mktemp -d)" --disable-gpu \
        --hide-scrollbars --window-size=1280,1000 --virtual-time-budget=6000 \
        --screenshot="$ROOT/build/tutor-screenshots/$1.png" \
        "http://127.0.0.1:$PORT/#$2" 2>&1 | grep -q "bytes written"
}
export -f shot
export ROOT PORT

"$PY" -m plc_lab.tutor.scripted --url "http://127.0.0.1:$PORT" \
    --hook-after 7 --hook-cmd 'shot session-mid m14' "$@"

session="$(ls -t "$RUN"/data/sessions/*.jsonl | head -1)"
cp "$session" "$ROOT/build/tutor-screenshots/transcript.jsonl"
"$PY" -m plc_lab.tutor.adjudicate "$session" | tee "$ROOT/build/tutor-screenshots/adjudication.txt" || true

sid="$(basename "$session" .jsonl)"
for name in image diagram last; do
    anchor="$("$PY" -m plc_lab.tutor.adjudicate --anchors "$session" | jq -r ".$name")"
    shot "session-$name" "$sid/$anchor"
done
echo "screenshots in $ROOT/build/tutor-screenshots/"
