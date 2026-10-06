# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Every human surface of a comparison delta reads the normalized state and
spells it with one formatter (ruling 2026-10-03): a comparison that ran
prints its number -- a measured zero stays ``0`` -- and one that did not
prints the words, never ``+0``, ``0 breaking`` or nothing."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from codeclone.report.html.sections._overview import (
    _adoption_card_html,
    _api_card_html,
    _health_gauge_html,
)
from codeclone.report.messages.comparison import (
    NOT_COMPARED,
    NOT_COMPARED_COMPACT,
    comparison_text,
    comparison_text_compact,
)
from codeclone.report.messages.overview import HEALTH_DELTA_SUFFIX, KPI_NOTHING_NEW
from tests.conftest import (
    _comparison_baseline,
    _rewrite_scope_as_foreign,
    _run_codeclone_cli_exit,
    materialize_comparison_corpus,
)
from tests.test_html_report import _metrics_payload, _render_metrics_html

# -- the one formatter ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "signed", "text", "compact"),
    [
        (None, False, "not compared", "n/a (not compared)"),
        (None, True, "not compared", "n/a (not compared)"),
        (0, False, "0", "0"),
        (0, True, "0", "0"),
        (3, False, "3", "3"),
        (3, True, "+3", "+3"),
        (-2, True, "-2", "-2"),
        (-2, False, "-2", "-2"),
    ],
)
def test_a_delta_is_its_number_or_the_rulings_words(
    *, value: int | None, signed: bool, text: str, compact: str
) -> None:
    """The ruling's words, spelled literally here so the owner's constants
    cannot drift from them; a measured zero is ``0``, never ``+0``."""
    assert comparison_text(value, signed=signed) == text
    assert comparison_text_compact(value, signed=signed) == compact
    assert (NOT_COMPARED, NOT_COMPARED_COMPACT) == (
        "not compared",
        "n/a (not compared)",
    )


# -- the CLI summary --------------------------------------------------------------


@pytest.fixture(scope="module")
def cli_corpus(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Path]]:
    """The comparison corpus twice, against one stage-A baseline: as compared
    (positive control) and with the scope rewritten as foreign -- the run
    whose API comparison context still says "available" while the state
    says the API lane is untrusted, so not compared."""
    base = tmp_path_factory.mktemp("human_text_corpus").resolve()
    baseline = _comparison_baseline(base)
    trees = {"baseline": baseline}
    for name in ("compared", "foreign_scope"):
        root = base / name
        materialize_comparison_corpus(root, stage_b=True)
        if name == "foreign_scope":
            _rewrite_scope_as_foreign(root)
        trees[name] = root
    yield trees


def _cli_output(
    cli_corpus: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    *,
    name: str,
    quiet: bool,
) -> str:
    """One in-process CLI run of a corpus tree, its stdout with whitespace
    collapsed (rich wraps at the console width)."""
    args = [
        str(cli_corpus[name]),
        "--no-progress",
        "--api-surface",
        "--baseline",
        str(cli_corpus["baseline"]),
        *(["--quiet"] if quiet else []),
    ]
    capsys.readouterr()
    code = _run_codeclone_cli_exit(args, {"CODECLONE_RUN_STORE_ENABLED": "0"})
    assert code in (None, 0), code
    return re.sub(r"\s+", " ", capsys.readouterr().out)


#: The corpus's measured public surface, the half of the line that is a fact
#: of the current run whatever the comparison did.
_SURFACE_RICH = "Public API 64 symbols · 25 modules ·"
_SURFACE_COMPACT = "Public API symbols=64 modules=25"
#: The run-outcome tip naming an API comparison that did not run.
_API_TIP = "Public API not compared:"


def test_the_cli_summary_states_no_api_comparison_the_document_disowns(
    cli_corpus: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Measured 2026-10-06: against the container of another scope the
    report document says the API comparison did not run (``false`` beside
    ``null``) while the CLI summary printed ``2 breaking / 1 changed / 37
    added`` -- the API comparison context's own flag, read around the
    state.  The rich line, the compact line and the run-outcome tip now read
    the state, and say the words."""
    rich = _cli_output(cli_corpus, capsys, name="foreign_scope", quiet=False)
    assert f"{_SURFACE_RICH} breaking changes: {NOT_COMPARED}" in rich, rich
    assert "breaking /" not in rich, rich
    assert _API_TIP in rich, rich
    compact = _cli_output(cli_corpus, capsys, name="foreign_scope", quiet=True)
    assert f"{_SURFACE_COMPACT} diff={NOT_COMPARED_COMPACT}" in compact, compact
    assert "breaking=" not in compact, compact


def test_the_cli_summary_prints_the_numbers_of_a_comparison_that_ran(
    cli_corpus: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Positive control: the same corpus against its own scope compared the
    API, and every line prints the counts, never the words."""
    rich = _cli_output(cli_corpus, capsys, name="compared", quiet=False)
    assert f"{_SURFACE_RICH} 2 breaking / 1 changed / 37 added" in rich, rich
    assert NOT_COMPARED not in rich and _API_TIP not in rich, rich
    compact = _cli_output(cli_corpus, capsys, name="compared", quiet=True)
    assert f"{_SURFACE_COMPACT} breaking=2 changed=1 added=37" in compact, compact
    assert NOT_COMPARED not in compact, compact


# -- the HTML overview --------------------------------------------------------------

_ADOPTION_BASE: dict[str, object] = {
    "param_permille": 900,
    "return_permille": 800,
    "docstring_permille": 500,
    "typing_any_count": 0,
}


def test_the_html_adoption_card_says_not_compared_beside_null() -> None:
    html = _adoption_card_html(
        {
            **_ADOPTION_BASE,
            "baseline_diff_available": False,
            "param_delta": None,
            "return_delta": None,
            "docstring_delta": None,
        }
    )
    assert html.count(NOT_COMPARED) == 3, html
    assert "pt</span>" not in html, html


def test_the_html_adoption_card_keeps_a_measured_zero() -> None:
    html = _adoption_card_html(
        {
            **_ADOPTION_BASE,
            "baseline_diff_available": True,
            "param_delta": 0,
            "return_delta": 12,
            "docstring_delta": -5,
        }
    )
    assert NOT_COMPARED not in html, html
    assert "0.0pt" in html and "+1.2pt" in html and "-0.5pt" in html, html


_API_BASE: dict[str, object] = {"enabled": True, "modules": 2, "public_symbols": 5}


def test_the_html_api_card_says_not_compared_beside_null() -> None:
    html = _api_card_html(
        {
            **_API_BASE,
            "baseline_diff_available": False,
            "breaking": None,
            "changed": None,
            "added": None,
        }
    )
    assert html.count(NOT_COMPARED) == 3, html
    assert ">0<" not in html, html


def test_the_html_api_card_keeps_a_measured_zero() -> None:
    html = _api_card_html(
        {
            **_API_BASE,
            "baseline_diff_available": True,
            "breaking": 0,
            "changed": 0,
            "added": 4,
        }
    )
    assert NOT_COMPARED not in html, html
    assert html.count(">0<") == 2 and ">4<" in html, html


def test_the_html_health_ring_says_not_compared_without_a_delta() -> None:
    assert NOT_COMPARED in _health_gauge_html(80.0, "B", health_delta=None)
    measured_zero = _health_gauge_html(80.0, "B", health_delta=0)
    assert NOT_COMPARED not in measured_zero
    assert "+3" in _health_gauge_html(80.0, "B", health_delta=3)


# -- the HTML overview, end to end ----------------------------------------------------


def _overview_html(*, health: dict[str, object], complexity: dict[str, object]) -> str:
    """The whole report page over a metrics payload whose health and
    complexity comparisons carry the given pair: the document builder writes
    the pair, the overview reads it back."""
    payload = _metrics_payload(
        health_score=80,
        health_grade="B",
        complexity_max=30,
        complexity_high_risk=2,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=2,
        dead_total=0,
        dead_critical=0,
    )
    families = cast("dict[str, dict[str, object]]", payload)
    families["health"] = {**families["health"], "summary": health}
    complexity_family = families["complexity"]
    complexity_family["summary"] = {
        **cast("dict[str, object]", complexity_family.get("summary", {})),
        **complexity,
    }
    return _render_metrics_html(payload)


_RING_NOT_COMPARED = f'<div class="health-ring-delta">{NOT_COMPARED}</div>'


def test_the_html_overview_reads_each_pair_off_the_document() -> None:
    """The ring and the KPI cards read the document's pair through the
    owner's reader: not compared prints the words on the ring and no
    "nothing new" tick on a card; a measured zero prints no words and earns
    the tick; a measured delta prints itself."""
    not_compared = _overview_html(
        health={"baseline_diff_available": False, "delta": None},
        complexity={"baseline_diff_available": False, "new_high_risk": None},
    )
    measured_zero = _overview_html(
        health={"baseline_diff_available": True, "delta": 0},
        complexity={"baseline_diff_available": True, "new_high_risk": 0},
    )
    measured = _overview_html(
        health={"baseline_diff_available": True, "delta": 3},
        complexity={"baseline_diff_available": True, "new_high_risk": 0},
    )
    assert _RING_NOT_COMPARED in not_compared
    assert _RING_NOT_COMPARED not in measured_zero
    assert HEALTH_DELTA_SUFFIX not in measured_zero
    assert f"+3{HEALTH_DELTA_SUFFIX}" in measured
    assert measured_zero.count(KPI_NOTHING_NEW) == (
        not_compared.count(KPI_NOTHING_NEW) + 1
    )
