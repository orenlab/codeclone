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
from typing import Any, cast

import pytest

from codeclone.report.html import build_html_report
from codeclone.report.messages.overview import (
    EXECUTIVE_HEALTH_UNMEASURED,
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

COMPLETE_HEALTH: dict[str, object] = {
    "score": 82,
    "grade": "B",
    "dimensions": dict.fromkeys(_DIMENSION_NAMES, 80) | {"coverage": 100},
    "population": "complete",
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


def test_metrics_payload_refuses_a_verdict_when_nothing_was_read(
    tmp_path: Path,
) -> None:
    """The origin of the lie: an unread run scored itself 0/F with six 100s."""

    root = tmp_path / "empty"
    root.mkdir()

    assert _payload_health(root, tmp_path) == UNMEASURED_HEALTH


def test_metrics_payload_keeps_the_verdict_when_files_were_read(
    tmp_path: Path,
) -> None:
    """The reverse skew: a read repository still gets its number."""

    root = tmp_path / "read"
    root.mkdir()
    (root / "mod.py").write_text("def f() -> int:\n    return 1\n", "utf-8")

    health = _payload_health(root, tmp_path)

    assert health["population"] == "complete"
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
    assert summary["population"] == "complete"


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
    assert snapshot["population"] == "complete"
    assert snapshot["strongest_dimension"] == "coverage"


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
    assert "- population: complete" in rendered
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

    assert "health: score=82 grade=B population=complete" in rendered
    assert "Health snapshot:score=82 grade=B population=complete" in rendered


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
    assert 'data-health-population="complete"' in rendered
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
            cache_policy="off",
        )
    )
    summary = service.get_run_summary()
    health = summary["health"]
    assert isinstance(health, dict)
    return health


def test_mcp_run_summary_refuses_the_health_verdict_on_an_unmeasured_run(
    tmp_path: Path,
) -> None:
    root = tmp_path / "empty"
    root.mkdir()

    health = _mcp_health(root)

    assert health["score"] is None
    assert health["grade"] is None
    assert health["population"] == "unmeasured"


def test_mcp_run_summary_keeps_the_health_verdict_on_a_complete_run(
    tmp_path: Path,
) -> None:
    root = tmp_path / "read"
    root.mkdir()
    (root / "mod.py").write_text("def f() -> int:\n    return 1\n", "utf-8")

    health = _mcp_health(root)

    assert isinstance(health["score"], int)
    assert health["grade"] in {"A", "B", "C", "D", "F"}
    assert health["population"] == "complete"


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


def test_a_complete_population_survives_a_zeroed_inventory() -> None:
    """The same rule in the other direction: counters cannot revoke a verdict."""

    document = _document(
        health=COMPLETE_HEALTH,
        inventory={"files": {"total_found": 0, "analyzed": 0}},
    )

    assert _health_summary(document)["population"] == "complete"
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
        == "complete"
    )
    assert _health_snapshot(document)["population"] == "complete"
    assert "population=complete" in render_text_report_document(document)
    assert "- population: complete" in render_markdown_report_document(document)
    assert 'data-health-population="complete"' in build_html_report(
        report_document=document
    )
