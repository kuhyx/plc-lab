#!/bin/bash

# ============================================================================
# Fail if any file in the commit exceeds the shared 250-line cap.
#
# Thin delegate to the shared gate in ~/src/utils, which owns the cap and the
# exemption list (generated / vendored / data files). This repo previously ran
# a LOCAL check_file_length.py with its own higher limit, so it reported
# "gated" while permitting files every other repo rejects -- which is why its
# violations went untouched. Delegating is what stops that recurring.
#
# Usage:
#   scripts/check_file_length.sh <file> [<file> ...]   # pre-commit passes these
#   scripts/check_file_length.sh --all                 # whole tree, from cwd
# ============================================================================

set -euo pipefail

readonly SHARED_GATE="${UTILS_ROOT:-$HOME/src/utils}/scripts/check_file_length.sh"

main() {
    if [[ ! -x "$SHARED_GATE" ]]; then
        echo "Error: shared file-length gate not found at $SHARED_GATE" >&2
        echo "       Clone github.com/kuhyx/utils to ~/src/utils, or set" >&2
        echo "       UTILS_ROOT to where it lives." >&2
        exit 1
    fi

    exec bash "$SHARED_GATE" "$@"
}

main "$@"
