# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A report must not issue a health verdict about code nobody read.

X-03 gave ``HealthScore`` a population tri-state and taught the CLI and the
gates to refuse an unmeasured run. The report surfaces were left behind: the
JSON document still shipped ``score: 0``, ``grade: "F"`` and six dimensions
at 100 for a run that opened no file, and every renderer downstream repeated
it. ``0`` means "measured, and bad"; it is not "we did not measure".

Every guard here has a sibling in the opposite direction. A fix that painted
``null`` over a repository that *was* read would be the same defect wearing
the other sign, so the complete-population pins fail on that mutation and the
unmeasured pins fail on the original one.

The population is produced exactly once, in ``compute_health``. Surfaces read
that fact; none of them re-derives it from the file counters. The
contradictory-inventory pin below is what keeps a second counter out.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast, get_args

import pytest

from codeclone.contracts import (
    REPORT_SCHEMA_VERSION,
    HealthPopulation,
    population_carries_score,
)
from codeclone.report.html import build_html_report
from codeclone.report.messages.overview import (
    EXECUTIVE_HEALTH_EMPTY_SCOPE,
    EXECUTIVE_HEALTH_UNMEASURED,
    KPI_HEALTH_EMPTY_SCOPE,
    KPI_HEALTH_NA,
    KPI_HEALTH_UNMEASURED,
)
from codeclone.report.renderers.markdown import render_markdown_report_document
from codeclone.report.renderers.sarif import render_sarif_report_document
from codeclone.report.renderers.text import render_text_report_document
from codeclone.surfaces.mcp._review_receipt import render_receipt_markdown
from codeclone.surfaces.mcp._session_helpers import (
    _render_pr_summary_markdown,
    _summary_health_payload,
    _summary_health_score,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest
from codeclone.ui_messages.formatters import fmt_metrics_health
from codeclone.ui_messages.styling import strip_markup
from tests._pipeline_fixtures import analysis_boot, run_pipeline_once
from tests._report_fixtures import build_test_report_document

_DIMENSION_NAMES = (
    "clones",
    "cohesion",
    "complexity",
    "coupling",
    "coverage",
    "dead_code",
    "dependencies",
)

#: The shape the producer must emit when no file was read. ``None`` is the
#: refusal; ``population`` is the reason, and it rides every run, not only
#: this one.
UNMEASURED_HEALTH: dict[str, object] = {
    "score": None,
    "grade": None,
    "dimensions": None,
    "population": "unmeasured",
}

#: The sibling shape: the run worked and the scope holds no source file.
#: Same withheld number, different reason — and the reason is what every
#: surface below has to word differently.
EMPTY_SCOPE_HEALTH: dict[str, object] = {
    "score": None,
    "grade": None,
    "dimensions": None,
    "population": "complete_empty",
}

COMPLETE_HEALTH: dict[str, object] = {
    "score": 82,
    "grade": "B",
    "dimensions": dict.fromkeys(_DIMENSION_NAMES, 80) | {"coverage": 100},
    "population": "complete_nonempty",
}

#: The third absence: the run never computed health at all (a clones-only run
#: brings no health block). Same withheld shape as the two refusals above; the
#: empty population is the fact that keeps this cause apart from both of them.
NEVER_COMPUTED_HEALTH: dict[str, object] = {
    "score": None,
    "grade": None,
    "dimensions": None,
    "population": "",
}


def _mapping_at(payload: Mapping[str, object], *path: str) -> dict[str, object]:
    current: object = payload
    for key in path:
        assert isinstance(current, Mapping), f"{key!r} is not under a mapping"
        current = current[key]
    assert isinstance(current, dict)
    return current


def _document(
    *,
    health: Mapping[str, object],
    inventory: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        metrics={"health": dict(health)},
        inventory=inventory,
    )


def _document_without_health() -> dict[str, object]:
    """A document from a run that never computed metrics — no health block.

    ``--skip-metrics`` hands the builder no metrics payload at all; this is
    that shape, not a health block whose fields are empty.
    """

    return build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        metrics=None,
    )


def _health_summary(document: Mapping[str, object]) -> dict[str, object]:
    return _mapping_at(document, "metrics", "families", "health", "summary")


def _health_snapshot(document: Mapping[str, object]) -> dict[str, object]:
    return _mapping_at(document, "derived", "overview", "health_snapshot")


# ── the producer: one owner for the tri-state ───────────────────────


def _payload_health(root: Path, tmp_path: Path) -> dict[str, object]:
    boot = analysis_boot(root, min_loc=1, min_stmt=1, skip_metrics=False)
    _cache, run = run_pipeline_once(
        boot,
        tmp_path / "cache.json",
        root=root,
        warm=False,
    )
    payload = run.result.metrics_payload
    assert payload is not None, "metrics payload missing; the run skipped metrics"
    health = payload["health"]
    assert isinstance(health, dict)
    return health


def test_metrics_payload_refuses_a_verdict_over_an_empty_scope(
    tmp_path: Path,
) -> None:
    """The origin of the lie: a run over no code scored itself 0/F, six 100s.

    The number is still withheld. What changed is the reason: this root was
    read completely and holds nothing, which is a measurement, not a failure
    to measure. Calling it ``unmeasured`` blamed the run for the repository.
    """

    root = tmp_path / "empty"
    root.mkdir()

    assert _payload_health(root, tmp_path) == EMPTY_SCOPE_HEALTH


def test_metrics_payload_keeps_the_verdict_when_files_were_read(
    tmp_path: Path,
) -> None:
    """The reverse skew: a read repository still gets its number."""

    root = tmp_path / "read"
    root.mkdir()
    (root / "mod.py").write_text("def f() -> int:\n    return 1\n", "utf-8")

    health = _payload_health(root, tmp_path)

    assert health["population"] == "complete_nonempty"
    assert isinstance(health["score"], int)
    assert health["grade"] in {"A", "B", "C", "D", "F"}
    dimensions = health["dimensions"]
    assert isinstance(dimensions, dict)
    assert set(dimensions) == set(_DIMENSION_NAMES)


# ── JSON: the canonical document every other surface reads ──────────


def test_report_document_refuses_the_health_verdict_on_an_unmeasured_run() -> None:
    document = _document(health=UNMEASURED_HEALTH)
    summary = _health_summary(document)

    assert summary["score"] is None
    assert summary["grade"] is None
    assert summary["dimensions"] is None
    assert summary["population"] == "unmeasured"


def test_report_document_keeps_the_health_verdict_on_a_complete_run() -> None:
    document = _document(health=COMPLETE_HEALTH)
    summary = _health_summary(document)

    assert summary["score"] == 82
    assert summary["grade"] == "B"
    assert summary["dimensions"] == COMPLETE_HEALTH["dimensions"]
    assert summary["population"] == "complete_nonempty"


def test_report_document_metrics_summary_mirrors_the_health_family() -> None:
    """One health block, two addresses; they must not disagree."""

    document = _document(health=UNMEASURED_HEALTH)

    assert _mapping_at(document, "metrics", "summary", "health") == _health_summary(
        document
    )


def test_derived_overview_refuses_the_health_verdict_on_an_unmeasured_run() -> None:
    snapshot = _health_snapshot(_document(health=UNMEASURED_HEALTH))

    assert snapshot["score"] is None
    assert snapshot["grade"] is None
    assert snapshot["population"] == "unmeasured"
    assert snapshot["strongest_dimension"] is None
    assert snapshot["weakest_dimension"] is None


def test_derived_overview_keeps_the_health_verdict_on_a_complete_run() -> None:
    snapshot = _health_snapshot(_document(health=COMPLETE_HEALTH))

    assert snapshot["score"] == 82
    assert snapshot["grade"] == "B"
    assert snapshot["population"] == "complete_nonempty"
    assert snapshot["strongest_dimension"] == "coverage"


def test_report_document_withholds_the_verdict_when_health_was_not_computed() -> None:
    """The third absence gets the same honest shape as the two refusals.

    A clones-only run brings no health block, and the family serialized that
    third fact through the historical empty shape: ``_as_int({}.get("score"))``
    published ``score: 0``, ``grade: ""``, ``dimensions: {}`` — a measured-bad
    verdict about a measurement that never ran. The number is withheld exactly
    as for the refusals; the empty population is already the fact that names
    this absence apart from both of them.
    """

    summary = _health_summary(_document_without_health())

    assert summary == {
        **NEVER_COMPUTED_HEALTH,
        "baseline_diff_available": False,
        "delta": 0,
    }


def test_metrics_summary_mirror_withholds_the_never_computed_verdict() -> None:
    """The second address of the same block must not disagree on the third fact."""

    document = _document_without_health()

    assert _mapping_at(document, "metrics", "summary", "health") == _health_summary(
        document
    )


def test_derived_overview_withholds_the_verdict_when_health_was_not_computed() -> None:
    snapshot = _health_snapshot(_document_without_health())

    assert snapshot["score"] is None
    assert snapshot["grade"] is None
    assert snapshot["population"] == ""
    assert snapshot["strongest_dimension"] is None
    assert snapshot["weakest_dimension"] is None


# ── Markdown ────────────────────────────────────────────────────────


def test_markdown_refuses_the_health_verdict_on_an_unmeasured_run() -> None:
    rendered = render_markdown_report_document(_document(health=UNMEASURED_HEALTH))

    health_lines = [
        line
        for line in rendered.splitlines()
        if line.startswith(("- Health:", "- score:", "- grade:", "- population:"))
    ]

    assert "- Health: 0 (F)" not in rendered
    assert "- Health: not measured (no file was read)" in rendered
    assert "- population: unmeasured" in rendered
    assert "- grade: F" not in rendered
    assert not any("None" in line for line in health_lines), health_lines


def test_markdown_keeps_the_health_verdict_on_a_complete_run() -> None:
    rendered = render_markdown_report_document(_document(health=COMPLETE_HEALTH))

    assert "- Health: 82 (B)" in rendered
    assert "- grade: B" in rendered
    assert "- population: complete_nonempty" in rendered
    assert "not measured" not in rendered


# ── Text ────────────────────────────────────────────────────────────


def test_text_refuses_the_health_verdict_on_an_unmeasured_run() -> None:
    rendered = render_text_report_document(_document(health=UNMEASURED_HEALTH))

    assert "health: score=0 grade=F" not in rendered
    assert "health: score=(none) grade=(none) population=unmeasured" in rendered
    assert "Health snapshot:score=(none) grade=(none) population=unmeasured" in rendered
    assert "None" not in rendered


def test_text_keeps_the_health_verdict_on_a_complete_run() -> None:
    rendered = render_text_report_document(_document(health=COMPLETE_HEALTH))

    assert "health: score=82 grade=B population=complete_nonempty" in rendered
    assert "Health snapshot:score=82 grade=B population=complete_nonempty" in rendered


# ── HTML ────────────────────────────────────────────────────────────


def test_html_health_card_refuses_the_verdict_on_an_unmeasured_run() -> None:
    """The ring is a verdict drawn as geometry; there must be no ring."""

    rendered = build_html_report(report_document=_document(health=UNMEASURED_HEALTH))

    assert "Grade F" not in rendered
    assert "Grade None" not in rendered
    assert 'class="health-ring-score"' not in rendered
    assert KPI_HEALTH_UNMEASURED in rendered
    assert 'data-health-population="unmeasured"' in rendered
    assert "data-health-grade=" not in rendered
    assert "data-health-score=" not in rendered


def test_html_executive_answer_names_the_unmeasured_population() -> None:
    """Pinned apart from the card above: two mechanisms, two pins.

    The card and the executive insight are rendered by different code paths.
    A single assertion that matched either one would pass while the other
    quietly went on asserting health, so each owns its own wording.
    """

    rendered = build_html_report(report_document=_document(health=UNMEASURED_HEALTH))

    assert EXECUTIVE_HEALTH_UNMEASURED in rendered


def test_html_keeps_the_health_verdict_on_a_complete_run() -> None:
    rendered = build_html_report(report_document=_document(health=COMPLETE_HEALTH))

    assert "Grade B" in rendered
    assert '<div class="health-ring-score">82</div>' in rendered
    assert 'data-health-population="complete_nonempty"' in rendered
    assert KPI_HEALTH_UNMEASURED not in rendered
    assert EXECUTIVE_HEALTH_UNMEASURED not in rendered


def test_html_still_says_n_a_when_health_was_never_computed() -> None:
    """The two "no number" cards are different facts and stay different.

    A clones-only run brings no health block at all: nothing was refused,
    health simply was not computed. That card keeps saying "n/a", so the
    unmeasured card above cannot be satisfied by the pre-existing path.
    """

    document = build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        metrics={},
    )
    rendered = build_html_report(report_document=document)

    assert KPI_HEALTH_NA in rendered
    assert KPI_HEALTH_UNMEASURED not in rendered


# ── SARIF ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("health", [UNMEASURED_HEALTH, COMPLETE_HEALTH])
def test_sarif_never_carries_a_health_verdict(health: dict[str, object]) -> None:
    """SARIF reports findings, never a score.

    Pinned in both population states so a future health block cannot be added
    to this surface without a population fact beside it.
    """

    rendered = render_sarif_report_document(_document(health=health))
    payload = json.loads(rendered)

    assert "health" not in json.dumps(payload)
    assert "Grade" not in rendered


# ── MCP: get_run_summary and the markdown it feeds ──────────────────


def _mcp_health(root: Path) -> dict[str, object]:
    service = CodeCloneMCPService(history_limit=2)
    service.analyze_repository(
        MCPAnalysisRequest(
            root=str(root),
            respect_pyproject=False,
        )
    )
    summary = service.get_run_summary()
    health = summary["health"]
    assert isinstance(health, dict)
    return health


def test_mcp_run_summary_refuses_the_health_verdict_over_an_empty_scope(
    tmp_path: Path,
) -> None:
    root = tmp_path / "empty"
    root.mkdir()

    health = _mcp_health(root)

    assert health["score"] is None
    assert health["grade"] is None
    assert health["population"] == "complete_empty"


def test_mcp_run_summary_keeps_the_health_verdict_on_a_complete_run(
    tmp_path: Path,
) -> None:
    root = tmp_path / "read"
    root.mkdir()
    (root / "mod.py").write_text("def f() -> int:\n    return 1\n", "utf-8")

    health = _mcp_health(root)

    assert isinstance(health["score"], int)
    assert health["grade"] in {"A", "B", "C", "D", "F"}
    assert health["population"] == "complete_nonempty"


def test_mcp_summary_health_score_is_absent_not_zero_when_unmeasured() -> None:
    """``0`` and "not measured" must not collapse into one integer again."""

    summary = {"health": dict(UNMEASURED_HEALTH)}

    assert _summary_health_payload(summary)["population"] == "unmeasured"
    assert _summary_health_score(summary) is None


def test_mcp_pr_summary_markdown_never_prints_none() -> None:
    """This heading is published into someone else's pull request."""

    rendered = _render_pr_summary_markdown(
        {"health": dict(UNMEASURED_HEALTH), "health_delta": None}
    )
    health_line = next(
        line for line in rendered.splitlines() if line.startswith("Health:")
    )

    assert "None" not in health_line
    assert health_line.startswith("Health: not measured (no file was read) |")


def test_mcp_pr_summary_markdown_keeps_the_score_when_measured() -> None:
    rendered = _render_pr_summary_markdown(
        {"health": dict(COMPLETE_HEALTH), "health_delta": 3}
    )
    health_line = next(
        line for line in rendered.splitlines() if line.startswith("Health:")
    )

    assert health_line.startswith("Health: 82/100 (B) | Delta: +3 |")


def test_mcp_review_receipt_markdown_never_prints_none() -> None:
    """A receipt is evidence; "None/100 (None)" would be evidence of nothing."""

    rendered = render_receipt_markdown(
        {
            "health": dict(UNMEASURED_HEALTH),
            "receipt": {"verdict": "incomplete", "generated_at_utc": ""},
            "provenance": {"run_id": "abcd1234"},
        }
    )
    health_line = next(
        line for line in rendered.splitlines() if line.startswith("**Health:**")
    )

    assert "None" not in health_line
    assert health_line == "**Health:** not measured (no file was read)"


def test_mcp_review_receipt_markdown_keeps_a_measured_score() -> None:
    rendered = render_receipt_markdown(
        {
            "health": dict(COMPLETE_HEALTH),
            "receipt": {"verdict": "clean", "generated_at_utc": ""},
            "provenance": {"run_id": "abcd1234"},
        }
    )
    health_line = next(
        line for line in rendered.splitlines() if line.startswith("**Health:**")
    )

    assert health_line == "**Health:** 82/100 (B)"


# ── the fact has one owner ──────────────────────────────────────────


def test_surfaces_read_the_population_fact_not_the_file_counters() -> None:
    """A renderer that recounts the population instead of reading it reds here.

    The document below is deliberately self-contradictory: the inventory says
    a thousand files were analysed while the health block says the population
    was never measured. ``compute_health`` is the only place allowed to decide
    that question, so every surface must follow the health block and ignore
    the counters beside it.
    """

    document = _document(
        health=UNMEASURED_HEALTH,
        inventory={"files": {"total_found": 1000, "analyzed": 1000}},
    )

    assert _health_summary(document)["population"] == "unmeasured"
    assert _health_summary(document)["score"] is None
    assert "not measured" in render_markdown_report_document(document)
    assert "population=unmeasured" in render_text_report_document(document)
    assert "not measured" in build_html_report(report_document=document)


# ── the two absences never wear each other's words ──────────────────


@pytest.mark.parametrize(
    ("health", "expected", "forbidden"),
    [
        pytest.param(
            EMPTY_SCOPE_HEALTH,
            "no source file in scope",
            "no file was read",
            id="empty-scope",
        ),
        pytest.param(
            UNMEASURED_HEALTH,
            "no file was read",
            "no source file in scope",
            id="unmeasured",
        ),
    ],
)
def test_markdown_words_each_absence_in_its_own_sentence(
    health: dict[str, object],
    expected: str,
    forbidden: str,
) -> None:
    """Both withhold the score; neither may borrow the other's reason.

    Parametrised in both directions on purpose: a renderer that hard-codes
    either sentence passes one row and reds the other, so a mutation cannot
    hide behind a single-state assertion.
    """

    rendered = render_markdown_report_document(_document(health=health))

    assert expected in rendered
    assert forbidden not in rendered
    assert "- Health: 0 (F)" not in rendered
    assert "- Health: 90 (A)" not in rendered


@pytest.mark.parametrize(
    ("health", "expected", "forbidden"),
    [
        pytest.param(
            EMPTY_SCOPE_HEALTH,
            KPI_HEALTH_EMPTY_SCOPE,
            KPI_HEALTH_UNMEASURED,
            id="empty-scope",
        ),
        pytest.param(
            UNMEASURED_HEALTH,
            KPI_HEALTH_UNMEASURED,
            KPI_HEALTH_EMPTY_SCOPE,
            id="unmeasured",
        ),
    ],
)
def test_html_card_names_the_right_absence(
    health: dict[str, object],
    expected: str,
    forbidden: str,
) -> None:
    """The ring is a verdict drawn as geometry; neither absence draws one."""

    rendered = build_html_report(report_document=_document(health=health))

    assert expected in rendered
    assert forbidden not in rendered
    assert 'class="health-ring-score"' not in rendered
    assert "Grade None" not in rendered


@pytest.mark.parametrize(
    ("health", "expected", "forbidden"),
    [
        pytest.param(
            EMPTY_SCOPE_HEALTH,
            EXECUTIVE_HEALTH_EMPTY_SCOPE,
            EXECUTIVE_HEALTH_UNMEASURED,
            id="empty-scope",
        ),
        pytest.param(
            UNMEASURED_HEALTH,
            EXECUTIVE_HEALTH_UNMEASURED,
            EXECUTIVE_HEALTH_EMPTY_SCOPE,
            id="unmeasured",
        ),
    ],
)
def test_html_executive_answer_names_the_right_absence(
    health: dict[str, object],
    expected: str,
    forbidden: str,
) -> None:
    """Pinned apart from the card: two code paths, two pins, still two facts."""

    rendered = build_html_report(report_document=_document(health=health))

    assert expected in rendered
    assert forbidden not in rendered


@pytest.mark.parametrize(
    ("health", "expected", "forbidden"),
    [
        pytest.param(
            EMPTY_SCOPE_HEALTH,
            "no source file in scope",
            "no file was read",
            id="empty-scope",
        ),
        pytest.param(
            UNMEASURED_HEALTH,
            "no file was read",
            "no source file in scope",
            id="unmeasured",
        ),
    ],
)
def test_mcp_receipt_and_pr_summary_name_the_right_absence(
    health: dict[str, object],
    expected: str,
    forbidden: str,
) -> None:
    """Two published surfaces, one rule: evidence names which absence it is.

    A receipt claiming "no file was read" about a repository that simply
    holds no Python is a second, quieter falsehood in the same line, and the
    PR heading goes into somebody else's review.
    """

    receipt = render_receipt_markdown(
        {
            "health": dict(health),
            "receipt": {"verdict": "incomplete", "generated_at_utc": ""},
            "provenance": {"run_id": "abcd1234"},
        }
    )
    pr_summary = _render_pr_summary_markdown(
        {"health": dict(health), "health_delta": None}
    )
    receipt_line = next(
        line for line in receipt.splitlines() if line.startswith("**Health:**")
    )
    pr_line = next(
        line for line in pr_summary.splitlines() if line.startswith("Health:")
    )

    assert expected in receipt_line
    assert forbidden not in receipt_line
    assert expected in pr_line
    assert forbidden not in pr_line
    assert "None" not in receipt_line
    assert "None" not in pr_line


@pytest.mark.parametrize(
    ("population", "expected", "forbidden"),
    [
        pytest.param(
            "complete_empty",
            "no source file in scope",
            "no file was read",
            id="empty-scope",
        ),
        pytest.param(
            "unmeasured",
            "no file was read",
            "no source file in scope",
            id="unmeasured",
        ),
    ],
)
def test_cli_summary_line_names_the_right_absence(
    population: str,
    expected: str,
    forbidden: str,
) -> None:
    """The terminal line every user sees, previously pinned by nothing at all.

    This surface had no test before this wave — not even for the refusal it
    already implemented — so replacing its whole body with a grade would have
    left the suite green. Both states are asserted, and both are asserted to
    print no number.
    """

    rendered = strip_markup(fmt_metrics_health(90, "A", population=population))

    assert expected in rendered
    assert forbidden not in rendered
    assert "90/100" not in rendered
    assert "(A)" not in rendered


def test_cli_summary_line_keeps_the_grade_for_a_measured_population() -> None:
    """The reverse skew: a measured run still gets its number on that line."""

    rendered = strip_markup(fmt_metrics_health(90, "A", population="complete_nonempty"))

    assert "90/100 (A)" in rendered
    assert "not measured" not in rendered


def test_the_document_follows_the_state_when_the_two_signals_disagree() -> None:
    """A number beside "nothing was measured" does not make the number real.

    ``health_report_fields`` never emits this block: it sets the state and the
    score together, so on every honest input the two agree and a reader that
    consulted only the score looked correct. That is what made the state check
    untestable — reverting it left the whole suite green. A corrupted or
    hand-built block is the only input that separates them, and there the
    fail-closed reading is the only honest one.
    """

    document = _document(
        health={
            "score": 82,
            "grade": "B",
            "dimensions": dict.fromkeys(_DIMENSION_NAMES, 80),
            "population": "complete_empty",
        }
    )

    assert _health_summary(document)["score"] is None
    assert _health_summary(document)["grade"] is None
    assert _health_summary(document)["dimensions"] is None
    assert _health_snapshot(document)["score"] is None
    assert "no source file in scope" in render_markdown_report_document(document)


def test_the_document_follows_the_missing_score_when_the_state_says_measured() -> None:
    """The same rule from the other side: a missing number stays missing.

    ``0`` is a measured value. A block whose state claims a full population
    while carrying no score must not have that absence coerced into a zero —
    which is the original lie of this whole wave, arriving through a
    contradiction instead of through a counter.
    """

    document = _document(
        health={
            "score": None,
            "grade": None,
            "dimensions": None,
            "population": "complete_nonempty",
        }
    )

    assert _health_summary(document)["score"] is None
    assert _health_summary(document)["grade"] is None
    assert _health_snapshot(document)["score"] is None
    assert "- Health: 0 (F)" not in render_markdown_report_document(document)


def test_the_population_fact_travels_for_the_empty_scope_too() -> None:
    """An absent key is not an answer; the state ships on every surface."""

    document = _document(health=EMPTY_SCOPE_HEALTH)

    assert _health_summary(document)["population"] == "complete_empty"
    assert _health_snapshot(document)["population"] == "complete_empty"
    assert "population=complete_empty" in render_text_report_document(document)
    assert "- population: complete_empty" in render_markdown_report_document(document)
    assert 'data-health-population="complete_empty"' in build_html_report(
        report_document=document
    )


def test_a_complete_population_survives_a_zeroed_inventory() -> None:
    """The same rule in the other direction: counters cannot revoke a verdict."""

    document = _document(
        health=COMPLETE_HEALTH,
        inventory={"files": {"total_found": 0, "analyzed": 0}},
    )

    assert _health_summary(document)["population"] == "complete_nonempty"
    assert "- Health: 82 (B)" in render_markdown_report_document(document)
    assert "Grade B" in build_html_report(report_document=document)


def test_population_rides_every_surface_even_when_measured() -> None:
    """An absent key is not an answer; the fact ships on complete runs too."""

    document = _document(health=COMPLETE_HEALTH)
    rendered_json = cast(dict[str, Any], json.loads(json.dumps(document)))

    assert (
        _mapping_at(rendered_json, "metrics", "families", "health", "summary")[
            "population"
        ]
        == "complete_nonempty"
    )
    assert _health_snapshot(document)["population"] == "complete_nonempty"
    assert "population=complete_nonempty" in render_text_report_document(document)
    assert "- population: complete_nonempty" in render_markdown_report_document(
        document
    )
    assert 'data-health-population="complete_nonempty"' in build_html_report(
        report_document=document
    )


# ── the enum is wire-visible, so it is bound to the schema version ──


#: The population value set as published under a given report schema version.
#:
#: Not a restatement of the enum: the members below are *compared against* the
#: live ``HealthPopulation``, which the tests read through ``get_args``. What
#: this records is the pairing — that this exact value set went out under this
#: exact schema version. The two must move together, because the value set is
#: wire-visible (the report document, and the HTML data attribute) and a
#: consumer switching on it cannot discover a new member on its own. That is
#: not a hypothetical: `complete` -> `complete_nonempty` plus the new
#: `complete_empty` is what forced 3.0 -> 3.1.
#:
#: Updating one side alone reds. Updating both is a two-line acknowledgement,
#: and the acknowledgement is the point.
_POPULATION_WIRE_CONTRACT: tuple[str, tuple[str, ...]] = (
    "3.2",
    ("complete_empty", "complete_nonempty", "partial", "unmeasured"),
)

#: The sibling pin for ``novelty_reason`` lives in
#: ``tests/test_report_contract_coverage.py``: same pairing, same reasoning, and
#: it has to live there because this module holds no frozen import edge to the
#: classifier that owns that vocabulary, and the architecture boundary ledger is
#: shrink-only.


def _health_block(population: str) -> dict[str, object]:
    """A health block for one population, shaped by the owner of the refusal.

    Which states carry a number is asked of ``population_carries_score``
    rather than listed here; listing it would put a second copy of the rule in
    the test that exists to prove there is only one.
    """

    base = (
        COMPLETE_HEALTH
        if population_carries_score(cast(HealthPopulation, population))
        else UNMEASURED_HEALTH
    )
    return dict(base) | {"population": population}


@pytest.mark.parametrize("population", sorted(get_args(HealthPopulation)))
def test_every_population_member_reaches_the_wire(population: str) -> None:
    """Each state must be observable in the report artifacts, or it is not wire.

    Parametrised over the live type, so a member added later is automatically
    required to show up here. This is what makes the version coupling below
    guard something real: a value set nobody can observe would not need a
    schema version at all, and pinning it would be theatre.
    """

    document = _document(health=_health_block(population))
    rendered_json = cast(dict[str, Any], json.loads(json.dumps(document)))

    assert (
        _mapping_at(rendered_json, "metrics", "families", "health", "summary")[
            "population"
        ]
        == population
    )
    assert f'data-health-population="{population}"' in build_html_report(
        report_document=document
    )


def test_the_population_value_set_cannot_move_without_the_schema_version() -> None:
    """The value set and the schema version are one fact; they move together.

    Deliberately not ``assert REPORT_SCHEMA_VERSION == "3.1"`` — that would
    move the magic number into the test and assert nothing about *why* the
    version has that value. The rule asserted here is the pairing, with the
    members re-read from the live type rather than retyped, so:

    * adding, removing or renaming a member without bumping the version reds;
    * bumping the version without touching the members also reds, which is
      intended. A schema bump for any other reason is exactly the moment to
      confirm that this wire-visible enum is still what the ledger says, and
      the confirmation costs one line.
    """

    live = (REPORT_SCHEMA_VERSION, tuple(sorted(get_args(HealthPopulation))))

    assert live == _POPULATION_WIRE_CONTRACT, (
        "The report health population value set and REPORT_SCHEMA_VERSION are "
        "one wire contract. If the members changed, bump "
        "REPORT_SCHEMA_VERSION and record the new pair here. If the version "
        "changed for another reason, record the unchanged members against the "
        f"new version. Live: {live}. Recorded: {_POPULATION_WIRE_CONTRACT}."
    )
