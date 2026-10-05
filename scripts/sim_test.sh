#!/bin/bash

# ============================================================================
# sim_test.sh -- every GUT test in sim/tests (unit + integration), headless.
# ============================================================================

set -euo pipefail

SIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../sim" && pwd)"
readonly SIM_DIR

if [[ ! -f "$SIM_DIR/addons/gut/gut_cmdln.gd" ]]; then
    echo "GUT missing: run scripts/sim_setup.sh" >&2
    exit 1
fi
# Test dirs live in sim/.gutconfig.json, so the bare gut_cmdln command works too.
godot --headless --path "$SIM_DIR" -s addons/gut/gut_cmdln.gd -gexit
