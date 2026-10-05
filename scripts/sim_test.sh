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
godot --headless --path "$SIM_DIR" -s addons/gut/gut_cmdln.gd \
    -gdir=res://tests -ginclude_subdirs -gexit
