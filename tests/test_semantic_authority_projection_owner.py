# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One authority fact, two published spellings -- pinned to agree.

``SemanticAuthorityResult`` has one producer and cannot hold two facts.  What
can differ is the TRANSLATION: the document publishes the same violation twice,
once as ``source_facts.semantic`` (a plain ``asdict`` of the frozen result) and
once as ``metrics.families.semantic_authority`` (hand-written rows), and
nothing made the two agree.

Measured 2026-09-02 on an ordinary warm-cache run: they did not.  A violation's
evidence site read ``pkg/shadow_in.py`` in the row form and the absolute
runtime path in the ``asdict`` form, because ``SemanticEvent.location[0]`` had
two domains -- the analysed (repository-relative) path when a file was parsed,
the runtime path when it came back from the cache.  ``source_facts`` is
digested into the ``analysis_facts`` integrity tier, so the same tree at the
same content produced two different run identities depending on cache warmth.

These pins therefore hold two separate things, and each fails for its own
reason:

* the two spellings of one run agree (a projection may not drift alone);
* the owner's own value does not depend on cache warmth (one domain, always).

``producer_root_ids`` is the second field where the two forms could disagree:
the row form sorts, ``asdict`` preserves the producer's order.  Today they
agree because ``semantics/ir.py`` emits ``tuple(sorted(...))`` at birth, which
makes the document's sort a provable no-op.  That is a DERIVATION, and the
derivation is what is pinned -- an equality between the two published forms
alone would stay green for any order the owner chose.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

import pytest

_CANON = """def canonical_normalize(value: str) -> str:
    payload = value
    return payload
"""

_ZULU = """def zulu_normalize(value: str) -> str:
    payload = value
    return payload
"""

# Two producers reach one sink, so the sink's ``producer_root_ids`` carries
# more than one entry: an ordering pin over single-element tuples is vacuous.
_SHADOW = """from pkg.canon import canonical_normalize
from pkg.zulu import zulu_normalize


def shadow_normalize_in(value: str, extra: str) -> str:
    first = canonical_normalize(value)
    second = zulu_normalize(extra)
    payload = first + second
    return payload
"""

_PYPROJECT = """[tool.codeclone]
semantic_authority = true

[[tool.codeclone.authority]]
contract_id = "projection-owner-fixture.normalize/v1"
canonical_owner = "pkg.canon:canonical_normalize"
allowed_adapters = []
forbidden_raw_inputs = ["param:0"]
required_provenance = ["producer:pkg.canon:canonical_normalize"]
"""


def _write_tree(root: Path) -> None:
    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", "utf-8")
    (package / "canon.py").write_text(_CANON, "utf-8")
    (package / "zulu.py").write_text(_ZULU, "utf-8")
    (package / "shadow_in.py").write_text(_SHADOW, "utf-8")
    (root / "pyproject.toml").write_text(_PYPROJECT, "utf-8")


def _run_cli(argv: list[str]) -> None:
    import codeclone.surfaces.cli.workflow as cli

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(sys, "argv", ["codeclone", *argv])
        try:
            cli.main()
        except SystemExit as exit_signal:
            assert exit_signal.code in (None, 0, 1), f"CLI exited {exit_signal.code!r}"
    finally:
        monkeypatch.undo()


@pytest.fixture(scope="module")
def warmth_documents(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, object], dict[str, object]]:
    """``(cold document, warm document)`` over one tree and one cache.

    The second run is the whole point: the first parses every file, the
    second serves all four from the cache, and those are the two production
    paths that stamp ``SemanticEvent.location``.
    """

    base = tmp_path_factory.mktemp("authority-projection-owner")
    root = base / "tree"
    _write_tree(root)
    cache = base / "cache.json"
    documents: list[dict[str, object]] = []
    for name in ("cold", "warm"):
        report = base / f"{name}.json"
        _run_cli(
            [
                str(root),
                "--cache-path",
                str(cache),
                "--json",
                str(report),
                "--no-progress",
                "--processes",
                "1",
            ]
        )
        document = json.loads(report.read_text("utf-8"))
        assert isinstance(document, dict)
        documents.append(document)
    return documents[0], documents[1]


def _owner_form(document: dict[str, object]) -> dict[str, object]:
    """``source_facts.semantic`` -- the frozen result, dumped as-is."""

    source_facts = cast("dict[str, object]", document["source_facts"])
    semantic = source_facts["semantic"]
    assert isinstance(semantic, dict), "the run published no authority result"
    return semantic


def _row_form(document: dict[str, object]) -> list[dict[str, object]]:
    """``metrics.families.semantic_authority.items`` -- the published rows."""

    metrics = cast("dict[str, object]", document["metrics"])
    families = cast("dict[str, object]", metrics["families"])
    family = cast("dict[str, object]", families["semantic_authority"])
    return [
        cast("dict[str, object]", item)
        for item in cast("list[object]", family["items"])
    ]


def _rows_by_kind(document: dict[str, object], kind: str) -> list[dict[str, object]]:
    return [row for row in _row_form(document) if row.get("item_kind") == kind]


def _location_paths(item: dict[str, object]) -> list[str]:
    return [
        str(cast("dict[str, object]", location)["relative_path"])
        for location in cast("list[object]", item["locations"])
    ]


def test_the_fixture_still_produces_the_shapes_the_pins_read(
    warmth_documents: tuple[dict[str, object], dict[str, object]],
) -> None:
    """The fixture's own witness: without it every pin below is vacuous."""

    _cold, warm = warmth_documents
    violations = cast("list[object]", _owner_form(warm)["violations"])
    assert violations, "the fixture stopped producing an authority violation"
    assert any(
        cast("list[object]", cast("dict[str, object]", violation)["locations"])
        for violation in violations
    ), "the fixture stopped producing an evidence location"
    sinks = cast("list[object]", _owner_form(warm)["sinks"])
    assert any(
        len(cast("list[object]", cast("dict[str, object]", sink)["producer_root_ids"]))
        > 1
        for sink in sinks
    ), "the fixture stopped producing a multi-root sink; an order pin needs two"
    assert _rows_by_kind(warm, "violation"), "the row form published no violation"


def test_both_published_authority_forms_spell_one_location_the_same_way(
    warmth_documents: tuple[dict[str, object], dict[str, object]],
) -> None:
    """One fact, two spellings, one answer -- on both cache paths."""

    for document in warmth_documents:
        owner = {
            str(violation["violation_id"]): _location_paths(violation)
            for violation in (
                cast("dict[str, object]", item)
                for item in cast("list[object]", _owner_form(document)["violations"])
            )
        }
        rows = {
            str(row["violation_id"]): _location_paths(row)
            for row in _rows_by_kind(document, "violation")
        }
        assert rows == owner


def test_the_authority_result_does_not_depend_on_cache_warmth(
    warmth_documents: tuple[dict[str, object], dict[str, object]],
) -> None:
    """The owner's own value is a function of the tree, not of the cache.

    ``source_facts`` is the preimage of the ``analysis_facts`` integrity tier,
    which feeds ``comparison`` and the report identity -- so a warmth-dependent
    field here is a warmth-dependent run identity.
    """

    cold, warm = warmth_documents
    assert _owner_form(warm) == _owner_form(cold)


def test_the_owner_emits_producer_root_ids_already_sorted(
    warmth_documents: tuple[dict[str, object], dict[str, object]],
) -> None:
    """Why the row form's ``sorted()`` cannot change the published value.

    The document layer sorts ``producer_root_ids`` to keep a union family's
    rows totally ordered; ``asdict`` does not.  They agree only because
    ``build_contract_ir`` emits the roots sorted at birth.  Pinning that
    derivation is what makes the other form's sort a proven no-op -- pinning
    the two forms equal instead would hold for any order the owner picked.
    """

    for document in warmth_documents:
        owner = _owner_form(document)
        carriers = [
            *cast("list[object]", owner["sinks"]),
            *cast("list[object]", owner["governed_sinks"]),
            *cast("list[object]", owner["violations"]),
            *cast(
                "list[object]",
                cast("dict[str, object]", owner["contract_ir"])["contracts"],
            ),
        ]
        multi_root = 0
        for carrier in carriers:
            entry = cast("dict[str, object]", carrier)
            roots = [
                str(value)
                for value in cast(
                    "list[object]",
                    entry.get("producer_root_ids", entry.get("provenance_roots")),
                )
            ]
            multi_root += len(roots) > 1
            assert roots == sorted(roots)
        assert multi_root, "no carrier held two roots; the order pin proved nothing"


def test_both_published_authority_forms_spell_producer_roots_the_same_way(
    warmth_documents: tuple[dict[str, object], dict[str, object]],
) -> None:
    """The consumer may not re-derive the order the owner already settled."""

    for document in warmth_documents:
        owner = {
            str(sink["sink_identity"]): [
                str(value) for value in cast("list[object]", sink["producer_root_ids"])
            ]
            for sink in (
                cast("dict[str, object]", item)
                for item in cast("list[object]", _owner_form(document)["sinks"])
            )
        }
        rows = {
            str(row["sink_identity"]): [
                str(value) for value in cast("list[object]", row["producer_root_ids"])
            ]
            for row in _rows_by_kind(document, "sink")
        }
        assert rows == owner
