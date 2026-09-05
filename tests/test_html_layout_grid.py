# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Layout pins for the HTML report grid.

What a table cell is allowed to do to its row, which numbers the first screen
says once, and what an empty state may spend its words on. Every pin here was
shown red under a targeted mutation of the behaviour it holds (receipt
2026-09-05, ``_lab/html-polish``); a pin that cannot be turned red by breaking
its subject is not a pin.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from codeclone.report.html.assets.css import build_css
from codeclone.report.html.sections._dead_code import (
    _held_by_tests_html,
    render_dead_code_panel,
)
from codeclone.report.html.sections._overview import (
    _baseline_verdict,
    _health_gauge_html,
    render_overview_panel,
)
from codeclone.report.html.widgets.tables import (
    _breakable_path_html,
    _identity_cell_html,
    render_rows_table,
)
from codeclone.report.messages.glossary import GLOSSARY_FAMILY_DEAD_CODE
from codeclone.report.messages.overview import (
    BASELINE_ACTION_ACCEPT,
    BASELINE_ACTION_BLOCK,
    BASELINE_ACTION_CREATE,
    BASELINE_NOTHING_NEW,
    EXECUTIVE_METRICS_SKIPPED,
)

_HELD = (
    "tests.test_cache:test_type_guards",
    "tests.test_cache:test_predicates",
    "tests.test_core:test_helpers",
)


def _ctx(**overrides: object) -> Any:
    """The slice of a report context the overview and dead-code panels read."""

    base: dict[str, object] = {
        "clone_groups_total": 4,
        "clone_summary": {"new": 0, "known": 4, "unavailable": 0},
        "complexity_map": {"summary": {"high_risk": 5, "average": 2.5, "max": 9}},
        "coupling_map": {"summary": {"high_risk": 3, "average": 1.5, "max": 7}},
        "cohesion_map": {"summary": {"low_cohesion": 2, "average": 1.2, "max": 5}},
        "dead_code_map": {
            "summary": {
                "total": 30,
                "high_confidence": 30,
                "suppressed": 2,
                "unresolved_external_override": 14,
                "unresolved": 81,
                "world_contract": "open",
                "unreachable_statements": 0,
            },
            "items": [
                {
                    "qualname": "pkg.mod:held",
                    "relative_path": "pkg/mod.py",
                    "start_line": 5,
                    "kind": "function",
                    "confidence": "high",
                    "reason": "test_only_reference",
                    "test_reference_sources": list(_HELD),
                }
            ],
            "suppressed_items": [],
        },
        "dependencies_map": {"cycles": [], "max_depth": 4},
        "health_map": {"score": 82, "grade": "B", "dimensions": {}},
        "metrics_available": True,
        "structural_findings": (),
        "suggestions": (),
        "func_sorted": (("clone:a", ({}, {})),),
        "block_sorted": (),
        "segment_sorted": (),
        "overview_data": {},
        "baseline_status": "trusted",
        "meta": {},
        "report_document": {},
        "relative_path": lambda filepath: filepath,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _banner_answer(html: str, question: str) -> str:
    match = re.search(
        re.escape(question) + r'</div><div class="insight-answer">(.*?)</div>', html
    )
    assert match is not None, html[:400]
    return match.group(1)


def _card(html: str, label: str) -> str:
    """One stat card's markup, from its label to the next card."""

    start = html.index(f'<div class="meta-label">{label}')
    end = html.find('<div class="meta-item">', start + 1)
    return html[start:] if end == -1 else html[start:end]


# ---------------------------------------------------------------------------
# The dead-code table: a row is as tall as its test modules, not its test ids
# ---------------------------------------------------------------------------


def test_held_by_tests_groups_by_module_and_keeps_every_id() -> None:
    html = _held_by_tests_html(_HELD)
    assert html.count('class="held-test"') == 2, html
    assert "&times;2" in html
    for source in _HELD:
        assert f"<code>{source}</code>" in html, source
    assert _held_by_tests_html([]) == ""


def test_held_by_tests_chip_carries_no_count_for_one_test() -> None:
    html = _held_by_tests_html(("tests.test_core:test_one",))
    assert "held-test-count" not in html
    assert "tests.test_core" in html


def test_dead_code_row_draws_its_chips_and_names_its_reason() -> None:
    panel = render_dead_code_panel(_ctx())
    assert panel.count('class="held-test"') == 2
    assert "test-only reference" in panel
    assert "test_only_reference" not in panel


def test_identity_cell_draws_the_symbol_over_its_module() -> None:
    assert _identity_cell_html("pkg.mod:Class.method") == (
        '<span class="ident-symbol">Class.method</span>'
        '<span class="ident-module">pkg.mod</span>'
    )
    assert _identity_cell_html("plain_name") == "plain_name"
    assert _identity_cell_html(":only") == ":only"


def test_identity_column_keeps_the_full_name_on_the_cell_and_never_elides() -> None:
    html = render_rows_table(
        headers=("Name", "Line"),
        rows=[("pkg.mod:symbol", "1")],
        empty_message="none",
        family=GLOSSARY_FAMILY_DEAD_CODE,
    )
    assert '<td class="col-name" title="pkg.mod:symbol">' in html
    name_rule = re.search(r"\.table \.col-name\{([^}]*)\}", build_css())
    assert name_rule is not None
    assert "ellipsis" not in name_rule.group(1)
    assert "nowrap" not in name_rule.group(1)


def test_path_cells_break_at_separators_only() -> None:
    assert _breakable_path_html("pkg/sub/mod.py") == "pkg/<wbr>sub/<wbr>mod.py"
    path_rule = re.search(
        r"\.table \.col-file,\.table \.col-path\{([^}]*)\}", build_css()
    )
    assert path_rule is not None
    assert "nowrap" not in path_rule.group(1)
    assert "ellipsis" not in path_rule.group(1)


# ---------------------------------------------------------------------------
# One visual language for a count beside a label
# ---------------------------------------------------------------------------


def _declarations(selector: str) -> dict[str, str]:
    # The bare rule, at the start of its line: a scoped override such as
    # ``.overview-kpi-cards .kpi-micro`` is a different rule.
    match = re.search(r"(?m)^" + re.escape(selector) + r"\{([^}]*)\}", build_css())
    assert match is not None, selector
    return {
        key.strip(): value.strip()
        for part in match.group(1).replace("\n", "").split(";")
        if ":" in part
        for key, value in (part.split(":", 1),)
    }


def test_count_captions_share_the_tab_pill_box() -> None:
    pill = _declarations(".tab-count")
    caption = _declarations(".kpi-micro")
    for token in ("height", "border-radius", "background", "font-family"):
        assert caption.get(token) == pill.get(token), (token, caption, pill)
    # The overview used to size the caption down on its own cards.
    assert ".overview-kpi-cards .kpi-micro{padding" not in build_css()


# ---------------------------------------------------------------------------
# The first screen says each number once
# ---------------------------------------------------------------------------


def test_dead_code_banner_answers_without_restating_the_cards() -> None:
    panel = render_dead_code_panel(_ctx())
    answer = _banner_answer(panel, "Do we have actionable unused code?")
    assert answer.startswith("Yes: 30 high-confidence candidates.")
    assert "Abstentions are counted on the cards" in answer
    for restated in ("81", "14", "suppressed", "candidates total"):
        assert restated not in answer, (restated, answer)
    assert "Hit rate" not in panel
    for caption in ("active", "abstained", "of total"):
        assert f'kpi-micro-lbl">{caption}<' not in panel, caption


def test_the_largest_dead_code_number_has_a_card() -> None:
    panel = render_dead_code_panel(_ctx())
    card = _card(panel, "Unresolved external reach")
    assert '<div class="meta-value meta-value--muted">81</div>' in card
    assert "open world contract" in card


def test_dead_code_banner_states_the_absence_when_nothing_is_dead() -> None:
    ctx = _ctx(
        dead_code_map={
            "summary": {"total": 0, "high_confidence": 0, "suppressed": 3},
            "items": [],
            "suppressed_items": [],
        }
    )
    answer = _banner_answer(
        render_dead_code_panel(ctx), "Do we have actionable unused code?"
    )
    assert answer == "No dead-code candidates."


def test_overview_banner_is_the_baseline_verdict() -> None:
    nothing = _baseline_verdict(
        baseline_status="trusted",
        new_by_family={"clones": 0, "complexity": 0},
        clones_not_compared=0,
        metrics_available=True,
    )
    assert nothing == (BASELINE_NOTHING_NEW, (), "ok")

    new = _baseline_verdict(
        baseline_status="trusted",
        new_by_family={"clones": 1, "complexity": 2, "coupling": None},
        clones_not_compared=0,
        metrics_available=True,
    )
    assert new[0] == (
        "New since the baseline: 1 clone group, 2 high-complexity functions."
    )
    assert new[1] == (BASELINE_ACTION_BLOCK, BASELINE_ACTION_ACCEPT)
    assert new[2] == "warn"

    missing = _baseline_verdict(
        baseline_status="missing",
        new_by_family={"clones": 0},
        clones_not_compared=0,
        metrics_available=True,
    )
    assert missing[0].startswith("Not compared: no baseline yet.")
    assert missing[1] == (BASELINE_ACTION_CREATE,)
    assert missing[2] == "info"

    untrusted = _baseline_verdict(
        baseline_status="untrusted",
        new_by_family={},
        clones_not_compared=0,
        metrics_available=True,
    )
    assert untrusted[0].startswith("Not compared: baseline untrusted.")

    skipped = _baseline_verdict(
        baseline_status="trusted",
        new_by_family={"clones": 0},
        clones_not_compared=0,
        metrics_available=False,
    )
    assert skipped[0] == f"{BASELINE_NOTHING_NEW} {EXECUTIVE_METRICS_SKIPPED}"


def test_overview_banner_does_not_restate_the_ring_or_the_cards() -> None:
    panel = render_overview_panel(_ctx())
    answer = _banner_answer(panel, "What changed since the baseline?")
    assert answer == BASELINE_NOTHING_NEW
    assert "82" not in answer
    assert "clone groups" not in answer


def test_clone_card_claims_nothing_new_only_when_every_group_was_compared() -> None:
    compared = _card(render_overview_panel(_ctx()), "Clone Groups")
    assert 'kpi-micro-lbl">nothing new<' in compared

    no_baseline = _card(
        render_overview_panel(_ctx(baseline_status="missing")), "Clone Groups"
    )
    assert "nothing new" not in no_baseline
    assert "kpi-delta" not in no_baseline

    partly = _card(
        render_overview_panel(
            _ctx(clone_summary={"new": 0, "known": 3, "unavailable": 1})
        ),
        "Clone Groups",
    )
    assert "nothing new" not in partly
    assert '>1</span><span class="kpi-micro-lbl">not compared<' in partly

    fresh = _card(
        render_overview_panel(
            _ctx(clone_summary={"new": 1, "known": 3, "unavailable": 0})
        ),
        "Clone Groups",
    )
    assert 'kpi-delta--bad">+1 new</span>' in fresh
    assert 'kpi-micro-lbl">new<' not in fresh


def test_scan_scope_counts_agree_with_their_nouns() -> None:
    panel = render_overview_panel(
        _ctx(
            inventory_map={
                "files": {"total_found": 1},
                "code": {"parsed_lines": 1, "functions": 1, "methods": 0, "classes": 1},
            }
        )
    )
    # The noun is pinned by its boundary: "1 class" is a prefix of "1 classes",
    # so the positive match alone let a plural mutant survive (battery
    # 2026-09-05); the negatives are what make the pin bite.
    assert "1 file · 1 line · 1 callable · 1 class<" in panel
    for wrong in ("1 files", "1 lines", "1 callables", "1 classes"):
        assert wrong not in panel, wrong
    assert "Thresholds:" not in panel


def test_hotspot_counts_agree_with_their_nouns() -> None:
    panel = render_overview_panel(
        _ctx(
            overview_data={
                "directory_hotspots": {
                    "all": {
                        "items": [
                            {
                                "path": "pkg",
                                "share_pct": 100.0,
                                "finding_groups": 1,
                                "affected_items": 1,
                                "files": 1,
                            }
                        ]
                    }
                }
            }
        )
    )
    assert "<span>1 group</span>" in panel
    assert "<span>1 item</span>" in panel
    assert "<span>1 file</span>" in panel
    assert "1 groups" not in panel


def test_structural_findings_card_names_its_population() -> None:
    panel = render_overview_panel(_ctx())
    assert '<div class="meta-label">Structural findings' in panel
    assert '<div class="meta-label">Findings<' not in panel


def test_health_ring_delta_names_its_reference() -> None:
    population = "complete_nonempty"
    gauge = _health_gauge_html(74.0, "C", health_delta=3, population=population)
    assert "+3 since baseline</div>" in gauge
    down = _health_gauge_html(74.0, "C", health_delta=-2, population=population)
    assert "-2 since baseline</div>" in down


def test_a_tier_that_did_not_run_says_so_in_one_row() -> None:
    document = {
        "findings": {
            "groups": {
                "near_miss": {"state": "disabled", "algorithm_revision": "3"},
                "renamed_structure": {"state": "complete", "count": 2},
            }
        }
    }
    panel = render_overview_panel(_ctx(report_document=document))
    rows = re.findall(
        r'<div class="overview-fact-row overview-tier-row"(.*?)</div>', panel
    )
    assert len(rows) == 2, panel
    near_miss, renamed = rows
    assert "not run" in near_miss and "<code>--near-miss</code>" in near_miss
    assert "algorithm" not in near_miss
    assert "2 measured" in renamed and "--renamed-structure" not in renamed
    for row in rows:
        words = re.sub(r"<[^>]+>", " ", row).split()
        assert len(words) <= 25, words


def test_tier_rows_stay_within_the_word_budget() -> None:
    document = {
        "findings": {
            "groups": {
                "near_miss": {"state": "disabled", "algorithm_revision": "3"},
                "renamed_structure": {"state": "disabled", "algorithm_revision": "1"},
            }
        }
    }
    panel = render_overview_panel(_ctx(report_document=document))
    cluster = panel[panel.index("Advisory detection tiers") :]
    cluster = cluster[: cluster.index("</section>")]
    text = " ".join(re.sub(r"<[^>]+>", " ", cluster).split())
    assert len(text.split()) <= 40, text


def test_overview_banner_offers_the_commands_the_cli_offers() -> None:
    first_run = render_overview_panel(_ctx(baseline_status="missing"))
    assert "<code>codeclone . --update-baseline</code>" in first_run
    assert "--fail-on-new" not in first_run

    fresh = render_overview_panel(
        _ctx(clone_summary={"new": 1, "known": 3, "unavailable": 0})
    )
    assert "<code>codeclone . --fail-on-new</code>" in fresh
    assert "<code>codeclone . --update-baseline</code>" in fresh

    clean = render_overview_panel(_ctx())
    assert "insight-actions" not in clean


def test_provenance_pill_says_what_is_verified() -> None:
    from codeclone.report.html.sections._meta import build_topbar_provenance_summary

    verified: Any = SimpleNamespace(
        meta={},
        baseline_meta={"loaded": True, "payload_sha256_verified": True},
        cache_meta={},
    )
    label, colour, _tooltip = build_topbar_provenance_summary(verified)
    assert (label, colour) == ("Baseline verified", "green")
    missing: Any = SimpleNamespace(
        meta={}, baseline_meta={"loaded": False}, cache_meta={}
    )
    assert build_topbar_provenance_summary(missing)[0] == "No baseline"
