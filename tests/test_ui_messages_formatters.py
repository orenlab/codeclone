# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import inspect
import string

import pytest

from codeclone.ui_messages import formatters, labels, styling


def test_fmt_summary_compact_coverage_join_ok_with_scope_gaps() -> None:
    text = formatters.fmt_summary_compact_coverage_join(
        status="ok",
        overall_permille=950,
        coverage_hotspots=2,
        scope_gap_hotspots=3,
        threshold_percent=80,
        source_label="cobertura.xml",
    )
    assert "status=ok" in text
    assert "scope_gaps=3" in text
    assert "source=cobertura.xml" in text


def test_fmt_metrics_coverage_join_ok_with_scope_gaps() -> None:
    text = formatters.fmt_metrics_coverage_join(
        status="ok",
        overall_permille=920,
        coverage_hotspots=1,
        scope_gap_hotspots=2,
        threshold_percent=75,
        source_label="external",
    )
    assert "scope gaps" in text
    assert "external" in text


def test_fmt_metrics_coverage_join_unavailable_with_source() -> None:
    text = formatters.fmt_metrics_coverage_join(
        status="missing",
        overall_permille=0,
        coverage_hotspots=0,
        scope_gap_hotspots=0,
        threshold_percent=80,
        source_label="none",
    )
    # Ownership pin: the expectation is read from the named owner, so the
    # compact line cannot drift apart from its vocabulary.
    assert formatters._COVERAGE_JOIN_ABSENCE in text
    assert "none" in text


def test_fmt_metrics_coverage_join_unavailable_without_source() -> None:
    text = formatters.fmt_metrics_coverage_join(
        status="missing",
        overall_permille=0,
        coverage_hotspots=0,
        scope_gap_hotspots=0,
        threshold_percent=80,
        source_label="",
    )
    assert formatters._COVERAGE_JOIN_ABSENCE in text
    assert " · " not in text.split(formatters._COVERAGE_JOIN_ABSENCE, 1)[-1]


def test_fmt_summary_parsed_returns_none_when_all_zero() -> None:
    assert (
        formatters.fmt_summary_parsed(
            lines=0,
            functions=0,
            methods=0,
            classes=0,
        )
        is None
    )


def test_fmt_summary_parsed_includes_callables_and_classes() -> None:
    text = formatters.fmt_summary_parsed(
        lines=100,
        functions=3,
        methods=2,
        classes=1,
    )
    assert text is not None
    assert "5 callables" in text
    assert "1 class" in text
    assert "1 classes" not in text


def test_fmt_summary_compact_coverage_non_ok_status() -> None:
    text = formatters.fmt_summary_compact_coverage_join(
        status="missing",
        overall_permille=0,
        coverage_hotspots=0,
        scope_gap_hotspots=0,
        threshold_percent=80,
        source_label="",
    )
    assert "status=missing" in text
    assert "overall=" not in text


def test_fmt_summary_compact_coverage_ok_without_scope_gaps() -> None:
    text = formatters.fmt_summary_compact_coverage_join(
        status="ok",
        overall_permille=990,
        coverage_hotspots=0,
        scope_gap_hotspots=0,
        threshold_percent=80,
        source_label="",
    )
    assert "scope_gaps" not in text


def test_fmt_summary_parsed_classes_only_without_callables() -> None:
    text = formatters.fmt_summary_parsed(
        lines=10,
        functions=0,
        methods=0,
        classes=2,
    )
    assert text is not None
    assert "classes" in text
    assert "callables" not in text


def test_fmt_metrics_api_surface_includes_breaking_and_added() -> None:
    text = formatters.fmt_metrics_api_surface(
        public_symbols=5,
        modules=2,
        added=3,
        breaking=1,
        diff_available=True,
    )
    assert "breaking" in text
    assert "added" in text


def test_fmt_metrics_api_surface_without_delta() -> None:
    text = formatters.fmt_metrics_api_surface(
        public_symbols=10,
        modules=3,
        added=0,
        breaking=0,
        diff_available=True,
    )
    assert "breaking" not in text


def test_fmt_summary_compact_api_surface_omits_diff_terms_when_withheld() -> None:
    """No surface prints the numbers of a comparison that never ran."""

    text = formatters.fmt_summary_compact_api_surface(
        public_symbols=3,
        modules=2,
        added=0,
        breaking=0,
        diff_available=False,
    )
    assert text == "Public API  symbols=3  modules=2"


def test_fmt_summary_compact_api_surface_keeps_diff_terms_when_available() -> None:
    """The opposite boundary: a comparison that ran keeps its terms verbatim."""

    text = formatters.fmt_summary_compact_api_surface(
        public_symbols=3,
        modules=2,
        added=4,
        breaking=1,
        diff_available=True,
    )
    assert text == "Public API  symbols=3  modules=2  breaking=1  added=4"


def test_fmt_metrics_api_surface_pronounces_a_withheld_comparison() -> None:
    """The rich line carries the absence in words, never the zeros."""

    text = formatters.fmt_metrics_api_surface(
        public_symbols=10,
        modules=3,
        added=0,
        breaking=0,
        diff_available=False,
    )
    # Ownership pin: the expectation is read from the named owner, so the
    # compact line cannot drift apart from its vocabulary.
    assert formatters._API_SURFACE_DIFF_ABSENCE in text
    assert "breaking" not in text
    assert "added" not in text


def test_fmt_metrics_api_surface_compared_clean_stays_silent_about_absence() -> None:
    """Compared-and-clean keeps its shape and gains no false absence."""

    text = formatters.fmt_metrics_api_surface(
        public_symbols=10,
        modules=3,
        added=0,
        breaking=0,
        diff_available=True,
    )
    assert "unavailable" not in text
    assert "breaking" not in text


def test_fmt_metrics_adoption_line_formats_permille_fields() -> None:
    text = formatters.fmt_metrics_adoption(
        param_permille=800,
        return_permille=700,
        docstring_permille=600,
        any_annotation_count=2,
    )
    assert "params" in text
    assert "returns" in text
    assert "docstrings" in text


def test_fmt_metrics_coverage_join_ok_without_scope_gaps_or_source() -> None:
    text = formatters.fmt_metrics_coverage_join(
        status="ok",
        overall_permille=990,
        coverage_hotspots=0,
        scope_gap_hotspots=0,
        threshold_percent=80,
        source_label="",
    )
    assert "scope gaps" not in text


# ---------------------------------------------------------------------------
# One owner for the compact clone line
#
# Every other member of the SUMMARY_COMPACT* family is imported by its
# formatter and rendered with ``.format``; the clone line alone was assembled
# from a parallel parts list, and the two statements of the same line drifted
# apart -- the template never learned ``low_value``. These pins hold the
# template to the formatter's signature from both sides and prove the
# rendered line is actually produced by the template (`G1`).
# ---------------------------------------------------------------------------

_COMPACT_CLONE_SENTINEL = (
    "CLONESENTINEL {function}|{block}|{segment}|{suppressed}|{low_value}|{new}"
)


def _compact_clone_slots() -> set[str]:
    """Field names the compact clone template declares."""

    return {
        field
        for _, field, _, _ in string.Formatter().parse(labels.SUMMARY_COMPACT_CLONES)
        if field
    }


def _compact_clone_rendered_fields() -> set[str]:
    """Field names ``fmt_summary_compact_clones`` renders, from its signature."""

    return {
        name
        for name, parameter in inspect.signature(
            formatters.fmt_summary_compact_clones
        ).parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    }


def test_compact_clone_template_declares_every_rendered_field() -> None:
    # Boundary "a field went missing": the formatter renders a count the
    # template never learned. This is the drift that was measured -- the
    # template knew five fields while the line printed six.
    missing = _compact_clone_rendered_fields() - _compact_clone_slots()
    assert missing == set(), (
        "SUMMARY_COMPACT_CLONES is missing a slot for field(s) the compact "
        f"clone line renders: {sorted(missing)}"
    )


def test_compact_clone_template_declares_no_unrendered_field() -> None:
    # Boundary "a field is surplus": the template declares a slot no
    # parameter feeds. Caught by a different test than the missing case so
    # each direction fails on its own evidence.
    surplus = _compact_clone_slots() - _compact_clone_rendered_fields()
    assert surplus == set(), (
        "SUMMARY_COMPACT_CLONES declares slot(s) the compact clone line does "
        f"not render: {sorted(surplus)}"
    )


def test_compact_clone_line_is_rendered_from_its_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The ownership edge itself. Observable bytes cannot tell a template that
    # owns the line from a parts list that happens to agree with it, so the
    # probe replaces the template and demands the line follow: a formatter
    # that rebuilds the string by hand ignores the substitution and fails
    # here. Distinct slots also pin the field-to-slot wiring against a swap.
    monkeypatch.setattr(formatters, "SUMMARY_COMPACT_CLONES", _COMPACT_CLONE_SENTINEL)
    rendered = formatters.fmt_summary_compact_clones(
        function=1,
        block=2,
        segment=3,
        suppressed=4,
        low_value=5,
        new=6,
    )
    assert rendered == "CLONESENTINEL 1|2|3|4|5|6"


def test_compact_clone_template_renders_the_uncompared_novelty_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ``new`` reaches the template pre-rendered, the way ``health`` does for
    # SUMMARY_COMPACT_METRICS: "not compared" is not "zero new", and the
    # template must carry that sentence rather than a number.
    monkeypatch.setattr(formatters, "SUMMARY_COMPACT_CLONES", _COMPACT_CLONE_SENTINEL)
    rendered = formatters.fmt_summary_compact_clones(
        function=1,
        block=2,
        segment=3,
        suppressed=4,
        low_value=5,
        new=None,
    )
    assert rendered == (
        f"CLONESENTINEL 1|2|3|4|5|{formatters.CLONE_NOVELTY_UNAVAILABLE_TEXT}"
    )


def test_rich_clone_line_pins_its_qualifier_group() -> None:
    # The rich summary line is the only owner of the "suppressed" term now
    # that SUMMARY_LABEL_SUPPRESSED is gone. Pinning the whole parenthesised
    # group holds the terms, their order, and the separator, so dropping a
    # qualifier or re-joining the group fails here rather than silently.
    rendered = styling.strip_markup(
        formatters.fmt_summary_clones(
            func=1,
            block=2,
            segment=3,
            suppressed=23,
            low_value=13,
        )
    )
    assert "(23 suppressed, 13 low-value)" in rendered


def test_new_row_owns_the_baseline_relative_answer() -> None:
    # Novelty left the Clones line for a row of its own: a count reads as a
    # count, an uncompared run reads as words, and the reason travels with it.
    counted = styling.strip_markup(formatters.fmt_summary_new(7))
    absent = styling.strip_markup(
        formatters.fmt_summary_new(
            None, reason="no baseline yet", detail="codeclone.baseline.json"
        )
    )
    assert counted.startswith("  New")
    assert "7 clone groups since the baseline" in counted
    assert "not compared (no baseline yet · codeclone.baseline.json)" in absent
    assert "0" not in absent
