# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""One isolated Claude conversation, driven through ``claude-agent-sdk``.

The SDK spawns the ``claude`` CLI, which by default loads the user's CLAUDE.md,
rules, hooks, skills and MCP servers. :func:`isolated_options` turns every one
of those off; ``isolation.py`` proves it with a canary instead of trusting it.
The conversation lives in one long-lived task: the SDK's task group must be
entered and left by the same task, and a web request is not that.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
)

from plc_lab.tutor.models import TURN_SCHEMA, TurnError, TutorTurn

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# A user message: plain text, or content blocks (text + base64 images).
Prompt = str | list[dict[str, Any]]

# The SDK's own ``effort`` values (``ClaudeAgentOptions.effort``).
Effort = Literal["low", "medium", "high", "xhigh", "max"]

MODEL: Final = "claude-sonnet-5-5"
_TURN_TIMEOUT: Final = 240.0
_logger = logging.getLogger(__name__)


class SessionError(RuntimeError):
    """The model could not produce a valid turn."""


def sandbox_dir() -> Path:
    """The model's empty working directory (resolved at call time)."""
    return Path.home() / ".local" / "share" / "automation_tutor" / "sandbox"


def isolated_options(
    system_prompt: str,
    *,
    model: str = MODEL,
    structured: bool = True,
    cwd: Path | None = None,
    effort: Effort = "medium",
) -> ClaudeAgentOptions:
    """Options with no user/project settings, tools, hooks, MCP or skills.

    ``structured`` asks for a :data:`TURN_SCHEMA` object; off for free text.
    """
    cwd = cwd or sandbox_dir()
    cwd.mkdir(parents=True, exist_ok=True)
    return ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt,
        tools=[],
        allowed_tools=[],
        setting_sources=[],
        strict_mcp_config=True,
        mcp_servers={},
        cwd=cwd,
        include_hook_events=True,
        output_format=(
            {"type": "json_schema", "schema": TURN_SCHEMA} if structured else None
        ),
        effort=effort,
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "DISABLE_TELEMETRY": "1"},
        extra_args={"disable-slash-commands": None, "no-session-persistence": None},
    )


@dataclass
class Reply:
    """What one model call returned, plus what proves how it was configured."""

    structured: Any
    text: str
    init: dict[str, Any]
    hook_events: int
    cost_usd: float


def _collect(client_msgs: list[Any]) -> Reply:
    structured: Any = None
    text = ""
    init: dict[str, Any] = {}
    hooks = 0
    cost = 0.0
    for msg in client_msgs:
        if isinstance(msg, SystemMessage):
            if msg.subtype == "init":
                init = dict(msg.data)
            elif "hook" in msg.subtype:
                hooks += 1
        elif isinstance(msg, ResultMessage):
            if msg.is_error:
                detail = f"model error: {msg.subtype} {msg.errors} {msg.result}"
                raise SessionError(detail)
            structured = msg.structured_output
            text = msg.result or ""
            cost = msg.total_cost_usd or 0.0
    return Reply(structured, text, init, hooks, cost)


async def _blocks(content: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    """One streamed user message carrying content blocks (how images go in)."""
    yield {
        "type": "user",
        "message": {"role": "user", "content": content},
        "parent_tool_use_id": None,
    }


class TutorSession:
    """A multi-turn conversation owned by one background task."""

    def __init__(self, options: ClaudeAgentOptions) -> None:
        """Remember the options; nothing is spawned until :meth:`ask`."""
        self._options = options
        self._queue: asyncio.Queue[tuple[Prompt, asyncio.Future[Reply]] | None] = (
            asyncio.Queue()
        )
        self._task: asyncio.Task[None] | None = None
        self._inflight: asyncio.Future[Reply] | None = None
        self.last_init: dict[str, Any] = {}

    async def ask_raw(self, prompt: Prompt) -> Reply:
        """Send one user message (text or content blocks); return the raw reply."""
        if self._task is None:
            self._task = asyncio.create_task(self._run())
            self._task.add_done_callback(self._on_exit)
        fut: asyncio.Future[Reply] = asyncio.get_running_loop().create_future()
        await self._queue.put((prompt, fut))
        return await asyncio.wait_for(fut, _TURN_TIMEOUT)

    async def ask(self, prompt: Prompt) -> tuple[TutorTurn, Reply]:
        """Send one message and validate the structured turn."""
        reply = await self.ask_raw(prompt)
        raw = reply.structured
        if raw is None:
            try:
                raw = json.loads(reply.text)
            except json.JSONDecodeError as err:
                msg = f"no structured output; text was: {reply.text[:200]!r}"
                raise SessionError(msg) from err
        try:
            return TutorTurn.from_json(raw), reply
        except TurnError as err:
            raise SessionError(str(err)) from err

    async def close(self) -> None:
        """Stop the background task and the CLI process."""
        if self._task is not None:
            task = self._task
            if not task.done():
                await self._queue.put(None)
            # wait(), not await: a task that died is reported by _on_exit,
            # and closing must not re-raise that failure.
            await asyncio.wait({task})
            if self._task is task:
                self._task = None

    async def _run(self) -> None:
        """Own the CLI process; serve queued prompts until the close sentinel.

        Nothing is caught here: whatever kills the process (it failed to
        start, died, or the SDK raised) ends this task, and :meth:`_on_exit`
        fails every waiting caller from the task's own exception.
        """
        async with ClaudeSDKClient(self._options) as client:
            while (item := await self._queue.get()) is not None:
                self._inflight = item[1]
                await self._serve(client, *item)
                self._inflight = None

    def _on_exit(self, task: asyncio.Task[None]) -> None:
        """The process is gone: fail its callers now, not at the turn timeout.

        The next :meth:`ask_raw` starts a fresh process (without the old
        conversation's memory; the engine's resume primer is what restores it).
        """
        if self._task is task:
            self._task = None
        waiting = [self._inflight] if self._inflight is not None else []
        self._inflight = None
        while not self._queue.empty():
            item = self._queue.get_nowait()
            if item is not None:
                waiting.append(item[1])
        if task.cancelled():
            _logger.error("model task cancelled; cancelling %d callers", len(waiting))
            err: BaseException | None = None
        else:
            err = task.exception()
            if err is None:
                if not waiting:
                    return  # a clean close with nobody waiting
                err = SessionError("the model session closed before replying")
            _logger.error("model process ended: %r; failing %d", err, len(waiting))
        for fut in waiting:
            _settle(fut, err)

    async def _serve(
        self, client: ClaudeSDKClient, prompt: Prompt, fut: asyncio.Future[Reply]
    ) -> None:
        """One model call; a failed turn is relayed and the process kept.

        Only the model's error result (:class:`SessionError`) is caught: it is
        raised after the whole turn was read, so the stream is clean for the
        next one. Anything else (the CLI died, a line would not parse) leaves
        the process in an unknown state and ends :meth:`_run`.
        """
        try:
            await client.query(prompt if isinstance(prompt, str) else _blocks(prompt))
            reply = _collect([m async for m in client.receive_response()])
        except SessionError as err:
            _logger.warning("model turn failed; relayed to the caller: %s", err)
            _settle(fut, err)
            return
        if reply.init:
            self.last_init = reply.init
        if not fut.done():  # the caller may have timed out meanwhile
            fut.set_result(reply)


def _settle(fut: asyncio.Future[Reply], err: BaseException | None) -> None:
    """Fail ``fut`` with ``err`` (cancel it when None), unless already done."""
    if fut.done():
        return
    if err is None:
        fut.cancel()
    else:
        fut.set_exception(err)
