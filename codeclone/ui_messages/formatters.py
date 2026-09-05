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
from typing import TYPE_CHECKING, Final, Literal

from .. import __version__
from ..contracts import ISSUES_URL
from ..contracts.errors import DiagnosedUserError
from .labels import (
    CLI_LAYOUT_MAX_WIDTH,
    SUMMARY_COMPACT,
    SUMMARY_COMPACT_BLAST_RADIUS,
    SUMMARY_COMPACT_CHANGED_SCOPE,
    SUMMARY_COMPACT_CLONES,
    SUMMARY_COMPACT_DEPENDENCIES,
    SUMMARY_COMPACT_METRICS,
    SUMMARY_COMPACT_NOVELTY,
    SUMMARY_COMPACT_PATCH_VERIFY,
    SUMMARY_COMPACT_SECURITY_SURFACES,
)
from .markers import BANNER_SUBTITLE, MARKER_CONTRACT_ERROR, MARKER_INTERNAL_ERROR
from .runtime import (
    ACTION_API_SURFACE_BASELINE,
    ACTION_CI,
    ACTION_FAIL_ON_NEW,
    ACTION_HTML,
    ACTION_UPDATE_BASELINE,
    ERR_BASELINE_CI_REQUIRES_TRUSTED,
    ERR_BASELINE_GATING_REQUIRES_TRUSTED,
    ERR_BASELINE_LOCK_RECOVERY_FAILED,
    ERR_BASELINE_SCOPE_ID_REQUIRED,
    ERR_BASELINE_WRITE_FAILED,
    ERR_INVALID_BASELINE_PATH,
    ERR_INVALID_BASELINE_SCOPE_ID,
    ERR_INVALID_OUTPUT_EXT,
    ERR_INVALID_OUTPUT_PATH,
    ERR_MEMORY_DB_NOT_FOUND,
    ERR_MEMORY_ROOT_NOT_FOUND,
    ERR_REPORT_WRITE_FAILED,
    ERR_UNREADABLE_SOURCE_IN_GATING,
    HINT_SCOPE_ID_ADD_KEY,
    HINT_SCOPE_ID_ADD_SECTION,
    HINT_SCOPE_ID_CREATE_FILE,
    HINT_SCOPE_ID_FOOTER,
    HINT_SCOPE_ID_KEY_LINE,
    HINT_SCOPE_ID_TABLE_HEADER,
    INFO_PROCESSING_CHANGED,
    NOTE_BASELINE_FOREIGN_INTERPRETER,
    NOTE_COHESION_LCOM4_2_1_MIGRATION,
    NOTE_DEAD_CODE_REACHABILITY_2_0_1_MIGRATION,
    NOTE_DEAD_CODE_REACHABILITY_2_0_2_MIGRATION,
    NOVELTY_REASON_NO_BASELINE,
    OUTCOME_API_NOT_COMPARED,
    OUTCOME_BASELINE_WRITTEN,
    OUTCOME_BASELINE_WRITTEN_NEXT,
    OUTCOME_CLEAN,
    OUTCOME_CREATE_BASELINE,
    OUTCOME_EMPTY_SCOPE,
    OUTCOME_EMPTY_SCOPE_NEXT,
    OUTCOME_FIRST_RUN_THEN,
    OUTCOME_FIRST_RUN_WHY,
    OUTCOME_GATE_IN_CI,
    OUTCOME_GATE_PASSED,
    OUTCOME_IGNORED_NEXT,
    OUTCOME_LOCATIONS,
    OUTCOME_NEW_CLONES,
    OUTCOME_NEW_CLONES_ACCEPT,
    OUTCOME_NEW_CLONES_BLOCK,
    OUTCOME_NEW_CLONES_QUIET,
    OUTCOME_NOT_COMPARED,
    SUCCESS_BASELINE_LOCK_RECOVERED,
    SUCCESS_BASELINE_UPDATED,
    TIP_GITIGNORE_CODECLONE_CACHE,
    TIP_VSCODE_EXTENSION,
    WARN_BASELINE_IGNORED,
    WARN_BASELINE_INVALID,
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
    GLYPH_FAIL,
    GLYPH_OK,
    GLYPH_SEP,
    GLYPH_WARN,
    INDENT_UNIT,
    STYLE_COUNT_ATTENTION,
    STYLE_COUNT_ATTENTION_SOFT,
    STYLE_COUNT_CRITICAL,
    STYLE_COUNT_NEUTRAL,
    STYLE_EMPHASIS,
    STYLE_META,
    STYLE_VERDICT_FAIL,
    STYLE_VERDICT_PASS,
    STYLE_VERDICT_PASS_STRONG,
    STYLE_VERDICT_WARN,
    _format_permille_pct,
    _v,
    esc,
    n_of,
    strip_markup,
    styled,
)

if TYPE_CHECKING:
    from uuid import UUID

    from ..api.config_delivery import ToolCodecloneTableState


def version_output(version: str) -> str:
    return f"CodeClone {version}"


def banner_title(version: str) -> str:
    return (
        f"  {styled('CodeClone', STYLE_EMPHASIS)} [dim]v{version}[/dim]"
        f"  [dim]{GLYPH_SEP}[/dim]  [dim]{BANNER_SUBTITLE}[/dim]"
    )


#: The grid: block content sits one unit in, detail under it sits two.
_INDENT = " " * INDENT_UNIT
_DETAIL_INDENT = " " * (INDENT_UNIT * 2)


def _indent_block(text: str, indent: str = _DETAIL_INDENT) -> str:
    """Indent every non-blank line of ``text``; blank lines stay empty."""

    return "\n".join(
        f"{indent}{line}" if line.strip() else "" for line in text.splitlines()
    )


def _advisory_block(text: str, *, glyph: str, style: str) -> str:
    """One advisory on the grid: a glyphed head line, dim detail under it."""

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    head, *details = lines
    rendered = [f"{_INDENT}[{style}]{glyph} {esc(head.rstrip('.'))}[/{style}]"]
    rendered.extend(
        f"{_DETAIL_INDENT}[{STYLE_META}]{esc(detail)}[/{STYLE_META}]"
        for detail in details
    )
    return "\n".join(rendered)


def fmt_banner_root(path: object) -> str:
    return f"{_INDENT}{'Root':<{_L}}[{STYLE_META}]{esc(path)}[/{STYLE_META}]"


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
        label=label, path=esc(path), error=esc(error), flag=_report_flag(label)
    )


def fmt_invalid_baseline_path(*, path: Path, error: object) -> str:
    return ERR_INVALID_BASELINE_PATH.format(path=esc(path), error=esc(error))


def fmt_baseline_write_failed(*, path: Path, error: object) -> str:
    return ERR_BASELINE_WRITE_FAILED.format(path=esc(path), error=esc(error))


def fmt_invalid_baseline_scope_id(*, path: Path, error: object) -> str:
    return ERR_INVALID_BASELINE_SCOPE_ID.format(path=esc(path), error=esc(error))


def fmt_report_write_failed(*, label: str, path: Path, error: object) -> str:
    return ERR_REPORT_WRITE_FAILED.format(
        label=label, path=esc(path), error=esc(error), flag=_report_flag(label)
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


def fmt_invalid_baseline(error: object, *, ignored: bool = True) -> str:
    """One advisory for an unusable baseline, in the register the run needs.

    ``ignored`` is the advisory register: the run continues without a
    comparison, so the block is the whole story, remedy included. The gating
    register states the fact and stops there -- the refusal that follows it
    carries the remedy once, instead of both blocks naming the same command.
    """

    template = WARN_BASELINE_IGNORED if ignored else WARN_BASELINE_INVALID
    return _advisory_block(
        template.format(error=error),
        glyph=GLYPH_WARN if ignored else GLYPH_FAIL,
        style=STYLE_VERDICT_WARN if ignored else STYLE_VERDICT_FAIL,
    )


def fmt_baseline_updated(path: object) -> str:
    return SUCCESS_BASELINE_UPDATED.format(path=esc(path))


def fmt_baseline_foreign_interpreter(*, baseline_tag: str, runtime_tag: str) -> str:
    """Report a usable baseline's foreign interpreter as origin, not as distrust.

    The wording is deliberately not a warning: the run proceeds, the comparison
    ran, and novelty is real. It is placed beside the other baseline notes so the
    operator sees the provenance without being told to regenerate anything.
    """

    head, detail = NOTE_BASELINE_FOREIGN_INTERPRETER.format(
        baseline_tag=baseline_tag,
        runtime_tag=runtime_tag,
    ).splitlines()
    label = f"[{STYLE_META}]Note[/{STYLE_META}]"
    hang = " " * (INDENT_UNIT + len("Note") + 2)
    return (
        f"{_INDENT}{label}  {esc(head)}\n"
        f"{hang}[{STYLE_META}]{esc(detail)}[/{STYLE_META}]"
    )


def fmt_baseline_lanes_opaque(lanes: Iterable[object]) -> str:
    """Name the opaque lanes deterministically, with their trust reasons."""

    rows = sorted(
        f"{getattr(item, 'name', item)}:{getattr(item, 'reason', 'unavailable')}"
        for item in lanes
    )
    return _advisory_block(
        WARN_BASELINE_LANES_OPAQUE.format(lanes=", ".join(rows)),
        glyph=GLYPH_WARN,
        style=STYLE_VERDICT_WARN,
    )


def fmt_baseline_gating_requires_trusted(*, ci: bool) -> str:
    return (
        ERR_BASELINE_CI_REQUIRES_TRUSTED if ci else ERR_BASELINE_GATING_REQUIRES_TRUSTED
    )


def fmt_cli_runtime_warning(message: object) -> str:
    """Put a runtime warning on the grid: glyphed head, dim detail under it.

    The first paragraph is the head; a ``"; "`` list, a parenthesis or the
    first ``": "`` splits its detail off, and every later paragraph is more
    detail. Detail lines are wrapped to the detail column; a token longer than
    the column (a path) is left whole for the console to fold in place.
    """

    source = strip_markup(str(message)).strip()
    paragraphs = [
        line.strip() for raw_line in source.splitlines() if (line := raw_line.strip())
    ]
    if not paragraphs:
        return ""
    first, *rest = paragraphs
    segments = [segment.strip() for segment in first.split("; ") if segment.strip()]
    head = segments[0].rstrip(".)") if segments else first.rstrip(".)")
    details: list[str] = []
    if " (" in head:
        head, extra = head.split(" (", 1)
        details.append(extra.rstrip(".)"))
    if not details and ": " in head:
        head, extra = head.split(": ", 1)
        details.append(extra.rstrip(".)"))
    details.extend(segment.rstrip(".)") for segment in segments[1:])
    details.extend(rest)

    rendered = [f"{_INDENT}[warning]{GLYPH_WARN} {esc(head)}[/warning]"]
    for detail in details:
        rendered.extend(
            [
                f"{_DETAIL_INDENT}[{STYLE_META}]{esc(wrapped)}[/{STYLE_META}]"
                for wrapped in textwrap.wrap(
                    detail,
                    width=max(40, CLI_LAYOUT_MAX_WIDTH - len(_DETAIL_INDENT)),
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            ]
        )
    return "\n".join(rendered)


def fmt_path(template: str, path: Path) -> str:
    return template.format(path=path)


def fmt_summary_compact(
    *, found: int, analyzed: int, cache_hits: int, skipped: int
) -> str:
    return SUMMARY_COMPACT.format(
        found=found, analyzed=analyzed, cache_hits=cache_hits, skipped=skipped
    )


#: Rendered in place of a new-clone count when no clone lane was compared
#: against the baseline. "Not compared" is not "zero new".
CLONE_NOVELTY_UNAVAILABLE_TEXT = "unavailable"


def fmt_summary_compact_clones(
    *,
    function: int,
    block: int,
    segment: int,
    suppressed: int,
    low_value: int,
    new: int | None,
) -> str:
    # One owner for this line. Assembling it from a parallel parts list left
    # the template stating a shape the line had already outgrown -- it never
    # learned ``low_value`` -- so the template is read, not restated (`G1`).
    return SUMMARY_COMPACT_CLONES.format(
        function=function,
        block=block,
        segment=segment,
        suppressed=suppressed,
        low_value=low_value,
        new=CLONE_NOVELTY_UNAVAILABLE_TEXT if new is None else new,
    )


def fmt_summary_compact_novelty(*, reason: str, detail: str = "") -> str:
    """Quiet-mode line for a run that compared nothing, with the file named."""

    why = reason.replace(" ", "_")
    if detail:
        why = f"{why}  path={detail}"
    return SUMMARY_COMPACT_NOVELTY.format(reason=why)


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
    population: str = "complete_nonempty",
) -> str:
    # The compact mirror of ``fmt_metrics_health``: the same owner table
    # decides whether a verdict exists, and the same sentence words the
    # absence, so the quiet and rich branches cannot drift apart (`G1`).
    # Printing ``0(F)`` here for a population that carries no score was a
    # verdict about code nobody read.
    absence = _HEALTH_ABSENCE_LINE.get(population)
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
        health=absence if absence is not None else f"{health}({grade})",
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
    diff_available: bool,
) -> str:
    # ``symbols=`` / ``modules=`` are facts of the current run and always
    # print. ``breaking=`` / ``added=`` are facts about a baseline comparison:
    # when that comparison never ran there is nothing to print, and printing
    # the default zeros rendered a withheld run byte-identical to "compared,
    # clean". The compact line omits the terms; the rich surfaces pronounce
    # the absence in words — the ratified adoption split.
    line = f"Public API  symbols={public_symbols}  modules={modules}"
    if not diff_available:
        return line
    return f"{line}  breaking={breaking}  added={added}"


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
    low_value: int,
) -> str:
    """The clone inventory of this run, family by family.

    Novelty is not here any more: whether a group is new is a fact about the
    baseline, not about the inventory, and it has its own row
    (:func:`fmt_summary_new`) so the two questions -- how much duplication,
    and what changed -- are answered one at a time.
    """

    clone_parts = [
        f"{_v(func, STYLE_COUNT_ATTENTION)} function",
        f"{_v(block, STYLE_COUNT_ATTENTION)} block",
    ]
    if segment:
        clone_parts.append(f"{_v(segment, STYLE_COUNT_ATTENTION)} segment")
    main = f" {GLYPH_SEP} ".join(clone_parts)
    quals = [
        f"{_v(suppressed, STYLE_COUNT_ATTENTION_SOFT)} suppressed",
        f"{_v(low_value, STYLE_COUNT_ATTENTION_SOFT)} low-value",
    ]
    return f"  {'Clones':<{_L}}{main} ({', '.join(quals)})"


def fmt_summary_new(new: int | None, *, reason: str = "", detail: str = "") -> str:
    """The baseline-relative answer: how many clone groups are new.

    ``None`` means no clone lane was compared; the row then says so and names
    the reason in words, because "not compared" is not "zero new". ``detail``
    is the file the reason is about -- the path a missing baseline was looked
    for at -- so the reader who passed ``--baseline`` sees which one.
    """

    if new is None:
        why = reason or CLONE_NOVELTY_UNAVAILABLE_TEXT
        if detail:
            why = f"{why} {GLYPH_SEP} {detail}"
        absence = f"not compared ({esc(why)})"
        return f"  {'New':<{_L}}[{STYLE_META}]{absence}[/{STYLE_META}]"
    noun = "clone group" if new == 1 else "clone groups"
    return f"  {'New':<{_L}}{_v(new, STYLE_COUNT_CRITICAL)} {noun} since the baseline"


def fmt_summary_metrics_skipped(*, requested: bool) -> str:
    """Why the Metrics section is absent, and how to get it.

    A run without a baseline skips metrics by default; the reader who sees a
    Summary and no Metrics is asking why. ``requested`` is the explicit
    ``--skip-metrics`` case, which needs no remedy.
    """

    if requested:
        detail = "skipped (--skip-metrics)"
    else:
        detail = "not run without a baseline (--no-skip-metrics runs them now)"
    return f"  {'Metrics':<{_L}}[{STYLE_META}]{detail}[/{STYLE_META}]"


#: Population states that print no grade on the summary line, each with its
#: own sentence. One table rather than a chain of ``if``s: a state added
#: without a row here prints a score, which is the failure mode this whole
#: split exists to stop.
_HEALTH_ABSENCE_LINE: Final[dict[str, str]] = {
    "unmeasured": "not measured (no file was read)",
    "complete_empty": "not measured (no source file in scope)",
}


def fmt_metrics_health(
    total: int,
    grade: str,
    *,
    population: str = "complete_nonempty",
) -> str:
    absence = _HEALTH_ABSENCE_LINE.get(population)
    if absence is not None:
        # There is no grade to print. Showing one — of any letter — would be a
        # verdict about code the run never opened, or about code that does not
        # exist. Two absences, two sentences: one sends the reader to the dead
        # worker, the other to the analysis root.
        return f"  {'Health':<{_L}}[bold]{absence}[/bold]"
    s = _HEALTH_GRADE_STYLE.get(grade, "bold")
    return f"  {'Health':<{_L}}[{s}]{total}/100 ({grade})[/{s}]"


def fmt_metrics_cc(avg: float, max_val: int, high_risk: int) -> str:
    hr = (
        styled(f"{high_risk:,} high-risk", STYLE_COUNT_CRITICAL)
        if high_risk
        else styled("0 high-risk", STYLE_META)
    )
    detail = f"avg {avg:.1f} {GLYPH_SEP} max {max_val} {GLYPH_SEP} {hr}"
    return f"  {'Complexity':<{_L}}{detail}"


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
        f"avg depth {avg_depth:.1f} {GLYPH_SEP} p95 {p95_depth}"
        f" {GLYPH_SEP} max {max_depth}"
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


#: The rich line's absence sentence for an API comparison that never ran.
#: One owner for the wording, mirroring the coverage-join "join unavailable"
#: pattern: the fact is stated in words, never as fabricated zeros.
_API_SURFACE_DIFF_ABSENCE: Final = "not compared with the baseline"

#: The metrics line's absence term for a coverage join that never ran.
#: Same role, same register: the fact is stated in words by a named owner,
#: so the spelling cannot drift apart from the tests that pin it.
_COVERAGE_JOIN_ABSENCE: Final = "not joined"


def fmt_metrics_api_surface(
    *,
    public_symbols: int,
    modules: int,
    added: int,
    breaking: int,
    diff_available: bool,
) -> str:
    parts = [
        f"{_v(public_symbols, STYLE_COUNT_NEUTRAL)} symbols",
        f"{_v(modules, STYLE_COUNT_NEUTRAL)} modules",
    ]
    if not diff_available:
        # The comparison never ran, so there are no breaking/added facts.
        # Silence here rendered a withheld run byte-identical to "compared,
        # clean"; the rich surface pronounces the absence instead.
        parts.append(f"[dim]{_API_SURFACE_DIFF_ABSENCE}[/dim]")
    elif breaking > 0 or added > 0:
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
        parts = [_COVERAGE_JOIN_ABSENCE]
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
    parts = [f"{_v(candidates, STYLE_COUNT_NEUTRAL)} of {_v(total)} ranked"]
    if top_score > 0:
        parts.append(f"max score {top_score:.2f}")
    summary = f" {GLYPH_SEP} ".join(parts)
    note = "report-only"
    if population_status and population_status != "ok":
        note = f"{note}, {population_status.replace('_', ' ')} population"
    return f"  {'Overloaded':<{_L}}{summary} [{STYLE_META}]({note})[/{STYLE_META}]"


def fmt_changed_scope_paths(*, count: int) -> str:
    return f"  {'Paths':<{_L}}{_v(count, STYLE_COUNT_NEUTRAL)} from git diff"


def fmt_changed_scope_findings(
    *,
    total: int,
    new: int,
    known: int,
    unavailable: int = 0,
) -> str:
    # The third novelty state is named only when it exists: at zero the
    # arithmetic ``new + known == total`` already says everything, while a
    # nonzero count kept silent reads as "nothing new" for findings whose
    # comparison never ran (`G4`). The word has one owner.
    parts = [
        f"{_v(total, STYLE_EMPHASIS)} total",
        f"{_v(new, STYLE_COUNT_NEUTRAL)} new",
        f"{_v(known)} known",
    ]
    if unavailable > 0:
        parts.append(f"{_v(unavailable)} {CLONE_NOVELTY_UNAVAILABLE_TEXT}")
    separator = f" {GLYPH_SEP} "
    return f"  {'Findings':<{_L}}{separator.join(parts)}"


def fmt_changed_scope_compact(
    *,
    paths: int,
    findings: int,
    new: int,
    known: int,
    unavailable: int = 0,
) -> str:
    line = SUMMARY_COMPACT_CHANGED_SCOPE.format(
        paths=paths,
        findings=findings,
        new=new,
        known=known,
    )
    # Same boundary as the rich line: the term appears only above zero, so
    # the two surfaces of this one fact cannot disagree about when it exists.
    if unavailable > 0:
        line = f"{line}  {CLONE_NOVELTY_UNAVAILABLE_TEXT}={unavailable}"
    return line


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


RunOutcomeKind = Literal[
    "empty_scope",
    "baseline_written",
    "not_compared",
    "clean",
    "gate_passed",
    "new_clones",
]

#: Column where the commands of an outcome block line up.
_OUTCOME_LABEL_WIDTH = 26


def fmt_run_outcome(
    *,
    kind: RunOutcomeKind,
    elapsed: float,
    baseline_display: str = "",
    reason: str = "",
    new_clones: int = 0,
    show_locations: bool = False,
    api_not_compared: bool = False,
) -> str:
    """The last block of a run: did it pass, and what to type now.

    One block, one owner. It replaced three things that used to close a run
    -- a "new clones detected" warning, a "pipeline done" timing line and,
    for a first run, nothing at all -- so the reader ends every run on the
    same line shape: a verdict glyph, the verdict, the timing, and under it
    a sentence when one is owed and the commands that apply to this state,
    every command in one column.
    """

    timing = f"[{STYLE_META}]{elapsed:.2f}s[/{STYLE_META}]"
    prose: list[str] = []
    commands: list[tuple[str, str]] = []
    if kind == "empty_scope":
        head = styled(f"{GLYPH_WARN} {OUTCOME_EMPTY_SCOPE}", STYLE_VERDICT_WARN)
        prose = [OUTCOME_EMPTY_SCOPE_NEXT]
    elif kind == "baseline_written":
        head = styled(
            f"{GLYPH_OK} {OUTCOME_BASELINE_WRITTEN.format(path=esc(baseline_display))}",
            STYLE_VERDICT_PASS_STRONG,
        )
        prose = [OUTCOME_BASELINE_WRITTEN_NEXT]
        commands = [(OUTCOME_GATE_IN_CI, ACTION_CI)]
    elif kind == "not_compared":
        head = styled(
            f"{GLYPH_WARN} {OUTCOME_NOT_COMPARED.format(reason=esc(reason))}",
            STYLE_VERDICT_WARN,
        )
        if reason == NOVELTY_REASON_NO_BASELINE:
            prose = [OUTCOME_FIRST_RUN_WHY]
            commands = [
                (OUTCOME_CREATE_BASELINE, ACTION_UPDATE_BASELINE),
                (OUTCOME_FIRST_RUN_THEN, ACTION_CI),
            ]
        else:
            commands = [(OUTCOME_IGNORED_NEXT, ACTION_UPDATE_BASELINE)]
    elif kind == "clean":
        head = styled(f"{GLYPH_OK} {OUTCOME_CLEAN}", STYLE_VERDICT_PASS)
    elif kind == "gate_passed":
        head = styled(
            f"{GLYPH_OK} {OUTCOME_GATE_PASSED} {GLYPH_SEP} exit 0",
            STYLE_VERDICT_PASS_STRONG,
        )
    else:
        head = styled(
            f"{GLYPH_WARN} "
            f"{OUTCOME_NEW_CLONES.format(count=n_of(new_clones, 'new clone group'))}",
            STYLE_VERDICT_WARN,
        )
        commands = [
            (OUTCOME_NEW_CLONES_BLOCK, ACTION_FAIL_ON_NEW),
            (OUTCOME_NEW_CLONES_ACCEPT, ACTION_UPDATE_BASELINE),
        ]
    if show_locations and kind != "empty_scope":
        commands.append((OUTCOME_LOCATIONS, ACTION_HTML))
    if api_not_compared:
        commands.append((OUTCOME_API_NOT_COMPARED, ACTION_API_SURFACE_BASELINE))
    lines = ["", f"{_INDENT}{head} [{STYLE_META}]{GLYPH_SEP}[/{STYLE_META}] {timing}"]
    lines.extend(f"{_DETAIL_INDENT}{line}" for line in prose)
    lines.extend(
        f"{_DETAIL_INDENT}{label:<{_OUTCOME_LABEL_WIDTH}}{command}"
        for label, command in commands
    )
    return "\n".join(lines)


def fmt_run_outcome_quiet(*, new_clones: int) -> str:
    """The one outcome a quiet run still prints: new clones nobody gated."""

    return (
        f"[warning]{GLYPH_WARN} "
        f"{OUTCOME_NEW_CLONES_QUIET.format(count=n_of(new_clones, 'new clone group'))}"
        "[/warning]"
    )


def fmt_contract_error(message: str) -> str:
    """The error banner: a blank line, the marker, the message under it.

    The marker line carries the glyph and sits one unit in; the message sits
    under it at two. A refusal used to start at column 0 with no air above
    it and run into whatever printed before, which is the "ragged" the
    maintainer named.
    """

    return f"\n{_INDENT}{MARKER_CONTRACT_ERROR}\n{_indent_block(message)}"


_SCOPE_ID_HINT_INDENT = "    "


def fmt_baseline_scope_id_required(
    *,
    table_state: ToolCodecloneTableState,
    config_path: Path,
    scope_id: UUID,
) -> str:
    """Refuse, then hand over the exact line and the exact place for it.

    The refusal sentence is unchanged and stays first; everything after it is
    the part an operator can act on without reading a guide. ``table_state``
    picks one of three insertions, and each wrong pick damages a real file:
    repeating ``[tool.codeclone]`` in a project that has it makes the TOML
    invalid, and omitting the header in a project that does not have it drops
    the key into whichever table happens to precede it. When the file cannot be
    inspected there is no fourth guess to make -- the sentence goes out alone.
    """

    key_line = HINT_SCOPE_ID_KEY_LINE.format(scope_id=scope_id)
    insertion: tuple[str, ...]
    if table_state == "existing_section":
        lead = HINT_SCOPE_ID_ADD_KEY.format(path=config_path)
        insertion = (key_line,)
    elif table_state == "missing_section":
        lead = HINT_SCOPE_ID_ADD_SECTION.format(path=config_path)
        insertion = (HINT_SCOPE_ID_TABLE_HEADER, key_line)
    elif table_state == "missing_file":
        lead = HINT_SCOPE_ID_CREATE_FILE.format(path=config_path)
        insertion = (HINT_SCOPE_ID_TABLE_HEADER, key_line)
    else:
        return ERR_BASELINE_SCOPE_ID_REQUIRED

    body = [ERR_BASELINE_SCOPE_ID_REQUIRED, "", lead, ""]
    body.extend(f"{_SCOPE_ID_HINT_INDENT}{line}" for line in insertion)
    body.extend(("", HINT_SCOPE_ID_FOOTER))
    return "\n".join(body)


def fmt_memory_db_not_found(*, error: object) -> str:
    return ERR_MEMORY_DB_NOT_FOUND.format(error=error)


def fmt_memory_root_not_found(*, path: object) -> str:
    return ERR_MEMORY_ROOT_NOT_FOUND.format(path=path)


def fmt_baseline_lock_recovery_failed(*, path: Path, reason: str) -> str:
    return ERR_BASELINE_LOCK_RECOVERY_FAILED.format(path=esc(path), reason=esc(reason))


def fmt_baseline_lock_recovered(*, path: Path) -> str:
    return SUCCESS_BASELINE_LOCK_RECOVERED.format(path=path)


def fmt_diagnosed_user_error(error: DiagnosedUserError) -> str:
    """Render a condition CodeClone diagnosed and the user can act on.

    A contract error and not an internal one, because that is what it is:
    the process validated the user's configuration, rejected it by name, and
    the sentence it produced is the whole diagnosis. The internal envelope
    was measured saying "Unexpected exception" over exactly such a sentence,
    then offering a traceback and a bug report for it -- three next steps,
    none of which can help, printed over an answer that already could.

    The remediation block appears only when there is a step; an error with
    nothing to add prints the diagnosis alone rather than a heading over
    nothing. Each step gets its own bullet: the heading says "steps", and a
    diagnosis with two ways out has two of them -- installing into an
    environment the user may not own, and simply not asking for the feature
    -- which are alternatives, not one sentence.

    Refusing an undiagnosed error is deliberate: this frame asserts "not our
    bug, and here is yours to fix", and it may not be put around a fault
    nobody classified.
    """

    if not isinstance(error, DiagnosedUserError):
        raise TypeError(
            "fmt_diagnosed_user_error renders a DiagnosedUserError; "
            f"{type(error).__name__} is not classified as one"
        )
    # ``esc`` and not the raw text: these diagnoses quote the user's own
    # configuration back at them, and the two things they quote most --
    # ``[tool.codeclone]`` and ``codeclone[perf]`` -- are exactly what Rich
    # reads as a style tag and swallows. The one message whose job is to
    # name the wrong key may not be the message that loses it.
    message = esc(str(error).strip()) or "<no message>"
    if not error.remediation:
        return fmt_contract_error(message)
    steps = tuple(f"- {esc(step)}" for step in error.remediation)
    return fmt_contract_error("\n".join((message, "", "Next steps:", *steps)))


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
    if debug:
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
    body = esc("\n".join(lines))
    return f"\n{_INDENT}{MARKER_INTERNAL_ERROR}\n{_indent_block(body)}"
