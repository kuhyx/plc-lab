# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""``python3 -m plc_lab``: see :mod:`plc_lab.cli`."""

from __future__ import annotations

import sys

from plc_lab.cli import main

__all__ = ["main"]

if __name__ == "__main__":
    sys.exit(main())
