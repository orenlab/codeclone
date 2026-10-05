# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One normalized state of the comparison deltas (ruling 2026-10-03/05).

The carrier (``contracts.comparison_state``) is held by its own laws; the
producer (``core.comparison_state``) writes the document from it; the two
readers -- the stored run's rows and the sealed document -- read back the
SAME typed state on every served population, value and reason alike; and a
ratchet holds every module that still reads a raw comparison count or the
availability flag around the carrier to a table that only shrinks.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

from codeclone.canonical.comparison_projection import stored_comparison_state
from codeclone.canonical.comparison_state import (
    ComparisonResult,
    ComparisonState,
    compared,
    comparison_results,
    comparison_state,
    document_comparison_state,
    not_compared,
)
from codeclone.canonical.store import RunStore
from codeclone.contracts.comparison_state import (
    COMPARISON_API_SURFACE,
    COMPARISON_HEALTH,
    COMPARISON_KEYS,
    COMPARISON_LANES,
    COMPARISON_TERMS,
    NOT_COMPARED_DISABLED,
    NOT_COMPARED_NOT_RUN,
    NOT_COMPARED_UNAVAILABLE,
    not_compared_reason,
)
from codeclone.report.gates.evaluator import HEALTH_INPUT_LANES
from codeclone.utils.coerce import as_mapping
from tests._run_summary_serving import RUN_SUMMARY_POPULATIONS, shared_populations

# -- the carrier's own laws --------------------------------------------------------


def test_a_result_is_a_value_or_a_reason_never_both_never_neither() -> None:
    assert compared(0) == ComparisonResult(value=0, reason=None)
    assert compared(0).is_compared
    assert not not_compared(NOT_COMPARED_NOT_RUN).is_compared
    with pytest.raises(ValueError, match="not both"):
        ComparisonResult(value=0, reason=NOT_COMPARED_NOT_RUN)
    with pytest.raises(ValueError, match="not both"):
        ComparisonResult(value=None, reason=None)


def test_a_state_states_every_key_exactly() -> None:
    every = {key: compared(1) for key in COMPARISON_KEYS}
    assert comparison_state(every).comparisons_made() == frozenset(COMPARISON_TERMS)
    missing = dict(every)
    missing.pop(COMPARISON_KEYS[0])
    with pytest.raises(ValueError, match="every comparison key"):
        ComparisonState(results=missing)
    with pytest.raises(ValueError, match="every comparison key"):
        ComparisonState(results={**every, ("health", "extra"): compared(1)})


@pytest.mark.parametrize(
    ("enabled", "lanes_trusted", "reason"),
    [
        (False, False, NOT_COMPARED_DISABLED),
        (False, True, NOT_COMPARED_DISABLED),
        (True, False, NOT_COMPARED_UNAVAILABLE),
        (True, True, NOT_COMPARED_NOT_RUN),
    ],
)
def test_the_reason_is_named_by_one_rule(
    *, enabled: bool, lanes_trusted: bool, reason: str
) -> None:
    assert not_compared_reason(enabled=enabled, lanes_trusted=lanes_trusted) == reason


def test_only_ran_on_an_enabled_capability_states_a_value() -> None:
    """``ran`` decides and a measured zero is a number; a capability the run
    did not enable never ran, whatever ``ran`` says."""
    values = dict.fromkeys(COMPARISON_TERMS[COMPARISON_API_SURFACE], 0)
    ran = comparison_results(
        COMPARISON_API_SURFACE, values, ran=True, enabled=True, lanes_trusted=True
    )
    assert {result.value for result in ran.values()} == {0}
    disabled = comparison_results(
        COMPARISON_API_SURFACE, values, ran=True, enabled=False, lanes_trusted=True
    )
    assert {result.reason for result in disabled.values()} == {NOT_COMPARED_DISABLED}
    not_run = comparison_results(
        COMPARISON_API_SURFACE, {}, ran=False, enabled=True, lanes_trusted=False
    )
    assert {result.reason for result in not_run.values()} == {NOT_COMPARED_UNAVAILABLE}


def test_the_health_gate_manifest_is_the_health_comparisons_lanes() -> None:
    """One table, not two equal ones: the gate matrix's health manifest IS
    the health comparison's lanes, so a second spelling cannot drift."""
    assert HEALTH_INPUT_LANES is COMPARISON_LANES[COMPARISON_HEALTH]


# -- the two readers read one state ------------------------------------------------


@pytest.fixture(scope="module")
def population_states(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, tuple[ComparisonState, ComparisonState, dict[str, object]]]:
    """Per population: the state read off the stored rows, the state read
    off the sealed document, and the document's API family summary."""
    populations = shared_populations(tmp_path_factory)
    states = {}
    for name in RUN_SUMMARY_POPULATIONS:
        record = populations[name].record
        link = record.execution.run_snapshot_link
        assert link is not None and link.store_run_id
        with RunStore(populations[name].store_path, create=False) as store:
            model = store.read_run(link.store_run_id)
        new_clones = as_mapping(record.summary.get("baseline_diff")).get(
            "new_clone_groups_total"
        )
        document = record.served_report
        families = as_mapping(as_mapping(document.get("metrics")).get("families"))
        states[name] = (
            stored_comparison_state(model),
            document_comparison_state(document, new_clone_groups=new_clones),
            dict(as_mapping(as_mapping(families.get("api_surface")).get("summary"))),
        )
    return states


def test_the_store_and_the_document_read_one_state_on_every_population(
    population_states: dict[
        str, tuple[ComparisonState, ComparisonState, dict[str, object]]
    ],
) -> None:
    """Every key, value and reason, on all nineteen populations -- and the
    population distinguishes: every reason and both outcomes occur, and a
    comparison that ran and measured zero is among them."""
    assert {
        name: stored.results for name, (stored, _doc, _api) in population_states.items()
    } == {
        name: document.results
        for name, (_stored, document, _api) in population_states.items()
    }
    outcomes = Counter(
        result.reason or ("zero" if result.value == 0 else "value")
        for stored, _doc, _api in population_states.values()
        for result in stored.results.values()
    )
    assert set(outcomes) == {
        "zero",
        "value",
        NOT_COMPARED_DISABLED,
        NOT_COMPARED_NOT_RUN,
        NOT_COMPARED_UNAVAILABLE,
    }, outcomes


def test_a_run_that_did_not_collect_the_api_surface_states_no_api_comparison(
    population_states: dict[
        str, tuple[ComparisonState, ComparisonState, dict[str, object]]
    ],
) -> None:
    """The producer fix: API not enabled with an API lane in the baseline
    published ``{enabled: false, baseline_diff_available: true,
    breaking: 29}`` (measured 2026-10-05).  The pair is now false beside
    no change; the trusted run with the API lane on keeps its comparison
    (positive control)."""
    stored, _document, api = population_states["api_disabled"]
    assert api["enabled"] is False
    assert api["baseline_diff_available"] is False
    assert api["breaking"] == 0
    assert stored.reason(COMPARISON_API_SURFACE) == NOT_COMPARED_DISABLED
    trusted, _document, trusted_api = population_states["trusted"]
    assert trusted_api["baseline_diff_available"] is True
    assert trusted.made(COMPARISON_API_SURFACE)
    assert (
        trusted.value(COMPARISON_API_SURFACE, "breaking_changes")
        == (trusted_api["breaking"])
    )


# -- the ratchet: nothing reads around the carrier -----------------------------------

#: The metrics diff's comparison terms: a read of one of these, of the
#: availability flag, or of the diff summarizer is a read of a raw
#: comparison count or decision around the normalized state.
_RAW_TERMS = frozenset(
    {
        "health_delta",
        "typing_param_permille_delta",
        "typing_return_permille_delta",
        "docstring_permille_delta",
        "new_api_breaking_changes",
        "new_api_signature_changes",
        "new_api_symbols",
        "new_high_risk_functions",
        "new_high_coupling_classes",
        "new_cycles",
        "new_import_cycles",
        "new_deferred_cycles",
        "new_dead_code",
    }
)
_FLAG = "baseline_diff_available"
_SUMMARIZERS = frozenset({"summarize_metrics_diff", "_summarize_metrics_diff"})

#: The owner: the vocabulary, the carrier and its document reader, the
#: producer, and the comparison that makes the metrics diff in the first
#: place.
_OWNER = frozenset(
    {
        "codeclone/baseline/diff.py",
        "codeclone/canonical/comparison_state.py",
        "codeclone/contracts/comparison_state.py",
        "codeclone/core/comparison_state.py",
    }
)

#: Every module outside the owner that reads around the carrier today, with
#: its count.  Shrink-only: a module that moves onto the carrier leaves the
#: table; no module may enter it, and no count may grow.
_READS_AROUND_THE_CARRIER: dict[str, int] = {
    "codeclone/canonical/comparison_ingest.py": 2,
    "codeclone/canonical/comparison_projection.py": 2,
    "codeclone/canonical/evaluation_projection.py": 3,
    "codeclone/canonical/model.py": 4,
    "codeclone/canonical/registry.py": 1,
    "codeclone/canonical/tier_storage.py": 1,
    "codeclone/core/api_surface_payload.py": 4,
    "codeclone/core/comparison_snapshot.py": 2,
    "codeclone/core/metrics_payload.py": 4,
    "codeclone/core/reporting.py": 1,
    "codeclone/report/document/_common.py": 4,
    "codeclone/report/document/metrics.py": 14,
    "codeclone/report/gates/evaluator.py": 15,
    "codeclone/report/html/sections/_overview.py": 7,
    "codeclone/surfaces/cli/patch_verify.py": 1,
    "codeclone/surfaces/cli/summary.py": 3,
    "codeclone/surfaces/mcp/_session_helpers.py": 1,
}


def _docstrings(tree: ast.AST) -> set[int]:
    return {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _reads(tree: ast.AST) -> int:
    docstrings = _docstrings(tree)
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            count += node.attr in _RAW_TERMS
        elif isinstance(node, ast.Constant) and id(node) not in docstrings:
            count += node.value == _FLAG
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            count += name in _SUMMARIZERS
            count += (
                name == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in _RAW_TERMS
            )
    return count


def test_no_module_reads_a_raw_comparison_count_around_the_carrier() -> None:
    root = Path(__file__).resolve().parents[1]
    observed = {}
    for path in sorted((root / "codeclone").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative in _OWNER:
            continue
        reads = _reads(ast.parse(path.read_text(encoding="utf-8")))
        if reads:
            observed[relative] = reads
    assert observed == _READS_AROUND_THE_CARRIER


def test_the_ratchet_sees_every_kind_of_read() -> None:
    """Positive control: each of the three read shapes is counted, and a
    docstring naming the flag is not."""
    source = (
        '"""baseline_diff_available"""\n'
        "a = diff.health_delta\n"
        'b = summary["baseline_diff_available"]\n'
        "c = summarize_metrics_diff(diff)\n"
        'd = getattr(diff, "new_dead_code", ())\n'
    )
    assert _reads(ast.parse(source)) == 4
