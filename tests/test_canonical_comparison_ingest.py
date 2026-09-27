# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical epoch E2 (2026-09-26): the comparison families, produced and
read back — the producer-native snapshot against the ingest oracle over the
document the SAME execution rendered, on six populations that between them
carry every state the families distinguish.

The populations are accounted for before anything is compared (Probe
Validity Law): a comparison of two empty houses, or of two houses that both
say ``compared`` everywhere, proves nothing about the words they did not
carry.  The accounting literals are measurements of the comparison corpus
(``tests/conftest.py``), taken 2026-09-26.
"""

from __future__ import annotations

import ast
import copy
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from codeclone.canonical import RunStore
from codeclone.canonical.comparison_ingest import comparison_facts_from_document
from codeclone.canonical.comparison_rows import (
    COMPARISON_LANE_FAMILIES,
    baseline_statuses_stated,
)
from codeclone.canonical.errors import LegacyIngestError
from codeclone.canonical.ingest import canonical_model_from_legacy_document
from codeclone.canonical.model import ComparisonFacts, novelty_families
from tests._served_run import ServedRunStoreProjection
from tests.conftest import (
    COMPARISON_POPULATIONS,
    ComparisonRun,
    RunStoreCorpusRunner,
)

_REPORTING = Path(__file__).resolve().parents[1] / "codeclone" / "core" / "reporting.py"


def _novelty(house: ComparisonFacts) -> dict[str, dict[tuple[str, str | None], int]]:
    return {
        family: dict(Counter((row.novelty, row.novelty_reason) for row in rows))
        for family, rows in novelty_families(house)
    }


def _availability(house: ComparisonFacts) -> dict[str, str]:
    return {row.lane: row.availability for row in house.comparison_availability}


def _deltas(house: ComparisonFacts) -> dict[str, dict[str, int]]:
    return {
        "adoption_delta": {row.delta: row.value for row in house.adoption_delta},
        "api_surface_delta": {row.delta: row.value for row in house.api_surface_delta},
    }


_ALL_COMPARED = dict.fromkeys(
    (
        "adoption_counts",
        "api_surface",
        "clones.blocks",
        "clones.functions",
        "coupling_cohesion_observations",
        "dead_code",
        "dependencies",
        "risk_observations",
    ),
    "compared",
)
_KNOWN_AND_NEW = {
    "clone_novelty": {("known", None): 3, ("new", None): 1},
    "complexity_novelty": {("known", None): 1, ("new", None): 1},
    "coupling_novelty": {("new", None): 1},
    "dead_symbol_novelty": {("known", None): 1, ("new", None): 1},
    "dependency_cycle_novelty": {("known", None): 3, ("new", None): 1},
}
_LANE_UNAVAILABLE = {
    "clone_novelty": {("unavailable", "lane_unavailable"): 4},
    "complexity_novelty": {("unavailable", "lane_unavailable"): 2},
    "coupling_novelty": {("unavailable", "lane_unavailable"): 1},
    "dead_symbol_novelty": {("unavailable", "lane_unavailable"): 2},
    "dependency_cycle_novelty": {("unavailable", "lane_unavailable"): 4},
}
#: Three distinct measured values each, so a swapped term cannot pass.
_ADOPTION = {
    "docstring_permille_delta": 17,
    "typing_param_permille_delta": -103,
    "typing_return_permille_delta": -44,
}
_API = {"api_breaking_changes": 2, "api_signature_changes": 1, "new_api_symbols": 37}


# ---------------------------------------------------------------------------
# Producer-native == oracle, one execution, every population.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("population", sorted(COMPARISON_POPULATIONS))
def test_the_comparison_families_agree_between_producer_and_oracle(
    comparison_runs: dict[str, ComparisonRun], population: str
) -> None:
    run = comparison_runs[population]
    oracle = canonical_model_from_legacy_document(run.document).facts.comparison
    assert run.stored.facts.comparison.baseline_witness is not None
    assert run.stored.facts.comparison == oracle


def test_the_compared_population_carries_both_verdicts_everywhere(
    comparison_runs: dict[str, ComparisonRun],
) -> None:
    house = comparison_runs["compared"].stored.facts.comparison
    witness = house.baseline_witness
    assert witness is not None
    assert (witness.state, witness.loaded, witness.status) == ("trusted", True, "ok")
    assert witness.baseline_scope_id == "9e6a3f60-1df0-4c1e-9f3a-6f2f4b6a0c11"
    assert witness.root_digest == witness.payload_sha256
    assert _availability(house) == _ALL_COMPARED
    assert house.disabled_capabilities == frozenset()
    assert _novelty(house) == _KNOWN_AND_NEW
    assert _deltas(house) == {
        "adoption_delta": _ADOPTION,
        "api_surface_delta": _API,
    }


def test_the_partial_population_is_compared_and_not_compared_at_once(
    comparison_runs: dict[str, ComparisonRun],
) -> None:
    """The ``not_compared`` word: a trusted lane whose current half was never
    observed.  The clone lanes and the adoption lane still compared."""
    house = comparison_runs["partial"].stored.facts.comparison
    assert _availability(house) == {
        **_ALL_COMPARED,
        "api_surface": "not_compared",
        "coupling_cohesion_observations": "not_compared",
        "dead_code": "not_compared",
        "dependencies": "not_compared",
        "risk_observations": "not_compared",
    }
    assert _deltas(house) == {"adoption_delta": _ADOPTION, "api_surface_delta": {}}


def test_a_lane_the_run_did_not_enable_is_the_fourth_state(
    comparison_runs: dict[str, ComparisonRun],
) -> None:
    """``disabled`` is a disabled capability, never an availability word:
    the lane has no availability row, and its results are absent."""
    api = comparison_runs["api_disabled"].stored.facts.comparison
    assert {row.lane for row in api.disabled_capabilities} == {"api_surface"}
    assert "api_surface" not in _availability(api)
    assert api.api_surface_delta == frozenset()
    skipped = comparison_runs["lanes_skipped"].stored.facts.comparison
    assert {row.lane for row in skipped.disabled_capabilities} == {
        "dead_code",
        "dependencies",
    }
    assert set(_availability(skipped)) == set(_ALL_COMPARED) - {
        "dead_code",
        "dependencies",
    }
    assert _novelty(skipped)["dead_symbol_novelty"] == {}
    assert _novelty(skipped)["dependency_cycle_novelty"] == {}


def test_a_foreign_container_leaves_every_lane_unavailable(
    comparison_runs: dict[str, ComparisonRun],
) -> None:
    """The container of another scope: every lane untrusted, every governed
    finding unavailable — and, as the producer publishes it (measured, on
    the desk), the CLI still calls the metrics baseline loaded and states the
    adoption and API deltas against it."""
    house = comparison_runs["foreign_scope"].stored.facts.comparison
    witness = house.baseline_witness
    assert witness is not None
    assert (witness.state, witness.loaded, witness.status) == ("untrusted", True, "ok")
    assert {(row.status, row.reason) for row in house.lane_trust} == {
        ("unavailable", "baseline_scope_id")
    }
    assert _availability(house) == {
        **dict.fromkeys(_ALL_COMPARED, "unavailable"),
        "adoption_counts": "compared",
        "api_surface": "compared",
    }
    assert _novelty(house) == _LANE_UNAVAILABLE


def test_no_container_is_a_missing_witness_and_no_results(
    comparison_runs: dict[str, ComparisonRun],
) -> None:
    house = comparison_runs["missing"].stored.facts.comparison
    witness = house.baseline_witness
    assert witness is not None
    assert (witness.state, witness.loaded, witness.status) == (
        "missing",
        False,
        "missing",
    )
    assert (witness.baseline_scope_id, witness.root_digest) == (None, None)
    assert {(row.status, row.reason) for row in house.lane_trust} == {
        ("unavailable", "baseline_missing")
    }
    assert _availability(house) == dict.fromkeys(_ALL_COMPARED, "unavailable")
    assert _novelty(house) == _LANE_UNAVAILABLE
    assert _deltas(house) == {"adoption_delta": {}, "api_surface_delta": {}}


def test_the_populations_carry_every_distinguishing_state(
    comparison_runs: dict[str, ComparisonRun],
) -> None:
    """The union the equivalence above is measured over: three witness
    states, three availability words beside the fourth state, three novelty
    words, deltas present and absent."""
    houses = [run.stored.facts.comparison for run in comparison_runs.values()]
    assert {
        house.baseline_witness.state
        for house in houses
        if house.baseline_witness is not None
    } == {"trusted", "untrusted", "missing"}
    assert {word for house in houses for word in _availability(house).values()} == {
        "compared",
        "not_compared",
        "unavailable",
    }
    assert any(house.disabled_capabilities for house in houses)
    assert {
        row.novelty
        for house in houses
        for _f, rows in novelty_families(house)
        for row in rows
    } == {"new", "known", "unavailable"}
    assert any(house.adoption_delta for house in houses)
    assert any(not house.adoption_delta for house in houses)


# ---------------------------------------------------------------------------
# The oracle on its own: absent is unwitnessed, malformed is refused, the one
# per-group absence is read.
# ---------------------------------------------------------------------------


def _document(comparison_runs: dict[str, ComparisonRun]) -> dict[str, Any]:
    return copy.deepcopy(comparison_runs["compared"].document)


def test_a_document_without_a_comparison_section_is_unwitnessed(
    comparison_runs: dict[str, ComparisonRun],
) -> None:
    document = _document(comparison_runs)
    del document["baseline"]
    assert comparison_facts_from_document(document) == ComparisonFacts()


@pytest.mark.parametrize("block", ["baseline", "metrics_baseline"])
def test_a_meta_stating_no_baseline_status_witnessed_no_comparison(
    comparison_runs: dict[str, ComparisonRun], block: str
) -> None:
    """The precondition both sides read (``baseline_statuses_stated``): a
    meta that states no status for either baseline — what ``report`` renders
    for a caller that hands it an empty meta — witnessed no comparison.  The
    untouched document is the other boundary."""
    document = _document(comparison_runs)
    assert baseline_statuses_stated(document["meta"])
    document["meta"][block]["status"] = None
    assert not baseline_statuses_stated(document["meta"])
    assert comparison_facts_from_document(document) == ComparisonFacts()


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("baseline", "state"), 3, "baseline.state is not a string"),
        (
            ("meta", "baseline", "loaded"),
            "yes",
            "meta.baseline.loaded is not a boolean",
        ),
        (("baseline", "sorted_lane_trust"), {}, "is not an array"),
        (("baseline", "root_digest_or_null"), 7, "neither a string nor null"),
    ],
)
def test_a_malformed_comparison_member_is_refused(
    comparison_runs: dict[str, ComparisonRun],
    path: tuple[str, ...],
    value: object,
    match: str,
) -> None:
    document = _document(comparison_runs)
    container: Any = document
    for key in path[:-1]:
        container = container[key]
    container[path[-1]] = value
    with pytest.raises(LegacyIngestError, match=match):
        comparison_facts_from_document(document)


def test_a_missing_delta_term_is_refused(
    comparison_runs: dict[str, ComparisonRun],
) -> None:
    document = _document(comparison_runs)
    del document["metrics"]["families"]["coverage_adoption"]["summary"]["param_delta"]
    with pytest.raises(LegacyIngestError, match="param_delta"):
        comparison_facts_from_document(document)


def test_a_trusted_clone_lane_its_groups_call_uncompared_is_not_compared(
    comparison_runs: dict[str, ComparisonRun],
) -> None:
    """The one absence the document spells per group: a trusted lane whose
    groups say ``comparison_unavailable`` was not compared.  Both boundaries:
    the same document without that reason reads as compared."""
    document = _document(comparison_runs)
    for group in document["findings"]["groups"]["clones"]["blocks"]:
        group["novelty"] = "unavailable"
        group["novelty_reason"] = "comparison_unavailable"
    availability = _availability(comparison_facts_from_document(document))
    assert availability["clones.blocks"] == "not_compared"
    assert availability["clones.functions"] == "compared"


def test_the_lane_family_pairing_is_the_reporting_one() -> None:
    """``COMPARISON_LANE_FAMILIES`` restates, for the four set-difference
    lanes, the pairing ``core.reporting._metrics_for_report`` writes the
    ``baseline_diff_available`` flags under — pinned against that SOURCE, so
    a pairing moved there reds here instead of silently misfiling a lane."""
    pairs: set[tuple[str, str]] = set()
    for node in ast.walk(ast.parse(_REPORTING.read_text("utf-8"))):
        if not (isinstance(node, ast.Tuple) and len(node.elts) == 4):
            continue
        family, lanes = node.elts[0], node.elts[1]
        if (
            isinstance(family, ast.Constant)
            and isinstance(lanes, ast.Tuple)
            and len(lanes.elts) == 1
            and isinstance(lanes.elts[0], ast.Constant)
        ):
            pairs.add((str(family.value), str(lanes.elts[0].value)))
    expected = {
        (family, lane)
        for lane, family in COMPARISON_LANE_FAMILIES.items()
        if lane not in {"adoption_counts", "api_surface"}
    }
    assert expected == pairs


# ---------------------------------------------------------------------------
# An MCP-published run: the store the surface wrote, against the oracle.
# ---------------------------------------------------------------------------


def test_the_comparison_families_of_an_mcp_published_run_agree_with_the_oracle(
    served_run_store_projection: ServedRunStoreProjection,
    run_store_cli: RunStoreCorpusRunner,
    tmp_path: Path,
) -> None:
    """The baseline-less serving corpus, published by the MCP surface, read
    back against the oracle over a CLI document of a copy of its tree: the
    MCP and CLI doors differ in how they hand the comparison to ``report``
    (the CLI flattens an uncompared clone lane to an empty set), and the
    store must read both the way the document does."""
    with RunStore(served_run_store_projection.store_path) as store:
        published = store.read_run(served_run_store_projection.store_run_id)
    root = tmp_path / "tree"
    shutil.copytree(served_run_store_projection.root, root)
    report_path = tmp_path / "report.json"
    run_store_cli(root, "--json", str(report_path), store=None)
    oracle = canonical_model_from_legacy_document(
        json.loads(report_path.read_text("utf-8"))
    ).facts.comparison
    house = published.facts.comparison
    assert house.baseline_witness is not None
    assert house.baseline_witness.state == "missing"
    assert house.clone_novelty, "the serving corpus carries a clone pair"
    assert house == oracle
