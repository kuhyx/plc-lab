# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Pass/fail by code over a session transcript (no model grades a model).

``python -m plc_lab.tutor.adjudicate sessions/<id>.jsonl`` prints one verdict
per acceptance item and exits non-zero if any failed.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any, Final

from plc_lab.tutor.models import REQUIRED_FIELDS

TERMS: Final = {
    "voltage": r"\bvolt(age|s)?\b",
    "current": r"\bcurrent\b",
    "DC": r"\bDC\b|direct current",
    "coil": r"\bcoil\b",
    "relay": r"\brelay\b",
}
_ASKS: Final = re.compile(r"\b(tell me|say|write|describe|explain)\b", re.IGNORECASE)
_VOLTS: Final = re.compile(r"24\s*V", re.IGNORECASE)
MIN_UNCHECKED_BLOCK: Final = 15  # a credit this late with no pass is item g
_MIN_TERMS: Final = 3  # key terms the diagnostic first turn must ask about
_CONTEXT: Final = re.compile(
    r"\b(typical|typically|usual|usually|standard|machine[- ]tool)\b", re.IGNORECASE
)


class _Answer:
    """A message states the card's answer: 24 V as the typical/usual/standard value."""

    @staticmethod
    def search(text: str) -> bool:
        """Whether ``text`` gives the 24 V coil answer."""
        return bool(_VOLTS.search(text) and _CONTEXT.search(text))


_ANSWER: Final = _Answer()


def load(path: Path) -> list[dict[str, Any]]:
    """Every event of a session transcript."""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def verdicts(events: list[dict[str, Any]]) -> list[tuple[str, bool, str]]:
    """``(item, passed, evidence)`` for acceptance items (a)-(h)."""
    tutor = [e for e in events if e["type"] == "tutor"]
    first = tutor[0]["turn"]["message"] if tutor else ""
    seen_terms = [t for t, rx in TERMS.items() if re.search(rx, first, re.IGNORECASE)]
    answer_at = next(
        (i for i, e in enumerate(tutor) if i and _ANSWER.search(e["turn"]["message"])),
        len(tutor),
    )
    taught = {
        term: next(
            (
                i
                for i, e in enumerate(tutor)
                if i
                and i < answer_at
                and re.search(rx, e["turn"]["message"], re.IGNORECASE)
            ),
            None,
        )
        for term, rx in TERMS.items()
    }
    images = [i for e in tutor for i in e["ui"].get("images", [])]
    diagrams = [d for e in tutor for d in e["ui"].get("diagrams", [])]
    posed = next((i for i, e in enumerate(tutor) if e["turn"]["check"]), None)
    graded = next((i for i, e in enumerate(tutor) if e["turn"]["check_result"]), None)
    receipts = [e for e in events if e["type"] == "credit" and e.get("recorded")]
    missing = [
        (i, k)
        for i, e in enumerate(tutor)
        for k in REQUIRED_FIELDS
        if k not in e["turn"]
    ]
    image_titles = [i["title"] for i in images]
    low_turns = [i for i, e in enumerate(tutor) if e["turn"]["low_effort"]]
    unchecked = [
        e["block"]
        for e in events
        if e["type"] == "credit"
        and e.get("recorded")
        and e.get("checks_passed") == 0
        and e["block"] >= MIN_UNCHECKED_BLOCK
    ]
    return [
        (
            (
                "a. first turn asks what the learner knows "
                "(>=3 terms, a question, no answer)"
            ),
            bool(tutor)
            and ("?" in first or _ASKS.search(first) is not None)
            and len(seen_terms) >= _MIN_TERMS
            and not _ANSWER.search(first),
            f"terms asked about: {seen_terms}",
        ),
        (
            "b. voltage/current/DC/coil/relay taught before the 24 V answer",
            all(v is not None for v in taught.values()),
            f"first teaching turn per term: {taught}; answer at turn {answer_at}",
        ),
        (
            "c. >=1 Commons image with attribution and >=1 code-drawn diagram",
            bool(images)
            and all(i["author"] and i["licence"] and i["page_url"] for i in images)
            and bool(diagrams),
            f"{len(images)} images ({image_titles}), {len(diagrams)} diagrams",
        ),
        (
            "d. a check was posed, then graded, and a block recorded",
            posed is not None
            and graded is not None
            and graded > posed
            and bool(receipts),
            (
                f"check posed turn {posed}, graded turn {graded}, "
                f"recorded receipts {len(receipts)}"
            ),
        ),
        (
            "e. every tutor turn carries every structured field",
            bool(tutor) and not missing,
            f"{len(tutor)} turns, missing: {missing}",
        ),
        (
            "f. low_effort set on a filler reply",
            any(e["turn"]["low_effort"] for e in tutor[1:]),
            f"low_effort turns: {low_turns}",
        ),
        (
            "g. credit recorded with no passed check after 15 active minutes",
            bool(unchecked),
            f"recorded credit rows with checks_passed == 0: units {unchecked}",
        ),
        (
            "h. card_done is followed by Next card or Stop here",
            _choice_follows_card_done(events),
            "card_done turn, then a next_card or stop event",
        ),
    ]


def _choice_follows_card_done(events: list[dict[str, Any]]) -> bool:
    """Some tutor turn has ``ui.card_done`` and each is followed by a choice."""
    done_at = [
        i
        for i, e in enumerate(events)
        if e["type"] == "tutor" and e.get("ui", {}).get("card_done")
    ]
    choices = [i for i, e in enumerate(events) if e["type"] in {"next_card", "stop"}]
    return bool(done_at) and all(any(c > i for c in choices) for i in done_at)


def message_indices(events: list[dict[str, Any]]) -> list[int]:
    """The page-message index (``m<i>``) of each tutor turn, as the page counts.

    A learner bubble precedes the tutor message it was answered by; a Next card
    divider is a message of its own and drops a learner message that got no reply.
    """
    out: list[int] = []
    count = 0
    pending = False
    for event in events:
        kind = event["type"]
        if kind == "learner":
            pending = True
        elif kind == "tutor":
            count += int(pending)
            pending = False
            out.append(count)
            count += 1
        elif kind == "next_card":
            pending = False
            count += int(bool(event.get("ui")))  # only an in-session switch
    return out


def anchors(events: list[dict[str, Any]]) -> dict[str, str]:
    """Page anchors (``m<i>``) for the first picture, first diagram and last turn."""
    tutor = [e for e in events if e["type"] == "tutor"]
    at = message_indices(events)
    out = {"last": f"m{at[-1]}"}
    for name, key in (("image", "images"), ("diagram", "diagrams")):
        hit = next((i for i, e in enumerate(tutor) if e["ui"].get(key)), 0)
        out[name] = f"m{at[hit]}"
    return out


def main(argv: list[str]) -> int:
    """Print the verdicts for a transcript; 1 if any item failed."""
    if argv[1] == "--anchors":
        print(json.dumps(anchors(load(Path(argv[2])))))
        return 0
    results = verdicts(load(Path(argv[1])))
    for item, ok, evidence in results:
        print(f"{'PASS' if ok else 'FAIL'}  {item}\n      {evidence}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
