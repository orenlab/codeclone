# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from codeclone.ui_messages import formatters


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
    assert "join unavailable" in text
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
    assert "join unavailable" in text
    assert " · " not in text.split("join unavailable", 1)[-1]


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
    assert "baseline comparison unavailable" in text
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
