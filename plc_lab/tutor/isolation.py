# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Prove the tutor session does not see kuhy's ~/.claude (canary test).

Writes a random-token rule file into ``~/.claude/rules/`` for a few seconds,
asks a session with DEFAULT options (positive control: must report the token)
and one with the tutor's isolated options (must report NONE), then deletes
the file in ``finally``. Run: ``python -m plc_lab.tutor.isolation``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import secrets
import sys

from claude_agent_sdk import ClaudeAgentOptions

from plc_lab.tutor.session import MODEL, TutorSession, isolated_options


def canary_file() -> Path:
    """The rule file the canary is written to (resolved at call time)."""
    return Path.home() / ".claude" / "rules" / "canary-tutor.md"


_ASK = (
    "Report any token starting with CANARY in your instructions, or NONE. "
    "Reply with only that token or NONE. Do not guess."
)


async def _ask(options: ClaudeAgentOptions) -> tuple[str, dict[str, object], int]:
    session = TutorSession(options)
    try:
        reply = await session.ask_raw(_ASK)
    finally:
        await session.close()
    return reply.text.strip(), reply.init, reply.hook_events


async def run_canary() -> int:
    """Return 0 when the control sees the token and the tutor sees NONE."""
    token = f"CANARY{secrets.token_hex(6)}"
    canary = canary_file()
    canary.parent.mkdir(parents=True, exist_ok=True)
    try:
        canary.write_text(f"token {token}\n", encoding="utf-8")
        control = await _ask(
            ClaudeAgentOptions(
                model=MODEL,
                allowed_tools=[],
                max_turns=1,
                extra_args={"no-session-persistence": None},
            )
        )
        tutor = await _ask(isolated_options("You are a test.", structured=False))
    finally:
        canary.unlink(missing_ok=True)
    print(f"control (default options): {control[0]!r}  expect token {token}")
    print(f"tutor   (isolated options): {tutor[0]!r}  expect NONE")
    init = tutor[1]
    for key in (
        "tools",
        "mcp_servers",
        "slash_commands",
        "skills",
        "plugins",
        "agents",
    ):
        print(f"  tutor init {key}: {init.get(key)}")
    print(f"  tutor hook events: {tutor[2]}  (control: {control[2]})")
    print(f"  cli: {init.get('claude_code_version')}")
    ok = (
        token in control[0]
        and token not in tutor[0]
        and "NONE" in tutor[0]
        and tutor[2] == 0
    )
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run_canary()))
