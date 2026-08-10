# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""CLI message formatters."""

from __future__ import annotations

import platform
import shlex
import sys
import textwrap
import traceback
from collections.abc import Iterable
from pathlib import Path

from .. import __version__
from ..contracts import ISSUES_URL
from .labels import (
    CLI_LAYOUT_MAX_WIDTH,
    SUMMARY_COMPACT,
    SUMMARY_COMPACT_BLAST_RADIUS,
    SUMMARY_COMPACT_CHANGED_SCOPE,
    SUMMARY_COMPACT_DEPENDENCIES,
    SUMMARY_COMPACT_METRICS,
    SUMMARY_COMPACT_PATCH_VERIFY,
    SUMMARY_COMPACT_SECURITY_SURFACES,
)
from .markers import BANNER_SUBTITLE, MARKER_CONTRACT_ERROR, MARKER_INTERNAL_ERROR
from .runtime import (
    ERR_BASELINE_CI_REQUIRES_TRUSTED,
    ERR_BASELINE_GATING_REQUIRES_TRUSTED,
    ERR_BASELINE_LOCK_RECOVERY_FAILED,
    ERR_BASELINE_WRITE_FAILED,
    ERR_INVALID_BASELINE,
    ERR_INVALID_BASELINE_PATH,
    ERR_INVALID_BASELINE_SCOPE_ID,
    ERR_INVALID_OUTPUT_EXT,
    ERR_INVALID_OUTPUT_PATH,
    ERR_MEMORY_DB_NOT_FOUND,
    ERR_MEMORY_ROOT_NOT_FOUND,
    ERR_REPORT_WRITE_FAILED,
    ERR_UNREADABLE_SOURCE_IN_GATING,
    INFO_PROCESSING_CHANGED,
    NOTE_COHESION_LCOM4_2_1_MIGRATION,
    NOTE_DEAD_CODE_REACHABILITY_2_0_1_MIGRATION,
    NOTE_DEAD_CODE_REACHABILITY_2_0_2_MIGRATION,
    SUCCESS_BASELINE_LOCK_RECOVERED,
    TIP_GITIGNORE_CODECLONE_CACHE,
    TIP_VSCODE_EXTENSION,
    WARN_BASELINE_LANES_OPAQUE,
    WARN_BATCH_ITEM_FAILED,
    WARN_CACHE_SAVE_FAILED,
    WARN_COVERAGE_JOIN_IGNORED,
    WARN_FAILED_FILES_HEADER,
    WARN_HTML_REPORT_OPEN_FAILED,
    WARN_LEGACY_CACHE,
    WARN_LEGACY_REPO_WORKSPACE,
    WARN_PARALLEL_FALLBACK,
    WARN_UNSUPPORTED_CONSTRUCT_SUMMARY,
    WARN_WORKER_FAILED,
)
from .styling import (
    _HEALTH_GRADE_STYLE,
    _L,
    GLYPH_OK,
    GLYPH_SEP,
    STYLE_COUNT_ATTENTION,
    STYLE_COUNT_ATTENTION_SOFT,
    STYLE_COUNT_CRITICAL,
    STYLE_COUNT_NEUTRAL,
    STYLE_EMPHASIS,
    STYLE_META,
    STYLE_VERDICT_FAIL,
    STYLE_VERDICT_PASS,
    STYLE_VERDICT_WARN,
    _format_permille_pct,
    _v,
    esc,
    n_of,
    strip_markup,
    styled,
)


def version_output(version: str) -> str:
    return f"CodeClone {version}"


def banner_title(version: str) -> str:
    return (
        f"  {styled('CodeClone', STYLE_EMPHASIS)} [dim]v{version}[/dim]"
        f"  [dim]{GLYPH_SEP}[/dim]  [dim]{BANNER_SUBTITLE}[/dim]"
    )


_REPORT_FLAG_BY_LABEL = {
    "HTML": "--html",
    "JSON": "--json",
    "Markdown": "--md",
    "SARIF": "--sarif",
    "text": "--text",
}


def _report_flag(label: str) -> str:
    return _REPORT_FLAG_BY_LABEL.get(label, "the report flag")


def fmt_invalid_output_extension(
    *, label: str, path: Path, expected_suffix: str
) -> str:
    return ERR_INVALID_OUTPUT_EXT.format(
        label=label,
        path=path,
        expected_suffix=expected_suffix,
        flag=_report_flag(label),
    )


def fmt_invalid_output_path(*, label: str, path: Path, error: object) -> str:
    return ERR_INVALID_OUTPUT_PATH.format(
        label=label, path=path, error=error, flag=_report_flag(label)
    )


def fmt_invalid_baseline_path(*, path: Path, error: object) -> str:
    return ERR_INVALID_BASELINE_PATH.format(path=path, error=error)


def fmt_baseline_write_failed(*, path: Path, error: object) -> str:
    return ERR_BASELINE_WRITE_FAILED.format(path=path, error=error)


def fmt_invalid_baseline_scope_id(*, path: Path, error: object) -> str:
    return ERR_INVALID_BASELINE_SCOPE_ID.format(path=path, error=error)


def fmt_report_write_failed(*, label: str, path: Path, error: object) -> str:
    return ERR_REPORT_WRITE_FAILED.format(
        label=label, path=path, error=error, flag=_report_flag(label)
    )


def fmt_html_report_open_failed(*, path: Path, error: object) -> str:
    return WARN_HTML_REPORT_OPEN_FAILED.format(path=path, error=error)


def fmt_coverage_join_ignored(error: object) -> str:
    return WARN_COVERAGE_JOIN_IGNORED.format(error=error)


def fmt_unreadable_source_in_gating(*, count: int) -> str:
    return ERR_UNREADABLE_SOURCE_IN_GATING.format(count=count)


def fmt_processing_changed(count: int) -> str:
    return INFO_PROCESSING_CHANGED.format(count=count)


def fmt_worker_failed(error: object) -> str:
    return WARN_WORKER_FAILED.format(error=error)


def fmt_batch_item_failed(error: object) -> str:
    return WARN_BATCH_ITEM_FAILED.format(error=error)


def fmt_parallel_fallback(error: object) -> str:
    return WARN_PARALLEL_FALLBACK.format(error=error)


def fmt_failed_files_header(count: int) -> str:
    return WARN_FAILED_FILES_HEADER.format(count=count)


def fmt_unsupported_construct_summary(
    *,
    count: int,
    constructs: Iterable[str],
) -> str:
    return WARN_UNSUPPORTED_CONSTRUCT_SUMMARY.format(
        count=count,
        constructs="; ".join(constructs),
    )


def fmt_cache_save_failed(error: object) -> str:
    return WARN_CACHE_SAVE_FAILED.format(error=error)


def fmt_vscode_extension_tip(*, url: str) -> str:
    return TIP_VSCODE_EXTENSION.format(url=url)


def fmt_gitignore_codeclone_cache_tip(*, message: str, entry: str) -> str:
    return TIP_GITIGNORE_CODECLONE_CACHE.format(
        message=message,
        entry=entry,
    )


def fmt_dead_code_reachability_migration_note(
    *,
    target_version: str = "2.0.1",
) -> str:
    if target_version == "2.0.2":
        return NOTE_DEAD_CODE_REACHABILITY_2_0_2_MIGRATION
    return NOTE_DEAD_CODE_REACHABILITY_2_0_1_MIGRATION


def fmt_cohesion_lcom4_migration_note(
    *,
    target_version: str = "2.1.0",
) -> str:
    _ = target_version
    return NOTE_COHESION_LCOM4_2_1_MIGRATION


def fmt_legacy_cache_warning(*, legacy_path: Path, new_path: Path) -> str:
    return WARN_LEGACY_CACHE.format(legacy_path=legacy_path, new_path=new_path)


def fmt_legacy_repo_workspace_warning(*, legacy_dir: Path, new_dir: Path) -> str:
    return WARN_LEGACY_REPO_WORKSPACE.format(legacy_dir=legacy_dir, new_dir=new_dir)


def fmt_invalid_baseline(error: object) -> str:
    return ERR_INVALID_BASELINE.format(error=error)


def fmt_baseline_lanes_opaque(lanes: Iterable[object]) -> str:
    """Name the opaque lanes deterministically, with their trust reasons."""

    rows = sorted(
        f"{getattr(item, 'name', item)}:{getattr(item, 'reason', 'unavailable')}"
        for item in lanes
    )
    return WARN_BASELINE_LANES_OPAQUE.format(lanes=", ".join(rows))


def fmt_baseline_gating_requires_trusted(*, ci: bool) -> str:
    return (
        ERR_BASELINE_CI_REQUIRES_TRUSTED if ci else ERR_BASELINE_GATING_REQUIRES_TRUSTED
    )


def fmt_cli_runtime_warning(message: object) -> str:
    source = strip_markup(str(message)).strip()
    paragraphs = [
        line.strip() for raw_line in source.splitlines() if (line := raw_line.strip())
    ]
    rendered: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        label = "Warning"
        body = paragraph.rstrip()
        lowered = body.lower()
        if lowered.startswith("cache "):
            label = "Cache"
            body = body[6:]
        elif lowered.startswith("baseline "):
            label = "Baseline"
            body = body[9:]
        elif lowered.startswith("legacy cache "):
            label = "Cache"

        segments = [segment.strip() for segment in body.split("; ") if segment.strip()]
        head = segments[0].rstrip(".)") if segments else body.rstrip(".)")
        details: list[str] = []
        if " (" in head:
            head, extra = head.split(" (", 1)
            details.append(extra.rstrip(".)"))
        if not details and ": " in head:
            head, extra = head.split(": ", 1)
            details.append(extra.rstrip(".)"))
        details.extend(segment.rstrip(".)") for segment in segments[1:])

        rendered.append(f"  [warning]{label}[/warning] {esc(head)}")
        for detail in details:
            rendered.extend(
                [
                    f"    [dim]{esc(wrapped)}[/dim]"
                    for wrapped in textwrap.wrap(
                        detail,
                        width=max(40, CLI_LAYOUT_MAX_WIDTH - 8),
                        break_long_words=False,
                        break_on_hyphens=False,
                    )
                ]
            )
        if index != len(paragraphs) - 1:
            rendered.append("")
    return "\n".join(rendered)


def fmt_path(template: str, path: Path) -> str:
    return template.format(path=path)


def fmt_summary_compact(
    *, found: int, analyzed: int, cache_hits: int, skipped: int
) -> str:
    return SUMMARY_COMPACT.format(
        found=found, analyzed=analyzed, cache_hits=cache_hits, skipped=skipped
    )


def fmt_summary_compact_clones(
    *,
    function: int,
    block: int,
    segment: int,
    suppressed: int,
    fixture_excluded: int,
    new: int,
) -> str:
    parts = [
        f"Clones   func={function}",
        f"block={block}",
        f"seg={segment}",
        f"suppressed={suppressed}",
    ]
    if fixture_excluded > 0:
        parts.append(f"fixtures={fixture_excluded}")
    parts.append(f"new={new}")
    return "  ".join(parts)


def fmt_summary_compact_metrics(
    *,
    cc_avg: float,
    cc_max: int,
    cbo_avg: float,
    cbo_max: int,
    lcom_avg: float,
    lcom_max: int,
    cycles: int,
    import_cycles: int,
    deferred_cycles: int,
    dead: int,
    health: int,
    grade: str,
    overloaded_modules: int,
) -> str:
    return SUMMARY_COMPACT_METRICS.format(
        cc_avg=f"{cc_avg:.1f}",
        cc_max=cc_max,
        cbo_avg=f"{cbo_avg:.1f}",
        cbo_max=cbo_max,
        lcom_avg=f"{lcom_avg:.1f}",
        lcom_max=lcom_max,
        cycles=cycles,
        import_cycles=import_cycles,
        deferred_cycles=deferred_cycles,
        dead=dead,
        health=health,
        grade=grade,
        overloaded_modules=overloaded_modules,
    )


def fmt_summary_compact_dependencies(
    *,
    avg_depth: float,
    p95_depth: int,
    max_depth: int,
) -> str:
    return SUMMARY_COMPACT_DEPENDENCIES.format(
        avg_depth=f"{avg_depth:.1f}",
        p95_depth=p95_depth,
        max_depth=max_depth,
    )


def fmt_summary_compact_security_surfaces(
    *,
    items: int,
    categories: int,
    production: int,
    tests: int,
) -> str:
    return SUMMARY_COMPACT_SECURITY_SURFACES.format(
        items=items,
        categories=categories,
        production=production,
        tests=tests,
    )


def fmt_summary_compact_adoption(
    *,
    param_permille: int,
    return_permille: int,
    docstring_permille: int,
    any_annotation_count: int,
) -> str:
    return (
        "Adoption"
        f"  params={_format_permille_pct(param_permille)}"
        f"  returns={_format_permille_pct(return_permille)}"
        f"  docstrings={_format_permille_pct(docstring_permille)}"
        f"  any={any_annotation_count}"
    )


def fmt_summary_compact_api_surface(
    *,
    public_symbols: int,
    modules: int,
    added: int,
    breaking: int,
) -> str:
    return (
        "Public API"
        f"  symbols={public_symbols}"
        f"  modules={modules}"
        f"  breaking={breaking}"
        f"  added={added}"
    )


def fmt_summary_compact_coverage_join(
    *,
    status: str,
    overall_permille: int,
    coverage_hotspots: int,
    scope_gap_hotspots: int,
    threshold_percent: int,
    source_label: str,
) -> str:
    parts = [f"Coverage  status={status or 'unknown'}"]
    if status == "ok":
        parts.extend(
            [
                f"overall={_format_permille_pct(overall_permille)}",
                f"coverage_hotspots={coverage_hotspots}",
                f"threshold={threshold_percent}",
            ]
        )
        if scope_gap_hotspots > 0:
            parts.append(f"scope_gaps={scope_gap_hotspots}")
    if source_label:
        parts.append(f"source={source_label}")
    return "  ".join(parts)


def fmt_summary_files(*, found: int, analyzed: int, cached: int, skipped: int) -> str:
    parts = [
        f"{_v(found, STYLE_EMPHASIS)} found",
        f"{_v(analyzed, STYLE_COUNT_NEUTRAL)} analyzed",
        f"{_v(cached)} cached",
        f"{_v(skipped)} skipped",
    ]
    val = f" {GLYPH_SEP} ".join(parts)
    return f"  {'Files':<{_L}}{val}"


def fmt_summary_parsed(
    *, lines: int, functions: int, methods: int, classes: int
) -> str | None:
    if lines == 0 and functions == 0 and methods == 0 and classes == 0:
        return None
    callable_count = functions + methods
    parts = [styled(n_of(lines, "line"), STYLE_COUNT_NEUTRAL)]
    if callable_count:
        parts.append(styled(n_of(callable_count, "callable"), STYLE_COUNT_NEUTRAL))
    if classes:
        parts.append(styled(n_of(classes, "class", "classes"), STYLE_COUNT_NEUTRAL))
    val = f" {GLYPH_SEP} ".join(parts)
    return f"  {'Parsed':<{_L}}{val}"


def fmt_summary_clones(
    *,
    func: int,
    block: int,
    segment: int,
    suppressed: int,
    fixture_excluded: int,
    new: int,
) -> str:
    clone_parts = [
        f"{_v(func, STYLE_COUNT_ATTENTION)} func",
        f"{_v(block, STYLE_COUNT_ATTENTION)} block",
    ]
    if segment:
        clone_parts.append(f"{_v(segment, STYLE_COUNT_ATTENTION)} seg")
    main = f" {GLYPH_SEP} ".join(clone_parts)
    quals = [
        f"{_v(suppressed, STYLE_COUNT_ATTENTION_SOFT)} suppressed",
    ]
    if fixture_excluded > 0:
        quals.append(f"{_v(fixture_excluded, STYLE_COUNT_ATTENTION_SOFT)} fixtures")
    quals.append(f"{_v(new, STYLE_COUNT_CRITICAL)} new")
    return f"  {'Clones':<{_L}}{main} ({', '.join(quals)})"


def fmt_metrics_health(total: int, grade: str) -> str:
    s = _HEALTH_GRADE_STYLE.get(grade, "bold")
    return f"  {'Health':<{_L}}[{s}]{total}/100 ({grade})[/{s}]"


def fmt_metrics_cc(avg: float, max_val: int, high_risk: int) -> str:
    hr = (
        styled(f"{high_risk:,} high-risk", STYLE_COUNT_CRITICAL)
        if high_risk
        else styled("0 high-risk", STYLE_META)
    )
    return f"  {'CC':<{_L}}avg {avg:.1f} {GLYPH_SEP} max {max_val} {GLYPH_SEP} {hr}"


def fmt_metrics_coupling(avg: float, max_val: int) -> str:
    return f"  {'Coupling':<{_L}}avg {avg:.1f} \u00b7 max {max_val}"


def fmt_metrics_cohesion(avg: float, max_val: int) -> str:
    return f"  {'Cohesion':<{_L}}avg {avg:.1f} \u00b7 max {max_val}"


def fmt_metrics_cycles(count: int, *, import_cycles: int, deferred: int) -> str:
    """Render the cycle total with its kind split.

    The total alone stopped predicting the exit code once only import cycles
    gate, so the breakdown is not decoration: it is the difference between a
    build that fails and one that does not. A deferred-only run is styled as a
    warning rather than a failure because that is exactly what it now is.
    """

    if count == 0:
        return f"  {'Cycles':<{_L}}{styled(f'{GLYPH_OK} clean', STYLE_VERDICT_PASS)}"
    detail = f"{count:,} detected ({import_cycles:,} import, {deferred:,} deferred)"
    style = STYLE_VERDICT_FAIL if import_cycles > 0 else STYLE_VERDICT_WARN
    return f"  {'Cycles':<{_L}}{styled(detail, style)}"


def fmt_metrics_dependencies(
    *, avg_depth: float, p95_depth: int, max_depth: int
) -> str:
    return (
        f"  {'Dependencies':<{_L}}"
        f"avg {avg_depth:.1f} · p95 {p95_depth} · max {max_depth}"
    )


def fmt_metrics_security_surfaces(
    *,
    items: int,
    categories: int,
    production: int,
    tests: int,
) -> str:
    return (
        f"  {'Security':<{_L}}"
        f"{_v(items, STYLE_COUNT_NEUTRAL)} surfaces"
        f" {GLYPH_SEP} {_v(categories, STYLE_COUNT_NEUTRAL)} categories"
        f" {GLYPH_SEP} production {_v(production)}"
        f" {GLYPH_SEP} tests {_v(tests)}"
    )


def fmt_metrics_dead_code(count: int, *, suppressed: int = 0) -> str:
    suppressed_suffix = (
        f" [dim]({suppressed} suppressed)[/dim]" if suppressed > 0 else ""
    )
    match count:
        case 0:
            return (
                f"  {'Dead code':<{_L}}"
                f"{styled(f'{GLYPH_OK} clean', STYLE_VERDICT_PASS)}"
                f"{suppressed_suffix}"
            )
        case _:
            return (
                f"  {'Dead code':<{_L}}"
                f"{styled(f'{count:,} found', STYLE_VERDICT_FAIL)}"
                f"{suppressed_suffix}"
            )


def fmt_metrics_adoption(
    *,
    param_permille: int,
    return_permille: int,
    docstring_permille: int,
    any_annotation_count: int,
) -> str:
    parts = [
        f"params {_format_permille_pct(param_permille)}",
        f"returns {_format_permille_pct(return_permille)}",
        f"docstrings {_format_permille_pct(docstring_permille)}",
        f"Any {_v(any_annotation_count)}",
    ]
    return f"  {'Adoption':<{_L}}{f' {GLYPH_SEP} '.join(parts)}"


def fmt_metrics_api_surface(
    *,
    public_symbols: int,
    modules: int,
    added: int,
    breaking: int,
) -> str:
    parts = [
        f"{_v(public_symbols, STYLE_COUNT_NEUTRAL)} symbols",
        f"{_v(modules, STYLE_COUNT_NEUTRAL)} modules",
    ]
    if breaking > 0 or added > 0:
        parts.append(
            " / ".join(
                [
                    f"{_v(breaking, STYLE_COUNT_CRITICAL)} breaking",
                    f"{_v(added, STYLE_COUNT_NEUTRAL)} added",
                ]
            )
        )
    return f"  {'Public API':<{_L}}{f' {GLYPH_SEP} '.join(parts)}"


def fmt_metrics_coverage_join(
    *,
    status: str,
    overall_permille: int,
    coverage_hotspots: int,
    scope_gap_hotspots: int,
    threshold_percent: int,
    source_label: str,
) -> str:
    if status != "ok":
        parts = ["join unavailable"]
        if source_label:
            parts.append(source_label)
        return (
            f"  {'Coverage':<{_L}}"
            f"{styled(f' {GLYPH_SEP} '.join(parts), STYLE_VERDICT_WARN)}"
        )
    parts = [
        f"{_format_permille_pct(overall_permille)} overall",
        f"{_v(coverage_hotspots, STYLE_COUNT_CRITICAL)} hotspots"
        f" < {threshold_percent}%",
    ]
    if scope_gap_hotspots > 0:
        parts.append(f"{_v(scope_gap_hotspots, STYLE_COUNT_ATTENTION)} scope gaps")
    if source_label:
        parts.append(source_label)
    return f"  {'Coverage':<{_L}}{f' {GLYPH_SEP} '.join(parts)}"


def fmt_metrics_overloaded_modules(
    *,
    candidates: int,
    total: int,
    population_status: str,
    top_score: float,
) -> str:
    parts = [f"{_v(candidates, STYLE_COUNT_NEUTRAL)} candidates"]
    if top_score > 0:
        parts.append(f"max score {top_score:.2f}")
    parts.append(f"{_v(total)} ranked")
    summary = f" {GLYPH_SEP} ".join(parts)
    note = "report-only"
    if population_status and population_status != "ok":
        note = f"{note}; {population_status.replace('_', ' ')} population"
    return f"  {'Overloaded':<{_L}}{summary} [dim]({note})[/dim]"


def fmt_changed_scope_paths(*, count: int) -> str:
    return f"  {'Paths':<{_L}}{_v(count, STYLE_COUNT_NEUTRAL)} from git diff"


def fmt_changed_scope_findings(*, total: int, new: int, known: int) -> str:
    parts = [
        f"{_v(total, STYLE_EMPHASIS)} total",
        f"{_v(new, STYLE_COUNT_NEUTRAL)} new",
        f"{_v(known)} known",
    ]
    separator = f" {GLYPH_SEP} "
    return f"  {'Findings':<{_L}}{separator.join(parts)}"


def fmt_changed_scope_compact(
    *,
    paths: int,
    findings: int,
    new: int,
    known: int,
) -> str:
    return SUMMARY_COMPACT_CHANGED_SCOPE.format(
        paths=paths,
        findings=findings,
        new=new,
        known=known,
    )


def fmt_blast_radius_compact(
    *,
    level: str,
    dependents: int,
    cohorts: int,
    cycles: int,
    do_not_touch: int,
) -> str:
    return SUMMARY_COMPACT_BLAST_RADIUS.format(
        level=level,
        dependents=dependents,
        cohorts=cohorts,
        cycles=cycles,
        do_not_touch=do_not_touch,
    )


def fmt_patch_verify_compact(
    *,
    status: str,
    health_before: int,
    health_after: int,
    regressions: int,
    gate_status: str,
) -> str:
    return SUMMARY_COMPACT_PATCH_VERIFY.format(
        status=status,
        health_before=health_before,
        health_after=health_after,
        regressions=regressions,
        gate_status=gate_status,
    )


def fmt_pipeline_done(elapsed: float) -> str:
    return f"  [dim]Pipeline done in {elapsed:.2f}s[/dim]"


def fmt_contract_error(message: str) -> str:
    return f"{MARKER_CONTRACT_ERROR}\n{message}"


def fmt_memory_db_not_found(*, error: object) -> str:
    return ERR_MEMORY_DB_NOT_FOUND.format(error=error)


def fmt_memory_root_not_found(*, path: object) -> str:
    return ERR_MEMORY_ROOT_NOT_FOUND.format(path=path)


def fmt_baseline_lock_recovery_failed(*, path: Path, reason: str) -> str:
    return ERR_BASELINE_LOCK_RECOVERY_FAILED.format(path=path, reason=reason)


def fmt_baseline_lock_recovered(*, path: Path) -> str:
    return SUCCESS_BASELINE_LOCK_RECOVERED.format(path=path)


def fmt_internal_error(
    error: BaseException,
    *,
    issues_url: str = ISSUES_URL,
    debug: bool = False,
) -> str:
    bug_report_url = issues_url.rstrip("/") + "/new?template=bug_report.yml"
    error_name = type(error).__name__
    error_text = str(error).strip() or "<no message>"
    lines = [
        MARKER_INTERNAL_ERROR,
        "Unexpected exception.",
        f"Reason: {error_name}: {error_text}",
        "",
        "Next steps:",
        "- Re-run with --debug to include a traceback.",
        f"- If this is reproducible, open an issue: {bug_report_url}.",
        (
            "- Attach: command line, CodeClone version, Python version, "
            "and the report file if generated."
        ),
    ]
    if not debug:
        return "\n".join(lines)

    traceback_lines = traceback.format_exception(
        type(error), error, error.__traceback__
    )
    command_line = shlex.join(sys.argv)
    lines.extend(
        [
            "",
            "DEBUG DETAILS",
            f"Platform: {platform.platform()}",
            f"Python: {sys.version.split()[0]}",
            f"CodeClone: {__version__}",
            f"Command: {command_line}",
            f"CWD: {Path.cwd()}",
            "Traceback:",
            "".join(traceback_lines).rstrip(),
        ]
    )
    return "\n".join(lines)
