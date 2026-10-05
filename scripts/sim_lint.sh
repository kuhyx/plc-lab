#!/bin/bash

# ============================================================================
# sim_lint.sh -- gdlint (every check, sim/.gdlintrc), gdformat --check, then
# a headless parse of every script with GDScript warnings promoted to errors
# (sim/project.godot), so an untyped declaration fails here, not at runtime.
# ============================================================================

set -euo pipefail

SIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../sim" && pwd)"
readonly SIM_DIR
readonly VENV="$SIM_DIR/../.venv"

parse_gate() {
    local failed=0 output file
    while IFS= read -r -d '' file; do
        output="$(godot --headless --path "$SIM_DIR" --check-only -s "res://${file#"$SIM_DIR"/}" 2>&1 \
            | grep -v '^Godot Engine' || true)"
        if [[ -n "$output" ]]; then
            printf '%s\n' "$output" >&2
            failed=1
        fi
    done < <(find "$SIM_DIR/scripts" "$SIM_DIR/tests" -name '*.gd' -print0 | sort -z)
    return "$failed"
}

main() {
    cd "$SIM_DIR"
    "$VENV/bin/gdlint" scripts tests
    "$VENV/bin/gdformat" --check scripts tests
    # Refresh the class cache first: a new script is otherwise "Could not
    # find type X" in every file that uses it.
    godot --headless --path "$SIM_DIR" --import >/dev/null 2>&1 || true
    if ! parse_gate; then
        echo "sim lint: headless parse reported warnings-as-errors" >&2
        exit 1
    fi
    echo "sim lint: ok"
}

main "$@"
