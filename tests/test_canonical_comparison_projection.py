# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shadow equivalence of the comparison tier (canonical epoch E2, cycle 3).

Every comparison-tier field serving census 3 names for this wave, as the
MCP surface answered it, against ``codeclone.canonical.comparison_projection``
over the run THAT SAME execution published: the surface is the oracle, the
store rows the shadow.  Four served populations, each a real MCP execution
(``tests/conftest.py``): the comparison corpus against a trusted baseline,
against a container of a foreign scope (refused by the surface's resolver),
with the API lane not enabled, and the baseline-less serving corpus.

Where the surface says something the store does not, the difference is
pinned as measured and named — never fitted: the API deltas the surface
states for a run whose API lane was not enabled
(``test_the_surface_states_api_deltas_for_a_lane_the_run_disabled``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

import pytest

from codeclone.canonical.comparison_projection import (
    DIFF_DELTA_KEYS,
    SOURCE_KIND_BREAKDOWN,
    UNPROJECTED_BASELINE_KEYS,
    UNPROJECTED_DIFF_KEYS,
    baseline_state,
    group_novelty,
    known_debt_paths,
    metric_deltas,
    metrics_baseline_state,
    new_by_source_kind,
    new_clone_groups,
    new_finding_paths,
    novelty_counts,
)
from codeclone.canonical.comparison_rows import DELTA_FAMILY_TERMS
from codeclone.canonical.model import CanonicalModel, ComparisonFacts
from codeclone.canonical.store import RunStore
from codeclone.domain.findings import FAMILY_AUTHORITY
from codeclone.utils.coerce import as_mapping, as_sequence
from tests._served_run import ServedComparisonRun, ServedRunStoreProjection
from tests.conftest import (
    SERVED_COMPARISON_BLAST_ORIGINS,
    SERVED_COMPARISON_CHANGED_PATHS,
    SERVED_COMPARISON_POPULATIONS,
)

_Answers = Mapping[str, Mapping[str, object]]


class _Served(NamedTuple):
    name: str
    model: CanonicalModel
    answers: _Answers


def _read(store_path: Path, run_id: str) -> CanonicalModel:
    with RunStore(store_path) as store:
        return store.read_run(run_id)


def _comparison_served(run: ServedComparisonRun) -> _Served:
    return _Served(run.name, _read(run.store_path, run.store_run_id), run.answers)


def _missing_served(projection: ServedRunStoreProjection) -> _Served:
    return _Served(
        "missing",
        _read(projection.store_path, projection.store_run_id),
        {
            "run_summary": projection.run_summary,
            "production_triage": projection.production_triage,
        },
    )


def _served_population(request: pytest.FixtureRequest, name: str) -> _Served:
    if name == "missing":
        return _missing_served(request.getfixturevalue("served_run_store_projection"))
    runs: dict[str, ServedComparisonRun] = request.getfixturevalue(
        "served_comparison_runs"
    )
    return _comparison_served(runs[name])


@pytest.fixture(params=["missing", *SERVED_COMPARISON_POPULATIONS])
def served(request: pytest.FixtureRequest) -> _Served:
    """All four served populations, one at a time."""
    return _served_population(request, request.param)


#: The populations whose ``diff`` agrees with the store on every key: the
#: API-disabled run is the measured divergence pinned on its own below.
_DIFF_AGREEING = ("missing", "trusted", "foreign_scope")


@pytest.fixture(params=_DIFF_AGREEING)
def served_diff(request: pytest.FixtureRequest) -> _Served:
    return _served_population(request, request.param)


@pytest.fixture(params=list(SERVED_COMPARISON_POPULATIONS))
def served_comparison(request: pytest.FixtureRequest) -> _Served:
    """The three comparison-corpus populations (the PR summary, the
    authority check and the blast radius are asked there only)."""
    runs: dict[str, ServedComparisonRun] = request.getfixturevalue(
        "served_comparison_runs"
    )
    return _comparison_served(runs[request.param])


def _canonical(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _answer(served: _Served, label: str) -> Mapping[str, object]:
    return as_mapping(served.answers[label])


# -- C1.08 / C2.04 / C1.09 (C6v.11's comparison input): the two witnesses ------


@pytest.mark.parametrize("label", ["run_summary", "production_triage"])
def test_the_baseline_block_matches_the_mcp_surface(
    served: _Served, label: str
) -> None:
    """``baseline`` byte for byte without the two execution keys, which the
    surface always states beside it and the store never carries."""
    block = as_mapping(_answer(served, label)["baseline"])
    projected = baseline_state(served.model.facts.comparison)
    assert projected, "every served run witnesses its baseline"
    assert set(block) - set(projected) <= set(UNPROJECTED_BASELINE_KEYS)
    assert "interpreter_provenance" in block
    surface = {
        key: value
        for key, value in block.items()
        if key not in UNPROJECTED_BASELINE_KEYS
    }
    assert _canonical(projected) == _canonical(surface)


def test_the_metrics_baseline_block_matches_the_mcp_surface(served: _Served) -> None:
    block = _answer(served, "run_summary")["metrics_baseline"]
    projected = metrics_baseline_state(served.model.facts.comparison)
    assert projected
    assert _canonical(projected) == _canonical(block)


# -- C1.17 / C1.20 / C2.09: novelty over the published universe -----------------


def test_the_novelty_counts_match_the_mcp_surface(served: _Served) -> None:
    findings = as_mapping(_answer(served, "run_summary")["findings"])
    counts = novelty_counts(served.model)
    assert counts == {word: findings[word] for word in ("new", "known", "unavailable")}
    assert sum(counts.values()) == findings["total"]


@pytest.mark.parametrize("label", ["run_summary", "production_triage"])
def test_new_by_source_kind_matches_the_mcp_surface(
    served: _Served, label: str
) -> None:
    findings = as_mapping(_answer(served, label)["findings"])
    projected = new_by_source_kind(served.model)
    assert tuple(projected) == SOURCE_KIND_BREAKDOWN
    assert _canonical(projected) == _canonical(findings["new_by_source_kind"])


# -- C1.21 / C1.23: the ``diff`` block ---------------------------------------------


def _projected_diff(comparison: ComparisonFacts) -> dict[str, object]:
    return {
        "new_clones": new_clone_groups(comparison),
        **metric_deltas(comparison),
    }


def _surface_diff(served: _Served) -> dict[str, object]:
    diff = as_mapping(_answer(served, "run_summary")["diff"])
    assert set(UNPROJECTED_DIFF_KEYS) <= set(diff)
    return {
        key: value for key, value in diff.items() if key not in UNPROJECTED_DIFF_KEYS
    }


def test_the_diff_block_matches_the_mcp_surface(served_diff: _Served) -> None:
    """``new_clones`` and the six deltas byte for byte, in the surface's
    order — on every population whose API lane ran or had nothing to
    compare against (the API-disabled run is the divergence below)."""
    comparison = served_diff.model.facts.comparison
    assert _canonical(_projected_diff(comparison)) == _canonical(
        _surface_diff(served_diff)
    )


_API_TERMS = DELTA_FAMILY_TERMS["api_surface_delta"]


#: The measured divergences (2026-09-27): for a run whose API comparison
#: did not run, what the store says about the lane, and the ``diff`` terms
#: the surface nevertheless states.
_API_DIVERGENCE: dict[str, tuple[str, frozenset[str]]] = {
    "api_disabled": ("disabled", frozenset({"api_breaking_changes"})),
    "partial": ("not_compared", frozenset(_API_TERMS)),
}


def _api_lane_state(comparison: ComparisonFacts) -> str:
    if "api_surface" in {row.lane for row in comparison.disabled_capabilities}:
        return "disabled"
    return next(
        row.availability
        for row in comparison.comparison_availability
        if row.lane == "api_surface"
    )


@pytest.mark.parametrize("name", list(_API_DIVERGENCE))
def test_the_surface_states_api_deltas_for_an_api_comparison_that_did_not_run(
    served_comparison_runs: dict[str, ServedComparisonRun], name: str
) -> None:
    """DIVERGENCE on the desk, measured 2026-09-27, not fitted: when the
    API comparison did not run — the lane not enabled (a disabled
    capability), or enabled over a partial population (trusted and not
    compared: the current universe was not observed) — the store carries
    no API delta, while the surface's ``diff`` reads the metrics diff raw
    and states API counts anyway (every baseline symbol as a breaking
    change on the first; all three counts on the second).  Every other key
    agrees byte for byte."""
    served = _comparison_served(served_comparison_runs[name])
    comparison = served.model.facts.comparison
    state, divergent = _API_DIVERGENCE[name]
    assert _api_lane_state(comparison) == state
    assert not comparison.api_surface_delta
    projected = _projected_diff(comparison)
    surface = _surface_diff(served)
    assert {key for key in projected if projected[key] != surface[key]} == divergent
    assert [projected[term] for term in _API_TERMS] == [0, 0, 0]
    assert all(isinstance(surface[term], int) for term in divergent)


#: The two delta families the ``diff`` block's six deltas belong to.
_DIFF_DELTA_FAMILIES = ("adoption_delta", "api_surface_delta")


def test_the_delta_keys_are_the_delta_families_terms() -> None:
    terms = {
        term for family in _DIFF_DELTA_FAMILIES for term in DELTA_FAMILY_TERMS[family]
    }
    assert set(DIFF_DELTA_KEYS) == terms
    assert len(DIFF_DELTA_KEYS) == len(set(DIFF_DELTA_KEYS))


def test_the_health_delta_is_the_one_term_outside_the_diff_deltas() -> None:
    """The health term (canonical epoch E3, the delta of ``health_result``)
    is the third delta family: it answers ``diff.health_delta`` beside the
    health verdict, not among the six metric deltas."""
    assert set(DELTA_FAMILY_TERMS) == {*_DIFF_DELTA_FAMILIES, "health_delta"}
    assert set(DELTA_FAMILY_TERMS["health_delta"]) == set(UNPROJECTED_DIFF_KEYS)


# -- C5.07: the PR summary's new findings --------------------------------------------


def _pr_new_ids(served: _Served, label: str) -> list[str]:
    items = as_sequence(_answer(served, label)["new_findings_in_changed_files"])
    return sorted(str(as_mapping(item)["canonical_id"]) for item in items)


def test_the_pr_summary_new_findings_match_the_projection(
    served_comparison: _Served,
) -> None:
    """The ids the comparison called new, over the repository and over two
    changed files (one new and one known hotspot): the novelty filter is
    the store's, the path filter the sites' (the surface matches a changed
    FILE by equality with a site's path)."""
    sites = new_finding_paths(served_comparison.model)
    assert _pr_new_ids(served_comparison, "pr_summary") == sorted(sites)
    changed = set(SERVED_COMPARISON_CHANGED_PATHS)
    assert _pr_new_ids(served_comparison, "pr_summary_changed") == sorted(
        finding_id for finding_id, paths in sites.items() if changed & set(paths)
    )
    answer = _answer(served_comparison, "pr_summary_changed")
    assert answer["findings_scope"] == "changed_files"


# -- C8v.10: the authority check's novelty ------------------------------------------


def test_the_authority_novelty_matches_the_projection(
    served_comparison: _Served,
) -> None:
    """Authority violations have no comparison term: no novelty row names
    them, and the surface says ``unavailable`` for each — also where the
    same baseline calls the other families new and known."""
    answer = _answer(served_comparison, "check_authority")
    items = [as_mapping(item) for item in as_sequence(answer["items"])]
    assert answer["total"] == len(items), "the check returned every violation"
    novelty = group_novelty(served_comparison.model)
    authority_ids = {
        finding_id
        for finding_id in novelty
        if finding_id.startswith(f"{FAMILY_AUTHORITY}:")
    }
    assert {str(item["id"]): item["novelty"] for item in items} == {
        finding_id: novelty[finding_id] for finding_id in authority_ids
    }


# -- C7.15: the known-debt review context of the blast radius ------------------------


@pytest.mark.parametrize("label", list(SERVED_COMPARISON_BLAST_ORIGINS))
def test_the_known_debt_review_context_matches_the_projection(
    served_comparison: _Served, label: str
) -> None:
    """``review_context`` entries of category ``known_baseline_debt`` are
    the projected known-debt paths inside the blast zone the same answer
    states (origin, dependents, clone cohort), the origin excluded."""
    origin, _depth = SERVED_COMPARISON_BLAST_ORIGINS[label]
    answer = _answer(served_comparison, label)
    zone = {
        origin,
        *(
            str(path)
            for key in (
                "direct_dependents",
                "transitive_dependents",
                "clone_cohort_members",
            )
            for path in as_sequence(answer[key])
        ),
    }
    surface = sorted(
        str(entry["path"])
        for entry in (as_mapping(raw) for raw in as_sequence(answer["review_context"]))
        if entry["category"] == "known_baseline_debt"
    )
    assert surface == [
        path
        for path in known_debt_paths(served_comparison.model)
        if path in zone and path != origin
    ]


# -- Probe Validity: the populations carry the distinguishing cases ------------------


def _witness_line(served: _Served) -> tuple[object, ...]:
    block = baseline_state(served.model.facts.comparison)
    return (block["loaded"], block["status"], "baseline_python_tag" in block)


def _served_runs(
    runs: dict[str, ServedComparisonRun], missing: ServedRunStoreProjection
) -> dict[str, _Served]:
    served = {name: _comparison_served(run) for name, run in runs.items()}
    served["missing"] = _missing_served(missing)
    return served


def test_the_served_populations_carry_every_witness_and_novelty_state(
    served_comparison_runs: dict[str, ServedComparisonRun],
    served_run_store_projection: ServedRunStoreProjection,
) -> None:
    """Measured 2026-09-27: the trusted run utters all three novelty words
    and a ``mixed`` new finding; the witness is loaded, refused and
    missing across the populations; the clone count is a number where a
    clone lane was compared and absent where none was."""
    runs = _served_runs(served_comparison_runs, served_run_store_projection)
    trusted = runs["trusted"]
    assert novelty_counts(trusted.model) == {"new": 6, "known": 8, "unavailable": 4}
    kinds = new_by_source_kind(trusted.model)
    assert (kinds["production"], kinds["mixed"]) == (5, 1)
    assert {name: _witness_line(run) for name, run in runs.items()} == {
        "trusted": (True, "ok", True),
        "foreign_scope": (False, "mismatch_scope_id", True),
        "api_disabled": (True, "ok", True),
        "partial": (True, "ok", True),
        "missing": (False, "missing", False),
    }
    assert new_clone_groups(trusted.model.facts.comparison) == 2
    assert new_clone_groups(runs["foreign_scope"].model.facts.comparison) is None


def test_the_served_populations_carry_every_availability_state(
    served_comparison_runs: dict[str, ServedComparisonRun],
) -> None:
    """Measured 2026-09-27: the availability takes all four states —
    compared, not compared (the partial run), unavailable, and the
    disabled capability beside them; known debt sits in one blast zone
    and not the other; the authority violations exist where the baseline
    is trusted, and the changed-file PR summary cuts one new finding."""
    runs = {
        name: _comparison_served(run) for name, run in served_comparison_runs.items()
    }
    words = {
        name: {
            row.availability
            for row in run.model.facts.comparison.comparison_availability
        }
        for name, run in runs.items()
    }
    assert words == {
        "trusted": {"compared"},
        "foreign_scope": {"unavailable"},
        "api_disabled": {"compared"},
        "partial": {"compared", "not_compared"},
    }
    assert _api_lane_state(runs["api_disabled"].model.facts.comparison) == "disabled"
    trusted = runs["trusted"]
    assert _known_debt_entries(trusted, "blast_known") == [
        "pkg/tri_b.py",
        "pkg/tri_c.py",
    ]
    assert _known_debt_entries(trusted, "blast_new") == []
    authority = as_sequence(_answer(trusted, "check_authority")["items"])
    assert len(authority) == 3
    assert _pr_new_ids(trusted, "pr_summary_changed") == [
        "design:complexity:pkg.complex_new:new_tangle"
    ]


def _known_debt_entries(served: _Served, label: str) -> list[str]:
    return sorted(
        str(as_mapping(entry)["path"])
        for entry in as_sequence(_answer(served, label)["review_context"])
        if as_mapping(entry)["category"] == "known_baseline_debt"
    )


# -- the empty house ----------------------------------------------------------------


def test_an_unwitnessed_house_answers_empty_blocks_and_no_clone_count() -> None:
    house = ComparisonFacts()
    assert baseline_state(house) == {}
    assert metrics_baseline_state(house) == {}
    assert new_clone_groups(house) is None
    assert metric_deltas(house) == dict.fromkeys(DIFF_DELTA_KEYS, 0)
