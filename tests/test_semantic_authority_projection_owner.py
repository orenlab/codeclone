# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One authority fact, three published spellings -- pinned to agree.

``SemanticAuthorityResult`` has one producer and cannot hold two facts.  What
can differ is the TRANSLATION, and three hand-written translators read that one
result: ``metrics.families.semantic_authority`` (the document rows), the
``semantic_authority`` baseline lane (the wire), and the canonical snapshot
(the run store's families).  Beside them the owner publishes itself as
``source_facts.semantic``, a plain ``asdict``.  Nothing made them agree.

Measured 2026-09-02 on an ordinary warm-cache run: they did not.  A violation's
evidence site read ``pkg/shadow_in.py`` in the row form and the absolute
runtime path in the ``asdict`` form, because ``SemanticEvent.location[0]`` had
two domains -- the analysed (repository-relative) path when a file was parsed,
the runtime path when it came back from the cache.  ``source_facts`` is
digested into the ``analysis_facts`` integrity tier, so the same tree at the
same content produced two different run identities depending on cache warmth.

These pins therefore hold separate things, and each fails for its own reason:

* the published spellings of one run agree (a projection may not drift alone);
* the owner's own value does not depend on cache warmth (one domain, always);
* where a spelling deliberately says LESS, the difference is asserted by name
  instead of being hidden inside a comparison that skips it.

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
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, cast

import orjson
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
    assert family["items_truncated"] is False, "the family truncated its rows"
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


# ---------------------------------------------------------------------------
# The third published spelling: the baseline lane.
# ---------------------------------------------------------------------------
#
# One ``AuthorityGovernedSink`` reaches three hand-written translators, and
# until these pins nothing compared them to each other:
#
# * ``core/metrics_payload.py::_semantic_authority_payload`` builds the
#   ``governed_sink`` rows of ``metrics.families.semantic_authority``;
# * ``observations/lanes.py::_lane_payload`` builds the ``semantic_authority``
#   baseline lane, whose canonical bytes ARE its lane digest and therefore
#   part of the published baseline identity;
# * ``report/document/builder.py::_source_facts`` dumps the frozen result with
#   ``asdict`` -- the owner's own spelling, and the preimage of the
#   ``analysis_facts`` integrity tier.
#
# The fourth translator, ``core/canonical_snapshot.py::_semantic_families``,
# is absent here because it carries no governed-sink family at all; the
# ``authority.sinks`` / ``.violations`` / ``.candidates`` lanes of
# ``tests/test_projection_equivalence.py`` already own every family it does
# carry.  Governed sinks were the family no instrument compared, and the lane
# form is the one whose drift would move a baseline identity in silence.

_ALPHA = """import json


def alpha_publish(value: str, handler: object) -> str:
    payload = json.dumps(value)
    extra = handler(payload)
    return payload + extra
"""

_OMEGA = """import json


def omega_publish(value: str, handler: object) -> str:
    payload = json.dumps(value)
    extra = handler(payload)
    return payload + extra
"""

_SINGLE_CONTRACT_PYPROJECT = """[tool.codeclone]
semantic_authority = true
baseline_scope_id = "5f1c0f4c-4b1a-4f2e-9a3d-0c7b6e5d4a31"

[[tool.codeclone.authority]]
contract_id = "projection-owner-fixture.normalize/v1"
canonical_owner = "pkg.canon:canonical_normalize"
allowed_adapters = []
forbidden_raw_inputs = ["param:0"]
required_provenance = ["producer:pkg.canon:canonical_normalize"]
"""

# Two contracts whose canonical owners INVERT the identity order: the
# alphabetically first contract owns the alphabetically last sink.  Governed
# rows are ordered contract-first, so this is the only one of the two trees on
# which a translator that ordered by ``sink_identity`` alone can be caught.
_TWO_CONTRACT_PYPROJECT = """[tool.codeclone]
semantic_authority = true
baseline_scope_id = "6b2d1e5a-7c3f-4d8b-8e1a-2f9c4b6d7e05"

[[tool.codeclone.authority]]
contract_id = "alpha.publish/v1"
canonical_owner = "pkg.omega:omega_publish"
allowed_adapters = []
forbidden_raw_inputs = ["param:0"]
required_provenance = ["producer:pkg.omega:omega_publish"]

[[tool.codeclone.authority]]
contract_id = "zulu.publish/v1"
canonical_owner = "pkg.alpha:alpha_publish"
allowed_adapters = []
forbidden_raw_inputs = ["param:0"]
required_provenance = ["producer:pkg.alpha:alpha_publish"]
"""

#: The columns all three forms publish for one governed sink.  Restricting to
#: them is the ONLY normalisation these pins apply, and the two columns it
#: leaves out are asserted -- not hidden -- by the narrowing pin below.
_GOVERNED_SINK_SHARED_COLUMNS: Final = (
    "authority_status",
    "contract_id",
    "effect_signature",
    "producer_root_ids",
    "resolution_state",
    "sink_identity",
)

#: The owner columns the published row form must reproduce, per family.
#: ``locations`` rides the violation row because it was measured NOT derivable
#: from any other stored family, so a drift there has nowhere else to be seen.
_OWNER_COLUMNS_BY_FAMILY: Final[dict[str, tuple[str, ...]]] = {
    "sinks": (
        "authority_status",
        "effect_signature",
        "producer_root_ids",
        "resolution_state",
        "sink_identity",
    ),
    "candidates": (
        "candidate_id",
        "independence",
        "level",
        "producers",
        "score",
        "semantic_divergence",
        "shared_fact",
        "sink_statuses",
    ),
    "violations": (
        "authority_status",
        "canonical_owner",
        "contract_id",
        "effect_signature",
        "kind",
        "locations",
        "producer_root_ids",
        "producers",
        "resolution_state",
        "sink_identity",
        "suppressed",
        "violation_id",
    ),
}

#: ``source_facts.semantic`` names its families in the plural; the union
#: container tags one row with the singular.  One mapping, stated once.
_ROW_KIND_BY_FAMILY: Final[dict[str, str]] = {
    "sinks": "sink",
    "candidates": "candidate",
    "violations": "violation",
}

#: The natural key each family is indexed by before comparison.  The two forms
#: publish different row ORDERS, so a positional comparison would assert the
#: order twice and the values not at all.
_NATURAL_KEY_BY_FAMILY: Final[dict[str, str]] = {
    "sinks": "sink_identity",
    "candidates": "candidate_id",
    "violations": "violation_id",
}

#: Which families each shape is required to populate.  Declared rather than
#: discovered: a shape that silently stopped emitting a family would otherwise
#: turn the comparison of that family into a comparison of two emptinesses.
#: ``two_contracts`` governs one function per contract and so raises no
#: violation -- that is the enforcement shape's job.
_POPULATED_FAMILIES: Final[dict[str, frozenset[str]]] = {
    "single_contract": frozenset({"sinks", "candidates", "violations"}),
    "two_contracts": frozenset({"sinks", "candidates"}),
}


def _write_single_contract_tree(root: Path) -> None:
    """The enforcement shape: one contract, three statuses, one violation."""

    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", "utf-8")
    (package / "canon.py").write_text(_CANON, "utf-8")
    (package / "zulu.py").write_text(_ZULU, "utf-8")
    (package / "shadow_in.py").write_text(_SHADOW, "utf-8")
    (root / "pyproject.toml").write_text(_SINGLE_CONTRACT_PYPROJECT, "utf-8")


def _write_two_contract_tree(root: Path) -> None:
    """The ordering shape: two contracts, every sink unresolved, multi-root."""

    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", "utf-8")
    (package / "alpha.py").write_text(_ALPHA, "utf-8")
    (package / "omega.py").write_text(_OMEGA, "utf-8")
    (root / "pyproject.toml").write_text(_TWO_CONTRACT_PYPROJECT, "utf-8")


@pytest.fixture(scope="module")
def published_forms(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, tuple[dict[str, object], dict[str, object]]]:
    """``{shape: (report document, published baseline container)}``.

    Both artefacts come out of ONE run of the real pipeline per shape, so the
    three spellings compared below are the three a user actually receives --
    not three calls this test made to three functions.
    """

    base = tmp_path_factory.mktemp("authority-published-forms")
    forms: dict[str, tuple[dict[str, object], dict[str, object]]] = {}
    for shape, writer in (
        ("single_contract", _write_single_contract_tree),
        ("two_contracts", _write_two_contract_tree),
    ):
        root = base / shape
        writer(root)
        report = base / f"{shape}.json"
        _run_cli(
            [
                str(root),
                "--cache-path",
                str(base / f"{shape}-cache.json"),
                "--json",
                str(report),
                "--no-progress",
                "--processes",
                "1",
                "--update-baseline",
            ]
        )
        document = json.loads(report.read_text("utf-8"))
        container = json.loads((root / "codeclone.baseline.json").read_text("utf-8"))
        assert isinstance(document, dict)
        assert isinstance(container, dict)
        forms[shape] = (document, container)
    return forms


def _owner_governed_sinks(document: dict[str, object]) -> list[dict[str, object]]:
    """``source_facts.semantic.governed_sinks`` -- the frozen result, as-is."""

    return [
        cast("dict[str, object]", item)
        for item in cast("list[object]", _owner_form(document)["governed_sinks"])
    ]


def _wire_governed_sinks(container: dict[str, object]) -> list[dict[str, object]]:
    """The published ``semantic_authority`` baseline lane rows."""

    lanes = cast("dict[str, object]", container["lanes"])
    lane = cast("dict[str, object]", lanes["semantic_authority"])
    payload = cast("dict[str, object]", lane["payload"])
    return [
        cast("dict[str, object]", item)
        for item in cast("list[object]", payload["observations"])
    ]


def _shared_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    """The six shared columns of a governed-sink row list, in row order."""

    return orjson.dumps(
        [
            {column: row[column] for column in _GOVERNED_SINK_SHARED_COLUMNS}
            for row in rows
        ],
        option=orjson.OPT_SORT_KEYS,
    )


def _indexed_bytes(
    rows: Sequence[Mapping[str, object]],
    *,
    key: str,
    columns: Sequence[str],
) -> bytes:
    return orjson.dumps(
        {str(row[key]): {column: row[column] for column in columns} for row in rows},
        option=orjson.OPT_SORT_KEYS,
    )


def _contract_keys(rows: Sequence[Mapping[str, object]]) -> list[tuple[str, str]]:
    return [(str(row["contract_id"]), str(row["sink_identity"])) for row in rows]


def _family_summary(document: dict[str, object]) -> dict[str, object]:
    """``metrics.families.semantic_authority.summary`` -- the hand-written counts."""

    metrics = cast("dict[str, object]", document["metrics"])
    families = cast("dict[str, object]", metrics["families"])
    family = cast("dict[str, object]", families["semantic_authority"])
    return cast("dict[str, object]", family["summary"])


def test_the_two_shapes_exercise_branches_the_other_cannot(
    published_forms: dict[str, tuple[dict[str, object], dict[str, object]]],
) -> None:
    """The fixtures' own witness: without it every pin below is vacuous.

    Two shapes and not one, because a single shape is satisfied by whichever
    translator happens to be canonical on it.  What each holds that the other
    does not is asserted here, so a fixture that quietly stops producing its
    branch reds instead of turning the pins that read it into tautologies.
    """

    single, _ = published_forms["single_contract"]
    double, _ = published_forms["two_contracts"]

    # The enforcement shape: three statuses under ONE contract, a violation
    # carrying evidence sites, and BOTH states of the report-only column.
    single_sinks = _owner_governed_sinks(single)
    assert len({str(row["authority_status"]) for row in single_sinks}) == 3
    assert any(row["unresolved_reasons"] for row in single_sinks)
    assert any(not row["unresolved_reasons"] for row in single_sinks)
    assert any(
        cast("list[object]", cast("dict[str, object]", violation)["locations"])
        for violation in cast("list[object]", _owner_form(single)["violations"])
    ), "the enforcement shape stopped producing an evidence location"

    # The ordering shape: two contracts whose identity order is the reverse of
    # their contract order.  A translator that ordered governed sinks by
    # ``sink_identity`` alone agrees with the owner on the shape above and
    # disagrees here -- that is the whole reason this tree exists.
    double_sinks = _owner_governed_sinks(double)
    assert len({str(row["contract_id"]) for row in double_sinks}) == 2
    identities = [str(row["sink_identity"]) for row in double_sinks]
    assert identities != sorted(identities), (
        "the ordering shape stopped inverting identity order against contract "
        "order; an order pin over it would prove nothing"
    )
    # Every row multi-reason and multi-root: a truncation or a re-order of
    # either list is observable on every row here, on one row above.
    for row in double_sinks:
        assert len(cast("list[object]", row["unresolved_reasons"])) > 1
        assert len(cast("list[object]", row["producer_root_ids"])) > 1

    # Which families each shape populates, so the column pin below cannot
    # quietly compare one emptiness against another.
    for shape, (document, _container) in published_forms.items():
        owner = _owner_form(document)
        populated = frozenset(
            family
            for family in _OWNER_COLUMNS_BY_FAMILY
            if cast("list[object]", owner[family])
        )
        assert populated == _POPULATED_FAMILIES[shape], shape


def test_all_three_published_governed_sink_forms_are_byte_identical(
    published_forms: dict[str, tuple[dict[str, object], dict[str, object]]],
) -> None:
    """One fact, three hand-written spellings, one answer -- on both shapes.

    Byte-identical over the columns all three publish, in each form's own row
    order.  The column restriction is the only normalisation, and the columns
    it drops are asserted by the narrowing pin rather than hidden here.
    """

    for shape, (document, container) in published_forms.items():
        owner = _shared_bytes(_owner_governed_sinks(document))
        rows = _shared_bytes(_rows_by_kind(document, "governed_sink"))
        wire = _shared_bytes(_wire_governed_sinks(container))
        assert rows == owner, shape
        assert wire == owner, shape


def test_the_governed_sink_order_is_one_derivation_in_every_form(
    published_forms: dict[str, tuple[dict[str, object], dict[str, object]]],
) -> None:
    """Why comparing the three row orders as sequences is not an accident.

    The producer emits governed sinks in registry order, the registry is
    required to be sorted by ``contract_id``, and ``_governed_functions``
    returns ``tuple(sorted(...))``; the document layer sorts its union rows by
    ``(item_kind, contract_id, sink_identity, ...)``.  Both therefore land on
    ``(contract_id, sink_identity)`` BY DERIVATION -- and pinning the
    derivation is what makes the byte equality above a proven no-op rather
    than a coincidence that would survive any order either side chose.
    """

    for shape, (document, container) in published_forms.items():
        for form, rows in (
            ("owner", _owner_governed_sinks(document)),
            ("rows", _rows_by_kind(document, "governed_sink")),
            ("wire", _wire_governed_sinks(container)),
        ):
            keys = _contract_keys(rows)
            assert keys == sorted(keys), f"{shape}/{form}"


def test_the_wire_form_narrows_by_exactly_one_named_column(
    published_forms: dict[str, tuple[dict[str, object], dict[str, object]]],
) -> None:
    """The difference between the forms, asserted instead of hidden.

    ``unresolved_reasons`` is declared report-only on the model itself: it
    explains why a sink abstained and is deliberately kept out of the lane, so
    a changed explanation cannot move a baseline lane digest.  That is a
    legitimate narrowing, and it is pinned HERE so the byte equality above can
    stay a value pin -- widening the lane reds this test and leaves that one
    green; drifting a shared column reds that one and leaves this green.

    The non-vacuity clause is the load-bearing half.  ``unresolved_reasons``
    is empty on most sinks, and an omission of an empty tuple asserts nothing,
    so both shapes are required to publish a sink that carries reasons.
    """

    for shape, (document, container) in published_forms.items():
        owner = _owner_governed_sinks(document)
        rows = _rows_by_kind(document, "governed_sink")
        wire = _wire_governed_sinks(container)
        assert owner and wire, shape
        owner_columns = set(owner[0])
        wire_columns = set(wire[0])
        assert owner_columns - wire_columns == {"unresolved_reasons"}, shape
        assert wire_columns - owner_columns == {"algorithm_revision"}, shape
        assert any(row["unresolved_reasons"] for row in owner), shape
        assert any(row["unresolved_reasons"] for row in rows), shape
        revision = _owner_form(document)["algorithm_revision"]
        assert {str(row["algorithm_revision"]) for row in wire} == {str(revision)}


def test_every_published_authority_row_reproduces_the_owners_columns(
    published_forms: dict[str, tuple[dict[str, object], dict[str, object]]],
) -> None:
    """The row form may translate the owner; it may not compute a new value.

    The document layer strips strings, coerces integers and sorts root lists
    on the way out.  Those stay projections only while every one of them is a
    no-op on the owner's own value -- so the pin is byte equality against the
    owner, indexed by each family's natural key because the two forms publish
    different row orders (the governed sinks' shared order has its own pin
    above).  ``locations`` rides the violation family here because no other
    stored family carries it: a drift in an evidence site has nowhere else to
    be seen.
    """

    for shape, (document, _container) in published_forms.items():
        owner = _owner_form(document)
        for family in sorted(_POPULATED_FAMILIES[shape]):
            columns = _OWNER_COLUMNS_BY_FAMILY[family]
            key = _NATURAL_KEY_BY_FAMILY[family]
            expected = _indexed_bytes(
                [
                    cast("dict[str, object]", item)
                    for item in cast("list[object]", owner[family])
                ],
                key=key,
                columns=columns,
            )
            published = _indexed_bytes(
                _rows_by_kind(document, _ROW_KIND_BY_FAMILY[family]),
                key=key,
                columns=columns,
            )
            assert published == expected, f"{shape}/{family}"


def test_the_published_authority_summary_counts_the_owners_own_families(
    published_forms: dict[str, tuple[dict[str, object], dict[str, object]]],
) -> None:
    """The summary is hand-written too, and nothing compared it to the owner.

    Every number in ``metrics.families.semantic_authority.summary`` is a count
    the row builder computes by hand over the same frozen result the document
    publishes beside it.  A count that drifts from its own population is the
    drift class this repository already measured once, when a hand-listed
    family set silently dropped three families out of a document that carried
    them.

    ``sinks_by_status`` is held two ways, and neither restates the bucket list
    here: every bucket the payload declares must carry the owner's own count
    for that status, and every status the owner actually produced must have a
    bucket.  Importing ``AuthorityStatus`` to pin the vocabulary itself would
    be the stronger pin and is deliberately not taken -- this module is an
    ``r4`` test and the Phase 39S boundary ratchet forbids it reaching into
    ``r2``; the honest cost is that a status added to the model which no
    fixture produces would not be missed here.
    """

    for shape, (document, _container) in published_forms.items():
        owner = _owner_form(document)
        summary = _family_summary(document)
        contract_ir = cast("dict[str, object]", owner["contract_ir"])
        violations = [
            cast("dict[str, object]", item)
            for item in cast("list[object]", owner["violations"])
        ]
        active = sum(not violation["suppressed"] for violation in violations)
        expected: dict[str, object] = {
            "sinks": len(cast("list[object]", owner["sinks"])),
            "candidates": len(cast("list[object]", owner["candidates"])),
            "governed_sinks": len(_owner_governed_sinks(document)),
            "violations": len(violations),
            "active_violations": active,
            "suppressed_violations": len(violations) - active,
            "contracts": len(cast("list[object]", contract_ir["contracts"])),
            "scc_count": len(cast("list[object]", contract_ir["sccs"])),
            "fixpoint_iterations": contract_ir["fixpoint_iterations"],
            "algorithm_revision": owner["algorithm_revision"],
        }
        assert {name: summary[name] for name in expected} == expected, shape
        by_status = Counter(
            str(cast("dict[str, object]", item)["authority_status"])
            for item in cast("list[object]", owner["sinks"])
        )
        buckets = cast("dict[str, object]", summary["sinks_by_status"])
        assert {name: by_status[name] for name in buckets} == buckets, shape
        assert set(by_status) <= set(buckets), shape
