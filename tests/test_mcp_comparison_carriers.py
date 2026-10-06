# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Not compared -> null: every MCP answer beside ``get_run_summary`` that
states a comparison, each carrier held on its own.

The maintainer's ruling (2026-10-03, extended 2026-10-05)::

    comparison performed     -> integer, including 0
    comparison not performed -> null

``get_run_summary`` answers its nine comparison fields by the run's
normalized comparison state (``tests/test_run_summary_not_compared_is_null``
holds its table).  Every other MCP answer that states one of those
comparisons states it by the same state, so each one is held here to the
SAME table, cell for cell, on every population of
``tests/_run_summary_serving.py`` -- and each carrier by its own test, so a
carrier that answers around the state is red under its own name, not under a
shared output site:

* the ``analyze_repository`` return and the ``codeclone://runs/{id}/summary``
  resource (the nine fields);
* the MCP ``analysis.completed`` audit row (``diff.new_clones`` and
  ``diff.health_delta``);
* the changed projection: ``analyze_changed_paths`` and the
  ``codeclone://runs/{id}/changed`` resource (``health_delta``);
* ``generate_pr_summary``: the JSON ``health_delta`` and the markdown
  ``Delta:`` words;
* ``create_review_receipt``: ``health.delta``;
* ``get_production_triage``: ``health.delta`` (a positive control: it reads
  the report document's pair, already ``null`` where nothing was compared).

The analyzer-invariant road of patch verification states a run-against-run
health delta, not a comparison against the baseline: the pair is one
content-addressed run, so the delta is ``0`` when the run measured a health
score and ``null`` when it measured none -- the rule ``compare_runs`` states
for any pair.

The populations here are a private set: the analyze, changed and invariant
carriers re-analyse their trees, and the shared set stays untouched for the
modules that read it.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Protocol, cast

import pytest

from codeclone.api.run_store_serving import SERVE_FROM_MEMORY, SERVE_FROM_RUN_STORE
from codeclone.contracts import REPORT_RUN_IDENTITY_TIER
from codeclone.surfaces.mcp import _review_receipt as receipt_module
from codeclone.surfaces.mcp import _session_helpers as helpers
from codeclone.surfaces.mcp._session_shared import (
    ExecutionEvent,
    MCPAnalysisRequest,
    MCPRunRecord,
    build_served_projection,
    mint_execution_event_id,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests._run_summary_serving import (
    SUMMARY_POPULATIONS,
    SummaryPopulation,
    SummaryPopulations,
    serving_environment,
)
from tests.test_run_summary_not_compared_is_null import ABSENT, FIELDS, STATE_TABLE

_Cell = int | str | None

#: The cell of ``diff.health_delta`` and of ``health.delta`` in the table.
_DIFF_HEALTH = FIELDS.index(("diff", "health_delta"))
_HEALTH_DELTA = FIELDS.index(("health", "delta"))
_NEW_CLONES = FIELDS.index(("diff", "new_clones"))


def _cell(container: object, key: str) -> _Cell:
    mapping = container if isinstance(container, Mapping) else {}
    if key not in mapping:
        return ABSENT
    value = mapping[key]
    assert value is None or (isinstance(value, int) and not isinstance(value, bool))
    return cast(_Cell, value)


def _nine(answer: Mapping[str, object]) -> tuple[_Cell, ...]:
    return tuple(_cell(answer.get(block), key) for block, key in FIELDS)


def _delta_words(cell: _Cell) -> str:
    """The ruling's compact words for a delta, spelled here by hand: the
    test does not ask the formatter what the formatter should say."""
    if cell is None:
        return "Delta: n/a (not compared)"
    assert isinstance(cell, int)
    return f"Delta: {cell:+d}" if cell else "Delta: 0"


def _first_python_path(root: Path) -> str:
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if not relative.startswith("."):
            return relative
    return "pkg/__init__.py"


@dataclasses.dataclass(frozen=True, slots=True)
class _Observed:
    """What every carrier stated for one population."""

    analyze_return: tuple[_Cell, ...]
    summary_resource: tuple[_Cell, ...]
    audit_diff: tuple[_Cell, _Cell]
    triage_health_delta: _Cell
    pr_json_health_delta: _Cell
    pr_markdown_delta: str
    receipt_health_delta: _Cell
    changed_answer_health_delta: _Cell
    changed_resource_health_delta: _Cell
    invariant_reason: object
    invariant_health: tuple[object, object]
    invariant_health_delta: _Cell
    invariant_serving: tuple[object, object]


def _delta_line(markdown: object) -> str:
    lines = [line for line in str(markdown).splitlines() if "| Delta: " in line]
    assert len(lines) == 1, markdown
    return lines[0].split(" | ")[1]


def _read_carriers(
    service: CodeCloneMCPService, record: MCPRunRecord
) -> dict[str, object]:
    root = str(record.root)
    short = record.run_id[:8]
    triage = service.get_production_triage(run_id=record.run_id, root=root)
    pr_json = service.generate_pr_summary(
        run_id=record.run_id, root=root, format="json"
    )
    pr_markdown = service.generate_pr_summary(
        run_id=record.run_id, root=root, format="markdown"
    )
    receipt = service.create_review_receipt(
        run_id=record.run_id, root=root, format="json"
    )
    return {
        "summary_resource": _nine(
            json.loads(service.read_resource(f"codeclone://runs/{short}/summary"))
        ),
        "triage_health_delta": _cell(triage.get("health"), "delta"),
        "pr_json_health_delta": _cell(pr_json, "health_delta"),
        "pr_markdown_delta": _delta_line(pr_markdown.get("content")),
        "receipt_health_delta": _cell(receipt.get("health"), "delta"),
    }


class _Event(Protocol):
    event_type: str
    payload: Mapping[str, object]


class _CapturingWriter:
    """An audit writer that keeps every ``analysis.completed`` payload: the
    rows the session's own emit path builds and hands to its writer."""

    def __init__(self) -> None:
        self.payloads: list[Mapping[str, object]] = []

    def emit(self, event: _Event) -> None:
        if event.event_type == "analysis.completed":
            self.payloads.append(event.payload)


def _analysed_with_audit(
    service: CodeCloneMCPService, request: MCPAnalysisRequest
) -> tuple[dict[str, object], list[Mapping[str, object]]]:
    """The real ``analyze_repository`` return, and the ``analysis.completed``
    rows the call wrote."""
    writer = _CapturingWriter()
    patch = pytest.MonkeyPatch()
    try:
        patch.setattr(service, "_audit_writer_for_root", lambda _root: writer)
        answer = service.analyze_repository(request)
    finally:
        patch.undo()
    return answer, writer.payloads


def _invariant_verification(
    population: SummaryPopulation,
) -> dict[str, object]:
    """Declare an edit of ``pyproject.toml`` that analysis does not read,
    make it, re-analyse, and verify: the analyzer-invariant road."""
    service = population.service
    root = population.root
    before = population.record
    started = service.start_controlled_change(
        root=str(root),
        scope={"allowed_files": ["pyproject.toml"]},
        intent="an edit analysis does not read",
    )
    assert started["edit_allowed"] is True, started
    intent_id = str(started["intent_id"])
    pyproject = root / "pyproject.toml"
    text = pyproject.read_text("utf-8") if pyproject.exists() else ""
    pyproject.write_text(text + "\n[tool.mypy]\nstrict = true\n", "utf-8")
    service.analyze_repository(dataclasses.replace(before.request, changed_paths=()))
    after = population.record
    assert after.run_id == before.run_id
    with serving_environment(population.store_path, serve_from=SERVE_FROM_RUN_STORE):
        verified = service.check_patch_contract(
            mode="verify",
            before_run_id=before.run_id,
            after_run_id=after.run_id,
            intent_id=intent_id,
            root=str(root),
            changed_files=["pyproject.toml"],
        )
    service.manage_change_intent(action="clear", intent_id=intent_id)
    return verified


def _observe(population: SummaryPopulation) -> _Observed:
    service = population.service
    with serving_environment(population.store_path, serve_from=SERVE_FROM_MEMORY):
        record = population.record
        read = _read_carriers(service, record)
        answer, audited = _analysed_with_audit(service, record.request)
        assert len(audited) == 1, audited
        audit_diff = cast(Mapping[str, object], audited[0]["diff"])
        changed = service.analyze_changed_paths(
            dataclasses.replace(
                record.request,
                changed_paths=(_first_python_path(population.root),),
            )
        )
        changed_record = population.record
        changed_resource = json.loads(
            service.read_resource(
                f"codeclone://runs/{changed_record.run_id[:8]}/changed"
            )
        )
    verified = _invariant_verification(population)
    delta = cast(Mapping[str, object], verified["structural_delta"])
    serving = cast(Mapping[str, object], verified["serving"])
    return _Observed(
        analyze_return=_nine(answer),
        summary_resource=cast(tuple[_Cell, ...], read["summary_resource"]),
        audit_diff=(
            _cell(audit_diff, "new_clones"),
            _cell(audit_diff, "health_delta"),
        ),
        triage_health_delta=cast(_Cell, read["triage_health_delta"]),
        pr_json_health_delta=cast(_Cell, read["pr_json_health_delta"]),
        pr_markdown_delta=str(read["pr_markdown_delta"]),
        receipt_health_delta=cast(_Cell, read["receipt_health_delta"]),
        changed_answer_health_delta=_cell(changed, "health_delta"),
        changed_resource_health_delta=_cell(changed_resource, "health_delta"),
        invariant_reason=verified.get("reason"),
        invariant_health=(
            cast(Mapping[str, object], verified["before"]).get("health"),
            cast(Mapping[str, object], verified["after"]).get("health"),
        ),
        invariant_health_delta=_cell(delta, "health_delta"),
        invariant_serving=(serving.get("source"), serving.get("reason")),
    )


class _Carriers:
    """Each population observed once, on first use."""

    def __init__(self, populations: SummaryPopulations) -> None:
        self._populations = populations
        self._observed: dict[str, _Observed] = {}

    def __getitem__(self, name: str) -> _Observed:
        if name not in self._observed:
            self._observed[name] = _observe(self._populations[name])
        return self._observed[name]


@pytest.fixture(scope="module")
def carriers(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Carriers]:
    yield _Carriers(
        SummaryPopulations(tmp_path_factory.mktemp("comparison_carriers").resolve())
    )


_NAMES = list(SUMMARY_POPULATIONS)


def test_the_table_is_the_run_summarys_table() -> None:
    assert list(STATE_TABLE) == _NAMES


@pytest.mark.parametrize("name", _NAMES)
def test_the_analyze_repository_return_states_the_run_summarys_cells(
    carriers: _Carriers, name: str
) -> None:
    assert carriers[name].analyze_return == STATE_TABLE[name]


@pytest.mark.parametrize("name", _NAMES)
def test_the_summary_resource_states_the_run_summarys_cells(
    carriers: _Carriers, name: str
) -> None:
    assert carriers[name].summary_resource == STATE_TABLE[name]


@pytest.mark.parametrize("name", _NAMES)
def test_the_analysis_completed_audit_row_states_the_run_summarys_cells(
    carriers: _Carriers, name: str
) -> None:
    cells = STATE_TABLE[name]
    assert carriers[name].audit_diff == (cells[_NEW_CLONES], cells[_DIFF_HEALTH])


@pytest.mark.parametrize("name", _NAMES)
def test_the_changed_projection_states_the_health_comparison_cell(
    carriers: _Carriers, name: str
) -> None:
    observed = carriers[name]
    expected = STATE_TABLE[name][_DIFF_HEALTH]
    assert observed.changed_answer_health_delta == expected, "analyze_changed_paths"
    assert observed.changed_resource_health_delta == expected, "changed resource"


@pytest.mark.parametrize("name", _NAMES)
def test_the_pr_summary_states_the_health_comparison_cell(
    carriers: _Carriers, name: str
) -> None:
    observed = carriers[name]
    expected = STATE_TABLE[name][_DIFF_HEALTH]
    assert observed.pr_json_health_delta == expected, "json"
    assert observed.pr_markdown_delta == _delta_words(expected), "markdown"


@pytest.mark.parametrize("name", _NAMES)
def test_the_review_receipt_states_the_health_comparison_cell(
    carriers: _Carriers, name: str
) -> None:
    assert carriers[name].receipt_health_delta == STATE_TABLE[name][_DIFF_HEALTH]


@pytest.mark.parametrize("name", _NAMES)
def test_the_triage_states_the_documents_health_pair(
    carriers: _Carriers, name: str
) -> None:
    """Positive control: the triage reads the document's pair."""
    assert carriers[name].triage_health_delta == STATE_TABLE[name][_HEALTH_DELTA]


@pytest.mark.parametrize("name", _NAMES)
def test_the_analyzer_invariant_road_states_a_delta_only_between_measured_scores(
    carriers: _Carriers, name: str
) -> None:
    """One content-addressed run on both sides: ``0`` when the run measured
    a health score, ``null`` when it measured none -- and the store's answer
    is the memory's."""
    observed = carriers[name]
    before, after = observed.invariant_health
    assert observed.invariant_reason == "analyzer_invariant"
    assert before == after
    expected = 0 if isinstance(before, int) else None
    assert observed.invariant_health_delta == expected
    assert observed.invariant_serving == ("run_store", "served")


def test_the_carrier_table_distinguishes(carriers: _Carriers) -> None:
    """The accounting (Probe Validity Law): over the populations each
    carrier states both ``null`` and a number, the changed / PR / receipt
    carriers meet a health comparison that ran, and the invariant road
    meets a measured zero and an unmeasured pair."""
    health_column = [STATE_TABLE[name][_DIFF_HEALTH] for name in _NAMES]
    assert None in health_column
    assert any(isinstance(cell, int) for cell in health_column)
    invariant = [carriers[name].invariant_health_delta for name in _NAMES]
    assert 0 in invariant and None in invariant
    analysed = [carriers[name].analyze_return for name in _NAMES]
    for index in range(len(FIELDS)):
        column = [cells[index] for cells in analysed]
        assert None in column and any(isinstance(c, int) for c in column), FIELDS[index]


# -- a measured zero stays 0: the health comparison no population makes ------


def _record_stating_health(root: Path, delta: int | None) -> MCPRunRecord:
    """A record whose document states one health comparison: ``delta`` beside
    ``baseline_diff_available`` true, or ``null`` beside false."""
    run_id = "healthpair" + ("0" * 54)
    document = {
        "integrity": {
            "digests": {
                REPORT_RUN_IDENTITY_TIER: {"algorithm": "sha256", "value": run_id}
            }
        },
        "baseline": {"sorted_lane_trust": [], "disabled_capabilities": []},
        "metrics": {
            "summary": {"health": {"score": 80, "grade": "B", "delta": delta}},
            "families": {
                "health": {
                    "summary": {
                        "baseline_diff_available": delta is not None,
                        "delta": delta,
                    }
                }
            },
        },
    }
    return MCPRunRecord(
        run_id=run_id,
        root=root,
        request=MCPAnalysisRequest(root=str(root), respect_pyproject=False),
        comparison_settings=(),
        served_report=build_served_projection(document),
        summary={
            "run_id": run_id,
            "health": {"score": 80, "grade": "B", "delta": delta},
            "baseline_diff": {"new_clone_groups_total": None},
        },
        changed_paths=(),
        changed_projection=None,
        func_clones_count=0,
        block_clones_count=0,
        reachable_qualnames=frozenset(),
        coverage_join=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
        execution=ExecutionEvent(
            execution_event_id=mint_execution_event_id(),
            root=root,
            semantic_report_id=run_id,
        ),
    )


@pytest.mark.parametrize("delta", [0, 3, -2, None])
def test_a_measured_health_zero_stays_zero_on_every_health_carrier(
    tmp_path: Path, delta: int | None
) -> None:
    """Positive control for the cell no population holds: the health
    comparison ran and measured ``0`` -- and its neighbours, a number either
    way and ``null``."""
    service = CodeCloneMCPService(history_limit=4)
    record = _record_stating_health(tmp_path, delta)
    service._runs.register(record)
    pr_json = service.generate_pr_summary(run_id=record.run_id, format="json")
    pr_markdown = service.generate_pr_summary(run_id=record.run_id, format="markdown")
    receipt = service.create_review_receipt(run_id=record.run_id, format="json")
    changed = service._build_changed_projection(
        dataclasses.replace(record, changed_paths=("pkg/a.py",))
    )
    assert changed is not None
    assert pr_json["health_delta"] == delta
    assert _delta_line(pr_markdown["content"]) == _delta_words(delta)
    assert cast(Mapping[str, object], receipt["health"])["delta"] == delta
    assert changed["health_delta"] == delta


@pytest.mark.parametrize(
    ("value", "words"),
    [(None, "not compared"), (0, "0"), (3, "+3"), (-2, "-2")],
)
def test_the_receipt_says_each_health_delta_in_the_rulings_words(
    value: int | None, words: str
) -> None:
    receipt = {
        "patch_contract": {"status": "accepted", "health_delta": value},
        "structural_delta": {"verdict": "stable", "health_delta": value},
    }
    lines = [
        line
        for line in receipt_module.render_receipt_markdown(receipt).splitlines()
        if line.startswith("**Health delta:**")
    ]
    assert lines == [f"**Health delta:** {words}"] * 2


def test_the_summary_diff_block_is_read_off_the_state_alone() -> None:
    """Without a run record there is no document, so no comparison is
    stated: every field ``null``, never a zero."""
    assert helpers._summary_diff_payload(None) == dict.fromkeys(
        (
            "new_clones",
            "health_delta",
            "typing_param_permille_delta",
            "typing_return_permille_delta",
            "docstring_permille_delta",
            "api_breaking_changes",
            "api_signature_changes",
            "new_api_symbols",
        )
    )
