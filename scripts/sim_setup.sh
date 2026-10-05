#!/bin/bash

# ============================================================================
# sim_setup.sh -- tooling for the Godot sorting line in sim/: GUT (cloned at a
# pinned tag into sim/addons/gut, gitignored) and Godot's import cache, so
# headless runs resolve class_name. gdtoolkit comes with the dev venv
# (scripts/setup_dev.sh). Idempotent; rerun after a pull.
# ============================================================================

set -euo pipefail

SIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../sim" && pwd)"
readonly SIM_DIR
readonly GUT_TAG="v9.7.1"   # newest tag; not tracked by the freshness gate

ensure_godot() {
    if ! command -v godot >/dev/null 2>&1; then
        echo "godot not found: install Godot 4.7 (pacman -S godot)" >&2
        exit 1
    fi
}

ensure_gut() {
    local gut_dir="$SIM_DIR/addons/gut" tmp
    if [[ -f "$gut_dir/plugin.cfg" ]] && grep -q "${GUT_TAG#v}" "$gut_dir/plugin.cfg"; then
        return
    fi
    echo "Installing GUT ${GUT_TAG}..."
    rm -rf "$gut_dir"
    tmp="$(mktemp -d)"
    git clone -q --depth 1 --branch "$GUT_TAG" https://github.com/bitwes/Gut "$tmp"
    mkdir -p "$SIM_DIR/addons"
    mv "$tmp/addons/gut" "$gut_dir"
    rm -rf "$tmp"
}

main() {
    ensure_godot
    ensure_gut
    # Builds sim/.godot (class cache) so headless runs resolve class_name.
    godot --headless --path "$SIM_DIR" --import >/dev/null 2>&1 || true
    echo "sim: ready. Run: godot --path sim -- --mock --autostart"
}

main "$@"
