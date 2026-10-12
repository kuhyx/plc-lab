#!/bin/bash

# ============================================================================
# The Automation tutor moved to its own repo, ~/src/tutor (2026-10-12).
#
# Kept as a forwarder because the i3 bar (linux_configuration
# i3blocks/automation_tutor.sh) and the control panel's automation-tutor
# manifest still call this path. Drop it once both point at ~/src/tutor.
# ============================================================================

set -euo pipefail

readonly TUTOR_RUN="${TUTOR_REPO:-$HOME/src/tutor}/run.sh"

exec "$TUTOR_RUN" "$@"
