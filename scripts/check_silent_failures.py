#!/usr/bin/env python3
# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Pre-commit hook: ban silent failures.

A caught exception that is swallowed (not re-raised) must say WHY in the log,
loudly. Otherwise the failure is invisible: the caller sees a bland ``None`` /
``[]`` / early return and cannot tell "nothing to do" from "it broke". That is
not hypothetical — the PC's workout sync silently did nothing for weeks because
a missing token returned ``[]`` and a real error only logged at ``INFO``.

The rule: every ``except`` handler must either

* re-``raise`` (the failure is someone else's problem), or
* log at ``warning`` / ``error`` / ``exception`` / ``critical`` with the reason.

``debug`` / ``info`` do not count — an invisible log is a silent failure with
extra steps. ruff's ``S110`` only catches ``except: pass``; this catches the
far more common ``except: log.info(...); return []``.

There is deliberately no escape hatch (per-line lint suppressions are banned
repo-wide too): if a failure is truly benign, say so at ``warning`` and move on.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
import sys

_logger = logging.getLogger(__name__)

# Log levels loud enough that a human actually sees the failure.
_LOUD_LOG_METHODS = frozenset({"warning", "error", "exception", "critical"})


def _is_loud_log_call(node: ast.AST) -> bool:
    """Return True if ``node`` is a ``<something>.warning(...)``-style call."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _LOUD_LOG_METHODS
    )


def _handler_is_loud(handler: ast.ExceptHandler) -> bool:
    """Return True if the handler re-raises or logs loudly about the failure."""
    return any(
        isinstance(node, ast.Raise) or _is_loud_log_call(node)
        for node in ast.walk(handler)
    )


def _handler_label(handler: ast.ExceptHandler) -> str:
    """Return a readable name for what the handler catches."""
    if handler.type is None:
        return "except:"
    return f"except {ast.unparse(handler.type)}:"


def _check_source(path: Path, source: str) -> list[str]:
    """Return one message per silently-swallowing except handler in ``source``."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        _logger.warning(
            "Could not parse %s (%s at line %s) — reporting it as a problem "
            "rather than skipping it, since its handlers cannot be checked",
            path,
            exc.msg,
            exc.lineno,
        )
        return [f"{path}:{exc.lineno}: could not parse ({exc.msg})"]
    return [
        f"{path}:{node.lineno}: {_handler_label(node)} swallows the error without "
        f"logging why — re-raise, or log at warning/error/exception/critical"
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and not _handler_is_loud(node)
    ]


def main() -> int:
    """Return 1 if any file swallows an exception silently, else 0."""
    problems: list[str] = []
    for filename in sys.argv[1:]:
        path = Path(filename)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _logger.warning(
                "Could not read %s (%s) — reporting it as a problem rather than "
                "skipping it, since its handlers cannot be checked",
                path,
                exc,
            )
            problems.append(f"{path}: could not read ({exc})")
            continue
        problems.extend(_check_source(path, source))
    for problem in problems:
        sys.stdout.write(f"{problem}\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
