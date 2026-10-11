# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""deck_edit: parse, validate, the line cap, the source check and the write."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

import pytest

from plc_lab import cards, sources
from plc_lab.tutor import deck_edit
from plc_lab.tutor.deck_edit import Dirs, EditError

REPO_DECK = Path(__file__).resolve().parents[3] / "deck"
CARD = "fund-plc-definition"


def _copy(dest: Path) -> Path:
    shutil.copytree(REPO_DECK, dest)
    return dest


@pytest.fixture
def dirs(tmp_path: Path) -> Dirs:
    return Dirs(_copy(tmp_path / "src"), _copy(tmp_path / "live"))


@pytest.fixture(autouse=True)
def source_ok(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    checked: list[str] = []

    def check(card_id: str, url: str, excerpt: str) -> None:
        del url, excerpt
        checked.append(card_id)

    monkeypatch.setattr(sources, "check_excerpt", check)
    return checked


def _body(card_id: str = CARD, **change: Any) -> dict[str, Any]:
    raw = next(
        c
        for path in REPO_DECK.glob("*.json")
        for c in json.loads(path.read_text(encoding="utf-8"))
        if c["id"] == card_id
    )
    return {**raw, **change}


def _new(card_id: str = "fund-new-card", **change: Any) -> dict[str, Any]:
    return _body(
        CARD, **{"id": card_id, "new": True, "topic": "fundamentals", **change}
    )


def test_every_deck_file_round_trips_byte_for_byte() -> None:
    for path in REPO_DECK.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert deck_edit.render(json.loads(text)) == text


def test_dirs_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(deck_edit.DECK_SRC_ENV, raising=False)
    assert Dirs.from_env(tmp_path).src is None
    monkeypatch.setenv(deck_edit.DECK_SRC_ENV, "  ")
    assert Dirs.from_env(tmp_path).src is None
    monkeypatch.setenv(deck_edit.DECK_SRC_ENV, str(tmp_path / "deck"))
    assert Dirs.from_env(tmp_path) == Dirs(tmp_path / "deck", tmp_path)


def test_read_only_reasons(tmp_path: Path) -> None:
    assert "is not set" in Dirs(None, tmp_path).read_only_reason()
    assert "is not a directory" in Dirs(tmp_path / "no", tmp_path).read_only_reason()
    assert Dirs(tmp_path, tmp_path).read_only_reason() == ""


def test_targets_write_each_dir_once(tmp_path: Path) -> None:
    other = tmp_path / "other"
    assert Dirs(None, tmp_path).targets() == [tmp_path]
    assert Dirs(tmp_path, tmp_path / ".").targets() == [tmp_path]
    assert Dirs(tmp_path, other).targets() == [tmp_path, other]


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"id": " "}, "id must be"),
        ({"id": 3}, "id must be"),
        ({"id": "x", "front": 1}, "must all be strings"),
        ({**_body(), "requires": "fund-x"}, "requires must be a list"),
        ({**_body(), "requires": [1]}, "requires must be a list"),
    ],
)
def test_parse_refuses_wrong_types(body: dict[str, Any], error: str) -> None:
    with pytest.raises(EditError, match=error):
        deck_edit.parse(body)


def test_parse_strips_and_defaults() -> None:
    edit = deck_edit.parse(
        {**_body(front="  Padded?  "), "topic": 7, "requires": [" a ", ""]}
    )
    assert (edit.fields["front"], edit.topic, edit.requires) == ("Padded?", "", ("a",))
    assert deck_edit.parse({**_body(), "requires": None}).requires == ()
    assert deck_edit.parse(_body()).new is False


def test_edit_then_revert_leaves_the_file_byte_identical(dirs: Dirs) -> None:
    before = (REPO_DECK / "fundamentals.json").read_bytes()
    for front in ("A changed front?", _body()["front"]):
        planned = deck_edit.prepare(dirs, deck_edit.parse(_body(front=front)))
        deck_edit.write(dirs, planned)
    for target in dirs.targets():
        assert (target / "fundamentals.json").read_bytes() == before
        assert not list(target.glob(".*.tmp"))


def test_edit_writes_both_dirs_and_checks_the_source(
    dirs: Dirs, source_ok: list[str]
) -> None:
    planned = deck_edit.prepare(dirs, deck_edit.parse(_body(front="New front?")))
    deck_edit.write(dirs, planned)
    assert source_ok == [CARD]
    assert planned.card.front == "New front?"
    for target in dirs.targets():
        deck = cards.load_deck(target)
        assert next(c for c in deck if c.id == CARD).front == "New front?"


def test_new_card_with_requires_is_appended(dirs: Dirs) -> None:
    body = _new(requires=[CARD, "lang-ld-name"])
    planned = deck_edit.plan(dirs, deck_edit.parse(body))
    assert planned.stem == "fundamentals"
    assert planned.card.requires == (CARD, "lang-ld-name")
    assert json.loads(planned.text)[-1]["id"] == "fund-new-card"


def test_an_emptied_requires_drops_the_key(dirs: Dirs) -> None:
    gated = _body("fund-five-languages", requires=[])
    planned = deck_edit.plan(dirs, deck_edit.parse(gated))
    row = next(c for c in json.loads(planned.text) if c["id"] == "fund-five-languages")
    assert "requires" not in row


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (_new(topic="nope"), "unknown topic"),
        (_new("ld-wrong-topic"), "must start with fund-"),
        (_new("fund-Bad id"), "only a-z"),
        (_new("fund-"), "must start with fund-"),
        (_new(CARD), "already taken"),
        (_body(id="fund-nope"), "unknown card 'fund-nope'"),
        (_body(requires=[CARD]), "cannot require itself"),
        (_body(requires=["fund-nope"]), "unknown card"),
        (_body("lang-ld-name", requires=["fund-five-languages"]), "requires cycle"),
        (_body(front=" ".join(["word"] * 30)), "front is over 25 words"),
        (_body(source="http://example.com/"), "https URL"),
        (_body(excerpt=""), "non-empty string"),
    ],
)
def test_refused_saves(dirs: Dirs, body: dict[str, Any], error: str) -> None:
    with pytest.raises(EditError, match=error):
        deck_edit.prepare(dirs, deck_edit.parse(body))


def test_line_cap_refuses_growing_a_file_past_250(dirs: Dirs) -> None:
    first = json.loads((REPO_DECK / "ot_security.json").read_text(encoding="utf-8"))[0]
    sec = _body(first["id"], new=True, topic="ot_security")
    for n in range(3):  # 226 lines + 3 cards of 7 lines = 247
        planned = deck_edit.plan(dirs, deck_edit.parse({**sec, "id": f"sec-a{n}"}))
        deck_edit.write(dirs, planned)
    with pytest.raises(EditError, match=r"would be 254 lines, over the 250-line cap"):
        deck_edit.plan(dirs, deck_edit.parse({**sec, "id": "sec-a9"}))


def test_read_only_refuses(tmp_path: Path) -> None:
    with pytest.raises(EditError, match="is not set"):
        deck_edit.plan(Dirs(None, tmp_path), deck_edit.parse(_body()))


def test_unreadable_topic_file(dirs: Dirs) -> None:
    assert dirs.src is not None
    (dirs.src / "ladder.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(EditError, match="cannot read"):
        deck_edit.plan(dirs, deck_edit.parse(_body()))


def test_a_topic_file_that_is_not_an_array(dirs: Dirs) -> None:
    assert dirs.src is not None
    (dirs.src / "ladder.json").write_text("{}", encoding="utf-8")
    with pytest.raises(EditError, match=r"ladder.json: the file must hold"):
        deck_edit.plan(dirs, deck_edit.parse(_body()))


def test_a_live_copy_that_differs_is_refused(dirs: Dirs) -> None:
    (dirs.live / "languages.json").unlink()
    with pytest.raises(EditError, match="deploy first: missing topic file deck/"):
        deck_edit.plan(dirs, deck_edit.parse(_body()))


def test_place_skips_entries_that_are_not_objects() -> None:
    raw: dict[str, list[Any]] = {"fundamentals": ["junk", {"id": CARD}]}
    edit = deck_edit.parse(_body(front="Q?"))
    assert deck_edit._place(raw, edit) == "fundamentals"
    assert raw["fundamentals"][1]["front"] == "Q?"


def test_check_source_refuses_a_missing_excerpt(
    dirs: Dirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    def check(card_id: str, url: str, excerpt: str) -> sources.Mismatch:
        del excerpt
        return sources.Mismatch(card_id, url, "excerpt not found in the page text")

    monkeypatch.setattr(sources, "check_excerpt", check)
    with pytest.raises(EditError, match="excerpt check failed for https://"):
        deck_edit.prepare(dirs, deck_edit.parse(_body(excerpt="x " * 8)))


def test_one_dir_when_the_server_runs_from_the_repo(tmp_path: Path) -> None:
    same = Dirs(_copy(tmp_path / "deck"), tmp_path / "deck")
    planned = deck_edit.prepare(same, deck_edit.parse(_body(front="Same dir?")))
    deck_edit.write(same, planned)
    assert "Same dir?" in (tmp_path / "deck" / "fundamentals.json").read_text("utf-8")
