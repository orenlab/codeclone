# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Mechanical validator for the CLI design code.

Every human-facing CLI string must pass these rules. The catalog below
renders every ``fmt_*`` formatter with pinned inputs; the rule tests walk
the catalog plus the message-constant modules plus the real argparse
trees. A future message added off the design grid fails here, not in
review.

Rules enforced:

* completeness — every public ``fmt_*`` formatter is exercised by the catalog
* hygiene — no trailing whitespace, no tab characters
* grid — leading indentation is a multiple of the 2-space unit
* anatomy — error messages carry an executable next step
* vocabulary — markup tags come from the design-code style map only
* ownership — chromatic color words appear only in the design module
* honesty — bracketed payload data survives markup rendering unmodified
* numbers — counts use thousands separators; singular/plural agree
* NO_COLOR — the catalog renders without a single ANSI escape byte
* help — every argparse action in every command tree documents itself
* casing — ALL-CAPS is reserved for verdict markers and domain acronyms
"""

from __future__ import annotations

import argparse
import io
import re
from pathlib import Path

import pytest

from codeclone import ui_messages as ui
from codeclone.ui_messages import styling

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DESIGN_MODULE = _REPO_ROOT / "codeclone" / "ui_messages" / "styling.py"

# ---------------------------------------------------------------------------
# The pinned catalog: every fmt_* formatter rendered with representative
# inputs. Adding a formatter without a catalog entry fails
# test_catalog_covers_every_formatter.
# ---------------------------------------------------------------------------

_PINNED_PATH = Path("/tmp/project/report.json")
_PINNED_ERROR = OSError("[Errno 2] No such file or directory: '/tmp/x.xml'")


def _build_catalog() -> dict[str, str]:
    entries: dict[str, str] = {
        "fmt_invalid_output_extension": ui.fmt_invalid_output_extension(
            label="JSON", path=_PINNED_PATH, expected_suffix=".json"
        ),
        "fmt_invalid_output_path": ui.fmt_invalid_output_path(
            label="JSON", path=_PINNED_PATH, error="permission denied"
        ),
        "fmt_invalid_baseline_path": ui.fmt_invalid_baseline_path(
            path=_PINNED_PATH, error="not a file"
        ),
        "fmt_baseline_write_failed": ui.fmt_baseline_write_failed(
            path=_PINNED_PATH, error="disk full"
        ),
        "fmt_invalid_baseline_scope_id": ui.fmt_invalid_baseline_scope_id(
            path=_PINNED_PATH, error="not a UUID"
        ),
        "fmt_report_write_failed": ui.fmt_report_write_failed(
            label="HTML", path=_PINNED_PATH, error="disk full"
        ),
        "fmt_html_report_open_failed": ui.fmt_html_report_open_failed(
            path=_PINNED_PATH, error="no browser"
        ),
        "fmt_coverage_join_ignored": ui.fmt_coverage_join_ignored(
            f"Invalid Cobertura XML at /tmp/x.xml: {_PINNED_ERROR}"
        ),
        "fmt_unreadable_source_in_gating": ui.fmt_unreadable_source_in_gating(count=3),
        "fmt_processing_changed": ui.fmt_processing_changed(42),
        "fmt_worker_failed": ui.fmt_worker_failed("worker crashed"),
        "fmt_batch_item_failed": ui.fmt_batch_item_failed("bad item"),
        "fmt_parallel_fallback": ui.fmt_parallel_fallback("no semaphore"),
        "fmt_failed_files_header": ui.fmt_failed_files_header(2),
        "fmt_unsupported_construct_summary": ui.fmt_unsupported_construct_summary(
            count=2,
            constructs=["unsupported fields on Import: is_lazy"],
        ),
        "fmt_cache_save_failed": ui.fmt_cache_save_failed("read-only fs"),
        "fmt_vscode_extension_tip": ui.fmt_vscode_extension_tip(
            url="https://example.invalid/ext"
        ),
        "fmt_gitignore_codeclone_cache_tip": ui.fmt_gitignore_codeclone_cache_tip(
            message="Cache directory is not ignored by git.",
            entry=".codeclone/",
        ),
        "fmt_dead_code_reachability_migration_note": (
            ui.fmt_dead_code_reachability_migration_note(target_version="2.0.2")
        ),
        "fmt_cohesion_lcom4_migration_note": ui.fmt_cohesion_lcom4_migration_note(),
        "fmt_legacy_cache_warning": ui.fmt_legacy_cache_warning(
            legacy_path=_PINNED_PATH, new_path=_PINNED_PATH
        ),
        "fmt_legacy_repo_workspace_warning": ui.fmt_legacy_repo_workspace_warning(
            legacy_dir=_PINNED_PATH, new_dir=_PINNED_PATH
        ),
        "fmt_invalid_baseline": ui.fmt_invalid_baseline("bad JSON"),
        "fmt_baseline_foreign_interpreter": ui.fmt_baseline_foreign_interpreter(
            baseline_tag="cp313", runtime_tag="cp314"
        ),
        "fmt_baseline_lanes_opaque": ui.fmt_baseline_lanes_opaque(
            ["clones:schema_mismatch"]
        ),
        "fmt_baseline_gating_requires_trusted": (
            ui.fmt_baseline_gating_requires_trusted(ci=True)
        ),
        "fmt_cli_runtime_warning": ui.fmt_cli_runtime_warning(
            ui.fmt_coverage_join_ignored(
                f"Invalid Cobertura XML at /tmp/x.xml: {_PINNED_ERROR}"
            )
        ),
        "fmt_path": ui.fmt_path("Report: {path}", _PINNED_PATH),
        "fmt_summary_compact": ui.fmt_summary_compact(
            found=978, analyzed=978, cache_hits=0, skipped=0
        ),
        "fmt_summary_compact_clones": ui.fmt_summary_compact_clones(
            function=1, block=2, segment=3, suppressed=4, fixture_excluded=5, new=6
        ),
        "fmt_summary_compact_metrics": ui.fmt_summary_compact_metrics(
            cc_avg=2.2,
            cc_max=34,
            cbo_avg=1.4,
            cbo_max=27,
            lcom_avg=1.1,
            lcom_max=3,
            cycles=0,
            import_cycles=0,
            deferred_cycles=0,
            dead=0,
            health=92,
            grade="A",
            overloaded_modules=55,
        ),
        "fmt_summary_compact_dependencies": ui.fmt_summary_compact_dependencies(
            avg_depth=7.6, p95_depth=25, max_depth=31
        ),
        "fmt_summary_compact_security_surfaces": (
            ui.fmt_summary_compact_security_surfaces(
                items=349, categories=8, production=150, tests=190
            )
        ),
        "fmt_summary_compact_adoption": ui.fmt_summary_compact_adoption(
            param_permille=998,
            return_permille=997,
            docstring_permille=153,
            any_annotation_count=67,
        ),
        "fmt_summary_compact_api_surface": ui.fmt_summary_compact_api_surface(
            public_symbols=9340,
            modules=842,
            added=488,
            breaking=22,
            diff_available=True,
        ),
        "fmt_summary_compact_api_surface_unavailable": (
            ui.fmt_summary_compact_api_surface(
                public_symbols=9340,
                modules=842,
                added=0,
                breaking=0,
                diff_available=False,
            )
        ),
        "fmt_summary_compact_coverage_join": ui.fmt_summary_compact_coverage_join(
            status="ok",
            overall_permille=875,
            coverage_hotspots=4,
            scope_gap_hotspots=1,
            threshold_percent=50,
            source_label="coverage.xml",
        ),
        "fmt_summary_files": ui.fmt_summary_files(
            found=12345, analyzed=12000, cached=345, skipped=0
        ),
        "fmt_summary_parsed": ui.fmt_summary_parsed(
            lines=319069, functions=11258, methods=1, classes=935
        )
        or "",
        "fmt_summary_parsed_singular": ui.fmt_summary_parsed(
            lines=1, functions=1, methods=0, classes=1
        )
        or "",
        "fmt_summary_clones": ui.fmt_summary_clones(
            func=1200, block=2, segment=3, suppressed=23, fixture_excluded=13, new=1
        ),
        "fmt_metrics_health": ui.fmt_metrics_health(92, "A"),
        "fmt_metrics_cc": ui.fmt_metrics_cc(2.2, 34, 6),
        "fmt_metrics_coupling": ui.fmt_metrics_coupling(1.4, 27),
        "fmt_metrics_cohesion": ui.fmt_metrics_cohesion(1.1, 3),
        "fmt_metrics_cycles": ui.fmt_metrics_cycles(0, import_cycles=0, deferred=0),
        "fmt_metrics_cycles_detected": ui.fmt_metrics_cycles(
            2, import_cycles=1, deferred=1
        ),
        "fmt_metrics_cycles_deferred_only": ui.fmt_metrics_cycles(
            2, import_cycles=0, deferred=2
        ),
        "fmt_metrics_dependencies": ui.fmt_metrics_dependencies(
            avg_depth=7.6, p95_depth=25, max_depth=31
        ),
        "fmt_metrics_security_surfaces": ui.fmt_metrics_security_surfaces(
            items=1349, categories=8, production=1150, tests=199
        ),
        "fmt_metrics_dead_code": ui.fmt_metrics_dead_code(0, suppressed=2),
        "fmt_metrics_dead_code_found": ui.fmt_metrics_dead_code(3),
        "fmt_metrics_adoption": ui.fmt_metrics_adoption(
            param_permille=998,
            return_permille=997,
            docstring_permille=153,
            any_annotation_count=67,
        ),
        "fmt_metrics_api_surface": ui.fmt_metrics_api_surface(
            public_symbols=9340,
            modules=842,
            added=488,
            breaking=22,
            diff_available=True,
        ),
        "fmt_metrics_api_surface_unavailable": ui.fmt_metrics_api_surface(
            public_symbols=9340,
            modules=842,
            added=0,
            breaking=0,
            diff_available=False,
        ),
        "fmt_metrics_coverage_join": ui.fmt_metrics_coverage_join(
            status="ok",
            overall_permille=875,
            coverage_hotspots=4,
            scope_gap_hotspots=1,
            threshold_percent=50,
            source_label="coverage.xml",
        ),
        "fmt_metrics_coverage_join_unavailable": ui.fmt_metrics_coverage_join(
            status="invalid",
            overall_permille=0,
            coverage_hotspots=0,
            scope_gap_hotspots=0,
            threshold_percent=0,
            source_label="coverage.xml",
        ),
        "fmt_metrics_overloaded_modules": ui.fmt_metrics_overloaded_modules(
            candidates=55,
            total=978,
            population_status="ok",
            top_score=1.0,
        ),
        "fmt_changed_scope_paths": ui.fmt_changed_scope_paths(count=4),
        "fmt_changed_scope_findings": ui.fmt_changed_scope_findings(
            total=5, new=1, known=4
        ),
        "fmt_changed_scope_compact": ui.fmt_changed_scope_compact(
            paths=4, findings=5, new=1, known=4
        ),
        "fmt_blast_radius_compact": ui.fmt_blast_radius_compact(
            level="medium", dependents=3, cohorts=0, cycles=0, do_not_touch=3
        ),
        "fmt_patch_verify_compact": ui.fmt_patch_verify_compact(
            status="accepted",
            health_before=81,
            health_after=92,
            regressions=0,
            gate_status="pass",
        ),
        "fmt_pipeline_done": ui.fmt_pipeline_done(12.72),
        "fmt_contract_error": ui.fmt_contract_error(
            ui.ERR_ROOT_NOT_FOUND.format(path="/tmp/project/missing")
        ),
        "fmt_baseline_lock_recovery_failed": ui.fmt_baseline_lock_recovery_failed(
            path=_PINNED_PATH, reason="foreign host"
        ),
        "fmt_baseline_lock_recovered": ui.fmt_baseline_lock_recovered(
            path=_PINNED_PATH
        ),
        "fmt_internal_error": ui.fmt_internal_error(ValueError("boom")),
        "version_output": ui.version_output("2.1.0"),
        "banner_title": ui.banner_title("2.1.0"),
        "fmt_memory_db_not_found": ui.fmt_memory_db_not_found(
            error="/tmp/project/.codeclone/memory/engineering_memory.sqlite3"
        ),
        "fmt_memory_root_not_found": ui.fmt_memory_root_not_found(
            path="/tmp/project/missing"
        ),
        "fmt_bool": ui.fmt_bool(True) + " " + ui.fmt_bool(False),
        "fmt_audit_no_data": ui.AUDIT_ERR_NO_DATA,
        "fmt_audit_not_enabled": ui.AUDIT_NOT_ENABLED,
    }
    return entries


_CATALOG = _build_catalog()

# Formatters that are exercised under a different catalog key, keyed by the
# extra entry name they appear under.
_ALIASED_ENTRIES = {
    "fmt_summary_parsed_singular",
    "fmt_metrics_cycles_detected",
    "fmt_metrics_cycles_deferred_only",
    "fmt_metrics_dead_code_found",
    "fmt_metrics_coverage_join_unavailable",
    "fmt_audit_no_data",
    "fmt_audit_not_enabled",
    "fmt_bool",
    "fmt_memory_db_not_found",
}

# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------


def test_catalog_covers_every_formatter() -> None:
    exported_formatters = sorted(
        name
        for name in dir(ui)
        if name.startswith("fmt_") and callable(getattr(ui, name))
    )
    missing = [name for name in exported_formatters if name not in _CATALOG]
    assert missing == [], (
        "Formatter(s) missing from the design-system catalog; add pinned "
        f"entries for: {missing}"
    )


# ---------------------------------------------------------------------------
# Hygiene: trailing whitespace, tabs, indent grid
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(_CATALOG))
def test_no_trailing_whitespace_or_tabs(name: str) -> None:
    rendered = _CATALOG[name]
    for line in rendered.splitlines():
        assert line == line.rstrip(), f"{name}: trailing whitespace in {line!r}"
        assert "\t" not in line, f"{name}: tab character in {line!r}"


@pytest.mark.parametrize("name", sorted(_CATALOG))
def test_indent_is_on_the_grid(name: str) -> None:
    for line in _CATALOG[name].splitlines():
        stripped = styling.strip_markup(line)
        indent = len(stripped) - len(stripped.lstrip(" "))
        assert indent % styling.INDENT_UNIT == 0, (
            f"{name}: indent {indent} is off the {styling.INDENT_UNIT}-space "
            f"grid in {line!r}"
        )


# ---------------------------------------------------------------------------
# Anatomy: errors carry an executable next step
# ---------------------------------------------------------------------------

_NEXT_STEP_RE = re.compile(
    r"--[a-z][a-z-]+"  # a flag the user can pass
    r"|codeclone[ .]"  # a runnable command
    r"|\[tool\.codeclone"  # a pyproject config key
    r"|\[\[tool\.codeclone"  # a pyproject registry entry
    r"|CODECLONE_[A-Z_]+"  # an environment variable
    r"|Run: "  # an explicit command line
    r"|open an issue"  # the internal-error escalation path
    r"|\{flag\}"  # a template slot the formatter fills with a real flag
)

# Warning-class formatters: the run continues, output is advisory, and the
# in-band next-step law binds errors, not degraded-state warnings.
_WARNING_CLASS_ENTRIES = frozenset(
    {
        "fmt_worker_failed",
        "fmt_batch_item_failed",
        "fmt_cache_save_failed",
        "fmt_failed_files_header",
        "fmt_html_report_open_failed",
        "fmt_unsupported_construct_summary",
    }
)

_ERROR_CATALOG_ENTRIES = sorted(
    name
    for name in _CATALOG
    if name not in _WARNING_CLASS_ENTRIES
    and (
        "invalid" in name
        or "failed" in name
        or "error" in name
        or "not_found" in name
        or "no_data" in name
        or "not_enabled" in name
        or "requires" in name
        or "unreadable" in name
    )
)


@pytest.mark.parametrize("name", _ERROR_CATALOG_ENTRIES)
def test_error_messages_carry_next_step(name: str) -> None:
    rendered = _CATALOG[name]
    assert _NEXT_STEP_RE.search(rendered), (
        f"{name}: error message has no executable next step "
        f"(flag, command, config key, or env var): {rendered!r}"
    )


def _module_string_constants(module: object, *, prefix: str) -> list[tuple[str, str]]:
    """Public string constants of a message module, filtered by name prefix."""

    pairs: list[tuple[str, str]] = []
    for name in dir(module):
        if name.startswith("_") or not name.startswith(prefix):
            continue
        value = getattr(module, name)
        if isinstance(value, str):
            pairs.append((name, value))
    return pairs


def test_error_constants_carry_next_step() -> None:
    from codeclone.ui_messages import controller, runtime

    violations = [
        f"{module.__name__}.{const_name}"
        for module in (runtime, controller)
        for const_name, value in _module_string_constants(module, prefix="ERR_")
        if not _NEXT_STEP_RE.search(value)
    ]
    assert violations == [], (
        "Error constants without an executable next step (flag, command, "
        f"config key, or env var): {violations}"
    )


# ---------------------------------------------------------------------------
# Vocabulary: markup tags come from the design map only
# ---------------------------------------------------------------------------

_TAG_CANDIDATE_RE = re.compile(r"\[/?([a-zA-Z][a-zA-Z0-9_ .#-]*)\]")


@pytest.mark.parametrize("name", sorted(_CATALOG))
def test_markup_tags_come_from_the_design_map(name: str) -> None:
    rendered = _CATALOG[name]
    for match in _TAG_CANDIDATE_RE.finditer(rendered):
        preceding = rendered[: match.start()]
        if preceding.endswith("\\"):
            continue  # escaped literal bracket: payload data, not a tag
        tag = match.group(1)
        assert tag in styling.MARKUP_STYLES or _is_payload_bracket(tag), (
            f"{name}: markup tag [{tag}] is not in the design-code style map"
        )


def _is_payload_bracket(tag: str) -> bool:
    """Bracketed payload data (never a style): contains digits or uppercase."""

    return any(ch.isdigit() or ch.isupper() for ch in tag)


# ---------------------------------------------------------------------------
# Ownership: chromatic color words only in the design module
# ---------------------------------------------------------------------------

_CHROMATIC_RE = re.compile(
    r"[\"'\[](?:bold )?(?:red|green|yellow|cyan|magenta|blue|white)\b"
)


def test_chromatic_color_literals_live_only_in_the_design_module() -> None:
    surfaces = sorted(
        (_REPO_ROOT / "codeclone" / "surfaces" / "cli").rglob("*.py")
    ) + sorted((_REPO_ROOT / "codeclone" / "ui_messages").glob("*.py"))
    violations: list[str] = []
    for path in surfaces:
        if path == _DESIGN_MODULE:
            continue
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            code = line.split("#", 1)[0]
            if _CHROMATIC_RE.search(code):
                rel = path.relative_to(_REPO_ROOT)
                violations.append(f"{rel}:{line_no}: {line.strip()}")
    assert violations == [], (
        "Chromatic color literals outside the design module (use the "
        "semantic STYLE_* constants from ui_messages.styling): " + "\n".join(violations)
    )


def test_no_raw_ansi_escapes_in_cli_sources() -> None:
    surfaces = sorted(
        (_REPO_ROOT / "codeclone" / "surfaces" / "cli").rglob("*.py")
    ) + sorted((_REPO_ROOT / "codeclone" / "ui_messages").glob("*.py"))
    violations = [
        str(path.relative_to(_REPO_ROOT))
        for path in surfaces
        if "\\x1b[" in path.read_text(encoding="utf-8")
    ]
    assert violations == []


# ---------------------------------------------------------------------------
# Honesty: bracketed payload data survives rendering
# ---------------------------------------------------------------------------


def _render_rich(text: str, *, no_color: bool) -> str:
    from codeclone.surfaces.cli.console import make_console

    console = make_console(no_color=no_color, width=200)
    with console.capture() as capture:
        console.print(text)
    return capture.get()


def test_errno_brackets_survive_the_runtime_warning_pipeline() -> None:
    warning = ui.fmt_cli_runtime_warning(
        ui.fmt_coverage_join_ignored(
            f"Invalid Cobertura XML at /tmp/x.xml: {_PINNED_ERROR}"
        )
    )
    rendered = _render_rich(warning, no_color=True)
    assert "[Errno 2]" in rendered, (
        f"the [Errno 2] detail was eaten by markup handling: {rendered!r}"
    )


def test_severity_brackets_survive_blast_radius_entries() -> None:
    from typing import cast

    from codeclone.surfaces.cli.blast_radius import _print_entries
    from codeclone.surfaces.cli.console import make_console
    from codeclone.surfaces.cli.types import PrinterLike

    console = make_console(no_color=True, width=200)
    with console.capture() as capture:
        _print_entries(
            console=cast(PrinterLike, console),
            title="Do not touch",
            entries=[
                {
                    "path": "codeclone.baseline.json",
                    "reason": "baseline artifacts require separate changes",
                    "severity": "hard",
                }
            ],
        )
    rendered = capture.get()
    assert "[hard]" in rendered, (
        f"the severity marker was eaten by markup handling: {rendered!r}"
    )


def test_plain_console_strips_tags_but_keeps_payload_brackets() -> None:
    import contextlib

    from codeclone.surfaces.cli.console import make_plain_console

    console = make_plain_console()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        console.print("[warning]Cache[/warning] failed: [Errno 2] denied \\[hard]")
    rendered = buffer.getvalue()
    assert "[warning]" not in rendered
    assert "[Errno 2]" in rendered
    assert "[hard]" in rendered


# ---------------------------------------------------------------------------
# Numbers and plurals
# ---------------------------------------------------------------------------


def test_counts_use_thousands_separators() -> None:
    parsed = _CATALOG["fmt_summary_parsed"]
    assert "319,069" in parsed
    assert "11,259" in parsed, f"callable count lacks separator: {parsed!r}"
    files = _CATALOG["fmt_summary_files"]
    assert "12,345" in files, f"file count lacks separator: {files!r}"
    clones = _CATALOG["fmt_summary_clones"]
    assert "1,200" in clones, f"clone count lacks separator: {clones!r}"
    security = _CATALOG["fmt_metrics_security_surfaces"]
    assert "1,349" in security and "1,150" in security


def test_singular_counts_render_singular_nouns() -> None:
    parsed = _CATALOG["fmt_summary_parsed_singular"]
    assert "1 line" in parsed and "1 lines" not in parsed
    assert "1 callable" in parsed and "1 callables" not in parsed
    assert "1 class" in parsed and "1 classes" not in parsed


# ---------------------------------------------------------------------------
# NO_COLOR discipline
# ---------------------------------------------------------------------------


def test_catalog_renders_without_ansi_bytes_under_no_color() -> None:
    for name in sorted(_CATALOG):
        rendered = _render_rich(_CATALOG[name], no_color=True)
        assert "\x1b" not in rendered, f"{name}: ANSI escape under NO_COLOR"


# ---------------------------------------------------------------------------
# Argparse help discipline: every action documents itself
# ---------------------------------------------------------------------------


def _iter_parser_actions(
    parser: argparse.ArgumentParser, prog: str
) -> list[tuple[str, argparse.Action]]:
    rows: list[tuple[str, argparse.Action]] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            # The one-line summaries shown in the parent's command listing.
            rows.extend(
                (f"{prog} {choice.dest}", choice) for choice in action._choices_actions
            )
            for choice_name, child in action.choices.items():
                rows.extend(_iter_parser_actions(child, f"{prog} {choice_name}"))
            continue
        rows.append((prog, action))
    return rows


def _collect_all_cli_actions() -> list[tuple[str, argparse.Action]]:
    from codeclone.surfaces.cli.analytics import _build_parser as analytics_parser
    from codeclone.surfaces.cli.memory import _build_parser as memory_parser
    from codeclone.surfaces.cli.observability import (
        _build_parser as observability_parser,
    )
    from codeclone.surfaces.cli.setup.main import _build_parser as setup_parser

    rows: list[tuple[str, argparse.Action]] = []
    rows.extend(_iter_parser_actions(memory_parser(), "codeclone memory"))
    rows.extend(_iter_parser_actions(analytics_parser(), "codeclone analytics"))
    rows.extend(_iter_parser_actions(observability_parser(), "codeclone observability"))
    rows.extend(_iter_parser_actions(setup_parser(), "codeclone setup"))
    return rows


def _is_stdlib_owned(action: argparse.Action) -> bool:
    # The stdlib help action text is argparse's own; the flagship main parser
    # overrides it, subcommand trees keep the stdlib default uniformly.
    return isinstance(action, argparse._HelpAction)


def test_every_subcommand_option_documents_itself() -> None:
    violations = [
        f"{prog}: {'/'.join(action.option_strings) or action.dest}"
        for prog, action in _collect_all_cli_actions()
        if not _is_stdlib_owned(action)
        and action.help is None
        and not isinstance(action, argparse._SubParsersAction)
    ]
    assert violations == [], "argparse actions without help text:\n" + "\n".join(
        violations
    )


def test_subcommand_help_text_is_sentence_cased() -> None:
    violations: list[str] = []
    for prog, action in _collect_all_cli_actions():
        if _is_stdlib_owned(action) or not action.help:
            continue
        text = action.help.strip()
        first = text[0]
        if first.isalpha() and not first.isupper():
            violations.append(f"{prog}: {action.dest}: {text!r}")
    assert violations == [], "argparse help text not sentence-cased:\n" + "\n".join(
        violations
    )


def test_subcommand_help_text_ends_with_period() -> None:
    violations: list[str] = []
    for prog, action in _collect_all_cli_actions():
        if _is_stdlib_owned(action) or not action.help:
            continue
        text = action.help.strip()
        if not text.endswith((".", ")")):
            violations.append(f"{prog}: {action.dest}: {text!r}")
    assert violations == [], (
        "argparse help text without terminal punctuation:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Casing: ALL-CAPS is reserved
# ---------------------------------------------------------------------------

_ALLCAPS_RE = re.compile(r"\b[A-Z][A-Z0-9]{2,}\b")

# Verdict markers, domain acronyms, and unit names that may shout.
_ALLCAPS_VOCABULARY = frozenset(
    {
        "ANSI",
        "API",
        "AST",
        "FILE",  # metavar reference in flag help ("If FILE is omitted...")
        "REF",  # metavar reference (GIT_REF)
        "CBO",
        "CC",
        "CI",
        "CLI",
        "CONTRACT",
        "CWD",
        "DEBUG",
        "DETAILS",
        "ERROR",
        "FAILED",
        "FAILURE",
        "GATING",
        "HTML",
        "IDE",
        "INTERNAL",
        "JSON",
        "KNOWN",
        "LCOM4",
        "LOC",
        "MCP",
        "NEW",
        "PID",
        "SARIF",
        "STOP",
        "URL",
        "UTC",
        "UUID",
        "XML",
    }
)


def test_allcaps_is_reserved_for_verdicts_and_acronyms() -> None:
    from codeclone.ui_messages import controller, runtime
    from codeclone.ui_messages import help as help_msgs

    violations = sorted(
        {
            f"{module.__name__}.{const_name}: {token}"
            for module in (runtime, controller, help_msgs)
            for const_name, value in _module_string_constants(module, prefix="")
            for token in _ALLCAPS_RE.findall(value)
            if token not in _ALLCAPS_VOCABULARY
        }
    )
    assert violations == [], (
        "Unexpected ALL-CAPS token(s); extend the message or use sentence "
        "case: " + "\n".join(violations)
    )
