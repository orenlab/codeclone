# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import json
import os
import subprocess
import sys
import webbrowser
from argparse import Namespace
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import codeclone._cli_meta as cli_meta_mod
import codeclone._cli_reports as cli_reports
import codeclone._cli_summary as cli_summary
import codeclone.baseline as baseline_mod
import codeclone.cli as cli
import codeclone.metrics_baseline as metrics_baseline_mod
import codeclone.pipeline as pipeline
from codeclone import __version__
from codeclone import ui_messages as ui
from codeclone._cli_args import build_parser
from codeclone._cli_config import ConfigValidationError
from codeclone.cache import Cache
from codeclone.cli import process_file
from codeclone.contracts import DOCS_URL, ISSUES_URL, REPOSITORY_URL
from codeclone.errors import BaselineValidationError
from codeclone.models import HealthScore, ProjectMetrics
from codeclone.normalize import NormalizationConfig


class _RecordingPrinter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *objects: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(obj) for obj in objects))


def test_process_file_stat_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    _original_stat = os.stat

    def _boom(path: str, *args: object, **kwargs: object) -> os.stat_result:
        if str(path) == str(src):
            raise OSError("nope")
        return _original_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "stat", _boom)
    result = process_file(str(src), str(tmp_path), NormalizationConfig(), 1, 1)
    assert result.success is False
    assert result.error is not None
    assert "Cannot stat file" in result.error


def test_process_file_encoding_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "a.py"
    src.write_bytes(b"\xff\xfe\xff")

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")

    monkeypatch.setattr(Path, "read_text", _boom)
    result = process_file(str(src), str(tmp_path), NormalizationConfig(), 1, 1)
    assert result.success is False
    assert result.error is not None
    assert "Encoding error" in result.error


def test_process_file_read_oserror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise OSError("read denied")

    monkeypatch.setattr(Path, "read_text", _boom)
    result = process_file(str(src), str(tmp_path), NormalizationConfig(), 1, 1)
    assert result.success is False
    assert result.error is not None
    assert "Cannot read file" in result.error


def test_process_file_unexpected_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline, "extract_units_and_stats_from_source", _boom)
    result = process_file(str(src), str(tmp_path), NormalizationConfig(), 1, 1)
    assert result.success is False
    assert result.error is not None
    assert "Unexpected error" in result.error


def test_process_file_success(tmp_path: Path) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    result = process_file(str(src), str(tmp_path), NormalizationConfig(), 1, 1)
    assert result.success is True
    assert result.stat is not None


def test_cli_module_main_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["codeclone", "--help"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0


def test_cli_version_flag_no_side_effects(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class _Boom:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("Side effect detected")

    monkeypatch.setattr(cli, "Cache", _Boom)
    monkeypatch.setattr(cli, "Baseline", _Boom)
    monkeypatch.setattr(sys, "argv", ["codeclone", "--version"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert __version__ in out
    assert "Scanning root" not in out
    assert "Architectural duplication detector" not in out


def test_cli_help_text_consistency(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["codeclone", "--help"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    expected_parts = (
        "usage: codeclone ",
        "[--version]",
        "[-h]",
        "Structural code quality analysis for Python.",
        "Target:",
        "Analysis:",
        "--changed-only",
        "--diff-against GIT_REF",
        "--paths-from-git-diff GIT_REF",
        "Baselines and CI:",
        "Quality gates:",
        "Analysis stages:",
        "Reporting:",
        "Output and UI:",
        "General:",
        "--fail-complexity [CC_MAX]",
        "--fail-coupling [CBO_MAX]",
        "--fail-cohesion [LCOM4_MAX]",
        "--fail-health [SCORE_MIN]",
        "If enabled without a value, uses 20.",
        "If enabled without a value, uses 10.",
        "If enabled without a value, uses 4.",
        "If enabled without a value, uses 60.",
        "<root>/.cache/codeclone/cache.json",
        "Legacy alias for --cache-path",
        "--max-baseline-size-mb MB",
        "--max-cache-size-mb MB",
        "--timestamped-report-paths",
        "--open-html-report",
        "--debug",
        "Equivalent to: --fail-on-new --no-color --quiet.",
        "Exit codes:",
        "0  Success.",
        "2  Contract error:",
        "3  Gating failure:",
        "5  Internal error:",
        f"Repository: {REPOSITORY_URL}",
        f"Issues:     {ISSUES_URL}",
        f"Docs:       {DOCS_URL}",
    )
    for expected in expected_parts:
        assert expected in out
    assert "\x1b[" not in out


def test_report_path_origins_distinguish_bare_and_explicit_flags() -> None:
    assert cli._report_path_origins(
        (
            "--html",
            "--json",
            "out.json",
            "--md=out.md",
            "--sarif",
            "--text",
        )
    ) == {
        "html": "default",
        "json": "explicit",
        "md": "explicit",
        "sarif": "default",
        "text": "default",
    }


def test_report_path_origins_stops_at_double_dash() -> None:
    assert cli._report_path_origins(("--json=out.json", "--", "--html")) == {
        "html": None,
        "json": "explicit",
        "md": None,
        "sarif": None,
        "text": None,
    }


def test_timestamped_report_path_appends_utc_slug() -> None:
    path = Path("/tmp/report.html")
    assert cli._timestamped_report_path(
        path,
        report_generated_at_utc="2026-03-22T21:30:45Z",
    ) == Path("/tmp/report-20260322T213045Z.html")


def test_open_html_report_in_browser_raises_without_handler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "report.html"
    report_path.write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(
        webbrowser,
        "open_new_tab",
        lambda _uri: False,
    )

    with pytest.raises(OSError, match="no browser handler available"):
        cli_reports._open_html_report_in_browser(path=report_path)


def test_open_html_report_in_browser_succeeds_when_handler_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "report.html"
    report_path.write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(webbrowser, "open_new_tab", lambda _uri: True)
    cli_reports._open_html_report_in_browser(path=report_path)


def test_cli_plain_console_status_context() -> None:
    plain = cli._make_plain_console()
    with plain.status("noop"):
        pass


def test_cli_internal_error_marker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "_main_impl", _boom)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 5
    out = capsys.readouterr().out
    assert "INTERNAL ERROR:" in out
    assert "Unexpected exception." in out
    assert "Reason: RuntimeError: boom" in out
    assert "Next steps:" in out
    assert "Re-run with --debug to include a traceback." in out
    assert f"{ISSUES_URL}/new?template=bug_report.yml" in out
    assert "Traceback:" not in out


def test_cli_internal_error_debug_flag_includes_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "_main_impl", _boom)
    monkeypatch.setattr(sys, "argv", ["codeclone", "--debug"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 5
    out = capsys.readouterr().out
    assert "INTERNAL ERROR:" in out
    assert "DEBUG DETAILS" in out
    assert "Traceback:" in out
    assert "Command: codeclone --debug" in out


def test_cli_internal_error_debug_env_includes_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "_main_impl", _boom)
    monkeypatch.setenv("CODECLONE_DEBUG", "1")
    monkeypatch.setattr(sys, "argv", ["codeclone"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 5
    out = capsys.readouterr().out
    assert "INTERNAL ERROR:" in out
    assert "DEBUG DETAILS" in out
    assert "Traceback:" in out


def test_argument_parser_contract_error_marker_for_invalid_args(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_parser(__version__)
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--unknown-flag"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "CONTRACT ERROR:" in err


def test_validate_changed_scope_args_requires_diff_source() -> None:
    cli.console = cli._make_console(no_color=True)
    args = Namespace(
        changed_only=True,
        diff_against=None,
        paths_from_git_diff=None,
    )
    with pytest.raises(SystemExit) as exc:
        cli._validate_changed_scope_args(args=args)
    assert exc.value.code == 2


def test_validate_changed_scope_args_requires_changed_only_for_diff_against() -> None:
    cli.console = cli._make_console(no_color=True)
    args = Namespace(
        changed_only=False,
        diff_against="main",
        paths_from_git_diff=None,
    )
    with pytest.raises(SystemExit) as exc:
        cli._validate_changed_scope_args(args=args)
    assert exc.value.code == 2


def test_validate_changed_scope_args_promotes_paths_from_git_diff() -> None:
    args = Namespace(
        changed_only=False,
        diff_against=None,
        paths_from_git_diff="HEAD~1",
    )
    assert cli._validate_changed_scope_args(args=args) == "HEAD~1"
    assert args.changed_only is True


def test_validate_changed_scope_args_rejects_conflicting_diff_sources() -> None:
    cli.console = cli._make_console(no_color=True)
    args = Namespace(
        changed_only=True,
        diff_against="HEAD~1",
        paths_from_git_diff="HEAD~2",
    )
    with pytest.raises(SystemExit) as exc:
        cli._validate_changed_scope_args(args=args)
    assert exc.value.code == 2


def test_normalize_changed_paths_relativizes_dedupes_and_sorts(tmp_path: Path) -> None:
    root_path = tmp_path.resolve()
    pkg_dir = root_path / "pkg"
    pkg_dir.mkdir()
    first = pkg_dir / "b.py"
    second = pkg_dir / "a.py"
    first.write_text("pass\n", "utf-8")
    second.write_text("pass\n", "utf-8")

    assert cli._normalize_changed_paths(
        root_path=root_path,
        paths=("pkg/b.py", str(second), " pkg/b.py ", ""),
    ) == ("pkg/a.py", "pkg/b.py")


def test_normalize_changed_paths_skips_empty_relative_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root_path = tmp_path.resolve()
    candidate = root_path / "marker.py"
    candidate.write_text("pass\n", encoding="utf-8")
    original_relative_to = Path.relative_to

    def _fake_relative_to(self: Path, *other: str | Path) -> Path:
        if self == candidate:
            return Path("/")
        return original_relative_to(self, *other)

    monkeypatch.setattr(Path, "relative_to", _fake_relative_to)
    assert (
        cli._normalize_changed_paths(root_path=root_path, paths=(str(candidate),)) == ()
    )


def test_normalize_changed_paths_reports_unresolvable_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli.console = cli._make_console(no_color=True)
    root_path = tmp_path.resolve()
    original_resolve = Path.resolve

    def _broken_resolve(self: Path, strict: bool = False) -> Path:
        if self.name == "broken.py":
            raise OSError("boom")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _broken_resolve)
    with pytest.raises(SystemExit) as exc:
        cli._normalize_changed_paths(root_path=root_path, paths=("broken.py",))
    assert exc.value.code == 2


def test_normalize_changed_paths_rejects_outside_root(tmp_path: Path) -> None:
    cli.console = cli._make_console(no_color=True)
    root_path = tmp_path.resolve()
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside"
    outside_dir.mkdir()
    outside_path = outside_dir / "external.py"
    outside_path.write_text("pass\n", "utf-8")

    with pytest.raises(SystemExit) as exc:
        cli._normalize_changed_paths(root_path=root_path, paths=(str(outside_path),))
    assert exc.value.code == 2


def test_git_diff_changed_paths_normalizes_subprocess_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root_path = tmp_path.resolve()
    pkg_dir = root_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "a.py").write_text("pass\n", "utf-8")
    (pkg_dir / "b.py").write_text("pass\n", "utf-8")

    def _run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["git", "diff", "--name-only", "HEAD~1", "--"],
            returncode=0,
            stdout="pkg/b.py\npkg/a.py\n\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _run)
    assert cli._git_diff_changed_paths(root_path=root_path, git_diff_ref="HEAD~1") == (
        "pkg/a.py",
        "pkg/b.py",
    )


def test_git_diff_changed_paths_reports_subprocess_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli.console = cli._make_console(no_color=True)

    def _run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="git diff", timeout=30)

    monkeypatch.setattr(subprocess, "run", _run)
    with pytest.raises(SystemExit) as exc:
        cli._git_diff_changed_paths(root_path=tmp_path.resolve(), git_diff_ref="HEAD~1")
    assert exc.value.code == 2


def test_git_diff_changed_paths_rejects_option_like_ref(tmp_path: Path) -> None:
    cli.console = cli._make_console(no_color=True)
    with pytest.raises(SystemExit) as exc:
        cli._git_diff_changed_paths(
            root_path=tmp_path.resolve(), git_diff_ref="--cached"
        )
    assert exc.value.code == 2


def test_report_path_origins_ignores_unrelated_equals_tokens() -> None:
    assert cli._report_path_origins(("--unknown=value", "--json=out.json")) == {
        "html": None,
        "json": "explicit",
        "md": None,
        "sarif": None,
        "text": None,
    }


def test_changed_clone_gate_from_report_filters_changed_scope() -> None:
    gate = cli._changed_clone_gate_from_report(
        {
            "findings": {
                "groups": {
                    "clones": {
                        "functions": [
                            {
                                "id": "clone:function:new",
                                "family": "clone",
                                "category": "function",
                                "novelty": "new",
                                "items": [{"relative_path": "pkg/dup.py"}],
                            },
                            {
                                "id": "clone:function:known",
                                "family": "clone",
                                "category": "function",
                                "novelty": "known",
                                "items": [{"relative_path": "pkg/other.py"}],
                            },
                        ],
                        "blocks": [
                            {
                                "id": "clone:block:known",
                                "family": "clone",
                                "category": "block",
                                "novelty": "known",
                                "items": [{"relative_path": "pkg/dup.py"}],
                            }
                        ],
                        "segments": [],
                    },
                    "structural": {
                        "groups": [
                            {
                                "id": "structural:changed",
                                "family": "structural",
                                "novelty": "new",
                                "items": [{"relative_path": "pkg/dup.py"}],
                            }
                        ]
                    },
                    "dead_code": {"groups": []},
                    "design": {"groups": []},
                }
            }
        },
        changed_paths=("pkg/dup.py",),
    )
    assert gate.changed_paths == ("pkg/dup.py",)
    assert gate.total_clone_groups == 2
    assert gate.new_func == frozenset({"clone:function:new"})
    assert gate.new_block == frozenset()
    assert gate.findings_total == 3
    assert gate.findings_new == 2
    assert gate.findings_known == 1


def test_run_analysis_stages_requires_rich_console_when_progress_ui_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cli.console = cli._make_plain_console()
    monkeypatch.setattr(
        cli,
        "discover",
        lambda **_kwargs: SimpleNamespace(
            skipped_warnings=(), files_to_process=("x.py",)
        ),
    )

    with pytest.raises(RuntimeError, match="Rich console is required"):
        cli._run_analysis_stages(
            args=Namespace(quiet=False, no_progress=False),
            boot=cast(Any, object()),
            cache=Cache(tmp_path / "cache.json"),
        )


def test_run_analysis_stages_prints_source_read_failures_when_failed_files_are_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cli.console = cli._make_plain_console()
    printed: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        cli,
        "_print_failed_files",
        lambda failures: printed.append(tuple(failures)),
    )
    monkeypatch.setattr(
        cli,
        "discover",
        lambda **_kwargs: SimpleNamespace(skipped_warnings=(), files_to_process=()),
    )
    monkeypatch.setattr(
        cli,
        "process",
        lambda **_kwargs: SimpleNamespace(
            failed_files=(),
            source_read_failures=("pkg/mod.py: unreadable",),
        ),
    )
    monkeypatch.setattr(cli, "analyze", lambda **_kwargs: SimpleNamespace())
    monkeypatch.setattr(
        cli,
        "_cache_update_segment_projection",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(Cache, "save", lambda self: None)

    cli._run_analysis_stages(
        args=Namespace(quiet=False, no_progress=True),
        boot=cast(Any, object()),
        cache=Cache(tmp_path / "cache.json"),
    )

    assert printed == [(), ("pkg/mod.py: unreadable",)]


def test_enforce_gating_rewrites_clone_threshold_for_changed_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli.console = cli._make_console(no_color=True)
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        cli,
        "gate",
        lambda **_kwargs: pipeline.GatingResult(
            exit_code=3,
            reasons=("clone:threshold:8:1",),
        ),
    )
    monkeypatch.setattr(
        cli,
        "_print_gating_failure_block",
        lambda *, code, entries, args: observed.update(
            {"code": code, "entries": tuple(entries), "threshold": args.fail_threshold}
        ),
    )

    with pytest.raises(SystemExit) as exc:
        cli._enforce_gating(
            args=Namespace(fail_threshold=1, verbose=False),
            boot=cast("pipeline.BootstrapResult", object()),
            analysis=cast("pipeline.AnalysisResult", object()),
            processing=cast(Any, Namespace(source_read_failures=[])),
            source_read_contract_failure=False,
            baseline_failure_code=None,
            metrics_baseline_failure_code=None,
            new_func=set(),
            new_block=set(),
            metrics_diff=None,
            html_report_path=None,
            clone_threshold_total=2,
        )

    assert exc.value.code == 3
    assert observed["code"] == "threshold"
    assert observed["entries"] == (
        ("clone_groups_total", 2),
        ("clone_groups_limit", 1),
    )


def test_enforce_gating_drops_rewritten_threshold_when_changed_scope_is_within_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli.console = cli._make_console(no_color=True)
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        cli,
        "gate",
        lambda **_kwargs: pipeline.GatingResult(
            exit_code=3,
            reasons=("clone:threshold:8:1",),
        ),
    )
    monkeypatch.setattr(
        cli,
        "_print_gating_failure_block",
        lambda **kwargs: observed.update(kwargs),
    )

    cli._enforce_gating(
        args=Namespace(fail_threshold=5, verbose=False),
        boot=cast("pipeline.BootstrapResult", object()),
        analysis=cast("pipeline.AnalysisResult", object()),
        processing=cast(Any, Namespace(source_read_failures=[])),
        source_read_contract_failure=False,
        baseline_failure_code=None,
        metrics_baseline_failure_code=None,
        new_func=set(),
        new_block=set(),
        metrics_diff=None,
        html_report_path=None,
        clone_threshold_total=2,
    )

    assert observed == {}


def test_main_impl_prints_changed_scope_when_changed_projection_is_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "baseline.json"
    metrics_path = tmp_path / "metrics.json"
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codeclone",
            str(tmp_path),
            "--quiet",
            "--changed-only",
            "--diff-against",
            "HEAD~1",
            "--baseline",
            str(baseline_path),
            "--metrics-baseline",
            str(metrics_path),
            "--cache-path",
            str(cache_path),
        ],
    )
    observed: dict[str, object] = {}

    monkeypatch.setattr(cli, "load_pyproject_config", lambda _root: {})
    monkeypatch.setattr(
        cli,
        "apply_pyproject_config_overrides",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        cli,
        "_git_diff_changed_paths",
        lambda **_kwargs: ("pkg/dup.py",),
    )
    monkeypatch.setattr(cli, "_validate_report_ui_flags", lambda **_kwargs: None)
    monkeypatch.setattr(cli, "bootstrap", lambda **_kwargs: cast(Any, object()))
    monkeypatch.setattr(
        cli,
        "_run_analysis_stages",
        lambda **_kwargs: (
            SimpleNamespace(files_found=1, cache_hits=0),
            SimpleNamespace(
                files_analyzed=1,
                files_skipped=0,
                analyzed_lines=10,
                analyzed_functions=1,
                analyzed_methods=0,
                analyzed_classes=0,
                source_read_failures=(),
            ),
            SimpleNamespace(
                func_groups={},
                block_groups={},
                func_clones_count=0,
                block_clones_count=0,
                segment_clones_count=0,
                suppressed_segment_groups=0,
                project_metrics=None,
            ),
        ),
    )
    monkeypatch.setattr(
        cli,
        "_resolve_clone_baseline_state",
        lambda **_kwargs: SimpleNamespace(
            baseline=baseline_mod.Baseline(baseline_path),
            loaded=False,
            status=baseline_mod.BaselineStatus.MISSING,
            trusted_for_diff=False,
            updated_path=None,
            failure_code=None,
        ),
    )
    monkeypatch.setattr(
        cli,
        "_resolve_metrics_baseline_state",
        lambda **_kwargs: SimpleNamespace(
            baseline=metrics_baseline_mod.MetricsBaseline(metrics_path),
            loaded=False,
            status=metrics_baseline_mod.MetricsBaselineStatus.MISSING,
            trusted_for_diff=False,
            failure_code=None,
        ),
    )
    monkeypatch.setattr(cli_meta_mod, "_build_report_meta", lambda **_kwargs: {})
    monkeypatch.setattr(cli, "_print_summary", lambda **_kwargs: None)
    monkeypatch.setattr(
        cli, "report", lambda **_kwargs: SimpleNamespace(report_document={})
    )
    monkeypatch.setattr(
        cli,
        "_changed_clone_gate_from_report",
        lambda _report, changed_paths: cli.ChangedCloneGate(
            changed_paths=tuple(changed_paths),
            new_func=frozenset(),
            new_block=frozenset(),
            total_clone_groups=0,
            findings_total=3,
            findings_new=1,
            findings_known=2,
        ),
    )
    monkeypatch.setattr(
        cli,
        "_print_changed_scope",
        lambda **kwargs: observed.update(kwargs),
    )
    monkeypatch.setattr(cli, "_write_report_outputs", lambda **_kwargs: None)
    monkeypatch.setattr(cli, "_enforce_gating", lambda **_kwargs: None)

    cli._main_impl()

    changed_scope = cast(Any, observed["changed_scope"])
    assert observed["quiet"] is True
    assert changed_scope.paths_count == 1
    assert changed_scope.findings_total == 3


def test_make_console_caps_width_to_layout_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[object] = []

    class _DummyConsole:
        def __init__(
            self,
            *,
            theme: object,
            no_color: bool,
            width: int | None = None,
        ) -> None:
            self.theme = theme
            self.no_color = no_color
            self.width = 200 if width is None else width
            created.append(self)

    monkeypatch.setattr(
        cli,
        "_make_rich_console",
        lambda *, no_color, width: _DummyConsole(
            theme=object(),
            no_color=no_color,
            width=width,
        ),
    )
    console = cli._make_console(no_color=True)
    assert len(created) == 1
    assert isinstance(console, _DummyConsole)
    assert console.width == ui.CLI_LAYOUT_MAX_WIDTH


def test_banner_title_without_root_returns_single_line() -> None:
    title = ui.banner_title("2.0.0")
    assert "[bold white]CodeClone[/bold white]" in title
    assert "\n" not in title


def test_print_summary_invariant_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    cli_summary._print_summary(
        console=cast("cli_summary._Printer", cli.console),
        quiet=False,
        files_found=1,
        files_analyzed=0,
        cache_hits=0,
        files_skipped=0,
        func_clones_count=0,
        block_clones_count=0,
        segment_clones_count=0,
        suppressed_segment_groups=0,
        new_clones_count=0,
    )
    out = capsys.readouterr().out
    assert "Summary accounting mismatch" in out


def test_compact_summary_labels_use_machine_scannable_keys() -> None:
    assert (
        ui.fmt_summary_compact(found=93, analyzed=1, cache_hits=92, skipped=0)
        == "Summary  found=93  analyzed=1  cached=92  skipped=0"
    )
    assert (
        ui.fmt_summary_compact_metrics(
            cc_avg=2.8,
            cc_max=21,
            cbo_avg=0.6,
            cbo_max=8,
            lcom_avg=1.2,
            lcom_max=4,
            cycles=0,
            dead=1,
            health=85,
            grade="B",
            god_modules=3,
        )
        == "Metrics  cc=2.8/21  cbo=0.6/8  lcom4=1.2/4"
        "  cycles=0  dead_code=1  health=85(B)  god_modules=3"
    )


def test_ui_summary_formatters_cover_optional_branches() -> None:
    assert ui._vn(0) == "[dim]0[/dim]"
    assert ui._vn(1200) == "1,200"

    parsed = ui.fmt_summary_parsed(lines=1200, functions=3, methods=2, classes=1)
    assert parsed is not None
    assert "1,200" in parsed
    assert "[bold cyan]5[/bold cyan] callables" in parsed
    assert "[bold cyan]1[/bold cyan] classes" in parsed

    clones = ui.fmt_summary_clones(
        func=1,
        block=2,
        segment=3,
        suppressed=1,
        new=0,
    )
    assert "[bold yellow]3[/bold yellow] seg" in clones

    assert "5 detected" in ui.fmt_metrics_cycles(5)
    dead_with_suppressed = ui.fmt_metrics_dead_code(447, suppressed=9)
    assert "447 found" in dead_with_suppressed
    assert "(9 suppressed)" in dead_with_suppressed
    assert "✔ clean" in ui.fmt_metrics_dead_code(0, suppressed=0)
    clean_with_suppressed = ui.fmt_metrics_dead_code(0, suppressed=9)
    assert "✔ clean" in clean_with_suppressed
    assert "(9 suppressed)" in clean_with_suppressed
    god_modules = ui.fmt_metrics_god_modules(
        candidates=4,
        total=158,
        population_status="ok",
        top_score=0.98,
    )
    assert all(
        fragment in god_modules
        for fragment in ("4", "max score 0.98", "158 ranked", "(report-only)")
    )
    limited_god_modules = ui.fmt_metrics_god_modules(
        candidates=0,
        total=12,
        population_status="limited",
        top_score=0.0,
    )
    assert "12 ranked" in limited_god_modules
    assert "report-only; limited population" in limited_god_modules
    changed_paths = ui.fmt_changed_scope_paths(count=45)
    assert "45" in changed_paths
    assert "from git diff" in changed_paths
    changed_findings = ui.fmt_changed_scope_findings(total=7, new=2, known=5)
    assert "total" in changed_findings
    assert "new" in changed_findings
    assert "5 known" in changed_findings
    changed_compact = ui.fmt_changed_scope_compact(
        paths=45,
        findings=7,
        new=2,
        known=5,
    )
    assert "Changed" in changed_compact
    assert "paths=45" in changed_compact
    assert "findings=7" in changed_compact


def test_print_changed_scope_uses_dedicated_block(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    cli_summary._print_changed_scope(
        console=cast("cli_summary._Printer", cli.console),
        quiet=False,
        changed_scope=cli_summary.ChangedScopeSnapshot(
            paths_count=45,
            findings_total=7,
            findings_new=2,
            findings_known=5,
        ),
    )
    out = capsys.readouterr().out
    assert "Changed Scope" in out
    assert "Paths" in out
    assert "Findings" in out
    assert "from git diff" in out


def test_print_changed_scope_uses_compact_line_in_quiet_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    cli_summary._print_changed_scope(
        console=cast("cli_summary._Printer", cli.console),
        quiet=True,
        changed_scope=cli_summary.ChangedScopeSnapshot(
            paths_count=45,
            findings_total=7,
            findings_new=2,
            findings_known=5,
        ),
    )
    out = capsys.readouterr().out
    assert "Changed" in out
    assert "paths=45" in out
    assert "findings=7" in out
    assert "new=2" in out
    assert "known=5" in out


def test_print_metrics_in_quiet_mode_includes_god_modules(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    cli_summary._print_metrics(
        console=cast("cli_summary._Printer", cli.console),
        quiet=True,
        metrics=cli_summary.MetricsSnapshot(
            complexity_avg=2.8,
            complexity_max=20,
            high_risk_count=0,
            coupling_avg=0.5,
            coupling_max=9,
            cohesion_avg=1.2,
            cohesion_max=4,
            cycles_count=0,
            dead_code_count=0,
            health_total=85,
            health_grade="B",
            god_modules_candidates=3,
            god_modules_total=158,
            god_modules_population_status="ok",
            god_modules_top_score=0.98,
        ),
    )
    out = capsys.readouterr().out
    assert "god_modules=3" in out


def test_configure_metrics_mode_rejects_skip_metrics_with_metrics_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    args = Namespace(
        skip_metrics=True,
        fail_complexity=10,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=False,
        fail_dead_code=False,
        fail_health=-1,
        fail_on_new_metrics=False,
        update_metrics_baseline=False,
        skip_dead_code=False,
        skip_dependencies=False,
    )
    with pytest.raises(SystemExit) as exc:
        cli._configure_metrics_mode(args=args, metrics_baseline_exists=False)
    assert exc.value.code == 2


def test_configure_metrics_mode_forces_dependency_and_dead_code_when_gated() -> None:
    args = Namespace(
        skip_metrics=False,
        fail_complexity=-1,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=True,
        fail_dead_code=True,
        fail_health=-1,
        fail_on_new_metrics=False,
        update_metrics_baseline=False,
        skip_dead_code=True,
        skip_dependencies=True,
    )
    cli._configure_metrics_mode(args=args, metrics_baseline_exists=True)
    assert args.skip_dead_code is False
    assert args.skip_dependencies is False


def test_probe_metrics_baseline_section_for_non_object_payload(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text("[]", "utf-8")
    probe = cli._probe_metrics_baseline_section(path)
    assert probe.has_metrics_section is True
    assert probe.payload is None


def test_metrics_computed_respects_skip_switches() -> None:
    assert cli._metrics_computed(
        Namespace(
            skip_metrics=False,
            skip_dependencies=True,
            skip_dead_code=True,
        )
    ) == ("complexity", "coupling", "cohesion", "health")
    assert cli._metrics_computed(
        Namespace(
            skip_metrics=False,
            skip_dependencies=False,
            skip_dead_code=False,
        )
    ) == (
        "complexity",
        "coupling",
        "cohesion",
        "health",
        "dependencies",
        "dead_code",
    )


def test_main_impl_exits_on_invalid_pyproject_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    monkeypatch.setattr(sys, "argv", ["codeclone", str(tmp_path)])

    def _raise_invalid_config(_root: Path) -> dict[str, object]:
        raise ConfigValidationError("broken config")

    monkeypatch.setattr(cli, "load_pyproject_config", _raise_invalid_config)
    with pytest.raises(SystemExit) as exc:
        cli._main_impl()
    assert exc.value.code == 2


def test_main_impl_debug_sets_env_and_handles_metrics_baseline_resolve_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    monkeypatch.delenv("CODECLONE_DEBUG", raising=False)
    bad_metrics = tmp_path / "bad_metrics.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codeclone",
            str(tmp_path),
            "--debug",
            "--metrics-baseline",
            str(bad_metrics),
        ],
    )
    monkeypatch.setattr(cli, "load_pyproject_config", lambda _root: {})
    original_resolve = Path.resolve

    def _resolve(self: Path, *, strict: bool = False) -> Path:
        if self == bad_metrics:
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve)
    with pytest.raises(SystemExit) as exc:
        cli._main_impl()
    assert exc.value.code == 2
    assert os.environ.get("CODECLONE_DEBUG") == "1"


def _stub_discovery_result() -> pipeline.DiscoveryResult:
    return pipeline.DiscoveryResult(
        files_found=0,
        cache_hits=0,
        files_skipped=0,
        all_file_paths=(),
        cached_units=(),
        cached_blocks=(),
        cached_segments=(),
        cached_class_metrics=(),
        cached_module_deps=(),
        cached_dead_candidates=(),
        cached_referenced_names=frozenset(),
        files_to_process=(),
        skipped_warnings=(),
    )


def _stub_processing_result() -> pipeline.ProcessingResult:
    return pipeline.ProcessingResult(
        units=(),
        blocks=(),
        segments=(),
        class_metrics=(),
        module_deps=(),
        dead_candidates=(),
        referenced_names=frozenset(),
        files_analyzed=0,
        files_skipped=0,
        analyzed_lines=0,
        analyzed_functions=0,
        analyzed_methods=0,
        analyzed_classes=0,
        failed_files=(),
        source_read_failures=(),
    )


def _stub_analysis_result(
    *,
    project_metrics: ProjectMetrics | None = None,
) -> pipeline.AnalysisResult:
    return pipeline.AnalysisResult(
        func_groups={},
        block_groups={},
        block_groups_report={},
        segment_groups={},
        suppressed_segment_groups=0,
        block_group_facts={},
        func_clones_count=0,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=0,
        project_metrics=project_metrics,
        metrics_payload=None,
        suggestions=(),
        segment_groups_raw_digest="",
    )


def _sample_project_metrics() -> ProjectMetrics:
    return ProjectMetrics(
        complexity_avg=1.0,
        complexity_max=1,
        high_risk_functions=(),
        coupling_avg=1.0,
        coupling_max=1,
        high_risk_classes=(),
        cohesion_avg=1.0,
        cohesion_max=1,
        low_cohesion_classes=(),
        dependency_modules=0,
        dependency_edges=0,
        dependency_edge_list=(),
        dependency_cycles=(),
        dependency_max_depth=0,
        dependency_longest_chains=(),
        dead_code=(),
        health=HealthScore(total=90, grade="A", dimensions={"coverage": 100}),
    )


def _patch_main_pipeline_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_metrics: ProjectMetrics | None = None,
) -> None:
    monkeypatch.setattr(cli, "discover", lambda **_kwargs: _stub_discovery_result())
    monkeypatch.setattr(cli, "process", lambda **_kwargs: _stub_processing_result())
    monkeypatch.setattr(
        cli,
        "analyze",
        lambda **_kwargs: _stub_analysis_result(project_metrics=project_metrics),
    )


def _assert_main_impl_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    *,
    expected_code: int,
    project_metrics: ProjectMetrics | None = None,
    pyproject_config: dict[str, object] | None = None,
    configure_metrics_mode: Callable[..., object] | None = None,
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(
        cli,
        "load_pyproject_config",
        lambda _root: {} if pyproject_config is None else pyproject_config,
    )
    if configure_metrics_mode is not None:
        monkeypatch.setattr(cli, "_configure_metrics_mode", configure_metrics_mode)
    _patch_main_pipeline_stubs(monkeypatch, project_metrics=project_metrics)
    with pytest.raises(SystemExit) as exc:
        cli._main_impl()
    assert exc.value.code == expected_code


def _prepare_fail_on_new_metrics_case(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> list[str]:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text("{}", "utf-8")
    return [
        "codeclone",
        str(tmp_path),
        "--quiet",
        "--baseline",
        str(tmp_path / "baseline.json"),
        "--metrics-baseline",
        str(metrics_path),
        "--fail-on-new-metrics",
    ]


def test_main_impl_rejects_update_metrics_baseline_when_metrics_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline_path = tmp_path / "baseline.json"
    metrics_path = tmp_path / "metrics.json"
    _assert_main_impl_exit_code(
        monkeypatch,
        [
            "codeclone",
            str(tmp_path),
            "--quiet",
            "--skip-metrics",
            "--update-metrics-baseline",
            "--baseline",
            str(baseline_path),
            "--metrics-baseline",
            str(metrics_path),
        ],
        expected_code=2,
    )


def test_main_impl_update_metrics_baseline_requires_project_metrics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline_path = tmp_path / "baseline.json"
    metrics_path = tmp_path / "metrics.json"
    _assert_main_impl_exit_code(
        monkeypatch,
        [
            "codeclone",
            str(tmp_path),
            "--quiet",
            "--update-metrics-baseline",
            "--baseline",
            str(baseline_path),
            "--metrics-baseline",
            str(metrics_path),
        ],
        expected_code=2,
        project_metrics=None,
    )


def test_main_impl_prints_metric_gate_reasons_and_exits_gating_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codeclone",
            str(tmp_path),
            "--quiet",
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--metrics-baseline",
            str(tmp_path / "metrics.json"),
        ],
    )
    monkeypatch.setattr(cli, "load_pyproject_config", lambda _root: {})
    _patch_main_pipeline_stubs(monkeypatch)
    monkeypatch.setattr(
        cli,
        "gate",
        lambda **_kwargs: pipeline.GatingResult(
            exit_code=3,
            reasons=(
                "metric:Health score regressed vs metrics baseline: delta=-1.",
                "metric:Complexity threshold exceeded: max CC=21, threshold=20.",
            ),
        ),
    )
    with pytest.raises(SystemExit) as exc:
        cli._main_impl()
    assert exc.value.code == 3
    out = capsys.readouterr().out
    for needle in (
        "GATING FAILURE [metrics]",
        "policy",
        "complexity_max",
        "health_delta",
    ):
        assert needle in out


def test_main_impl_uses_configured_metrics_baseline_without_cli_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    baseline_path = tmp_path / "baseline.json"
    metrics_path = tmp_path / "metrics.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codeclone",
            str(tmp_path),
            "--quiet",
            "--baseline",
            str(baseline_path),
        ],
    )
    monkeypatch.setattr(
        cli,
        "load_pyproject_config",
        lambda _root: {"metrics_baseline": str(metrics_path)},
    )
    monkeypatch.setattr(
        cli,
        "_probe_metrics_baseline_section",
        lambda _path: pytest.fail("unexpected unified-baseline probe"),
    )
    _patch_main_pipeline_stubs(monkeypatch)
    cli._main_impl()


def test_main_impl_unified_metrics_update_auto_enables_baseline_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    baseline_path = tmp_path / "unified.baseline.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codeclone",
            str(tmp_path),
            "--quiet",
            "--baseline",
            str(baseline_path),
            "--metrics-baseline",
            str(baseline_path),
            "--update-metrics-baseline",
        ],
    )
    monkeypatch.setattr(cli, "load_pyproject_config", lambda _root: {})
    _patch_main_pipeline_stubs(monkeypatch, project_metrics=_sample_project_metrics())
    cli._main_impl()
    payload = json.loads(baseline_path.read_text("utf-8"))
    assert "clones" in payload
    assert "metrics" in payload


def test_main_impl_skip_metrics_defensive_contract_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline_path = tmp_path / "baseline.json"
    metrics_path = tmp_path / "metrics.json"
    _assert_main_impl_exit_code(
        monkeypatch,
        [
            "codeclone",
            str(tmp_path),
            "--quiet",
            "--skip-metrics",
            "--update-metrics-baseline",
            "--baseline",
            str(baseline_path),
            "--metrics-baseline",
            str(metrics_path),
        ],
        expected_code=2,
        configure_metrics_mode=lambda **_kwargs: None,
    )


def test_main_impl_fail_on_new_metrics_requires_existing_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline_path = tmp_path / "baseline.json"
    metrics_path = tmp_path / "missing.metrics.json"
    _assert_main_impl_exit_code(
        monkeypatch,
        [
            "codeclone",
            str(tmp_path),
            "--quiet",
            "--baseline",
            str(baseline_path),
            "--metrics-baseline",
            str(metrics_path),
            "--fail-on-new-metrics",
        ],
        expected_code=2,
    )


def test_main_impl_fail_on_new_metrics_handles_load_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv = _prepare_fail_on_new_metrics_case(monkeypatch, tmp_path)

    def _raise_load(self: object, *, max_size_bytes: int) -> None:
        raise BaselineValidationError("broken metrics baseline", status="invalid_type")

    monkeypatch.setattr(metrics_baseline_mod.MetricsBaseline, "load", _raise_load)
    _assert_main_impl_exit_code(monkeypatch, argv, expected_code=2)


def test_main_impl_fail_on_new_metrics_handles_verify_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv = _prepare_fail_on_new_metrics_case(monkeypatch, tmp_path)

    def _noop_load(self: object, *, max_size_bytes: int) -> None:
        return None

    def _raise_verify(self: object, *, runtime_python_tag: str) -> None:
        raise BaselineValidationError(
            "metrics baseline python tag mismatch",
            status="mismatch_python_version",
        )

    monkeypatch.setattr(metrics_baseline_mod.MetricsBaseline, "load", _noop_load)
    monkeypatch.setattr(
        metrics_baseline_mod.MetricsBaseline,
        "verify_compatibility",
        _raise_verify,
    )
    _assert_main_impl_exit_code(monkeypatch, argv, expected_code=2)


def test_main_impl_update_metrics_baseline_write_error_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    baseline_path = tmp_path / "baseline.json"
    metrics_path = tmp_path / "metrics.json"

    def _raise_save(self: object) -> None:
        raise OSError("readonly fs")

    monkeypatch.setattr(metrics_baseline_mod.MetricsBaseline, "save", _raise_save)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codeclone",
            str(tmp_path),
            "--quiet",
            "--baseline",
            str(baseline_path),
            "--metrics-baseline",
            str(metrics_path),
            "--update-metrics-baseline",
        ],
    )
    monkeypatch.setattr(cli, "load_pyproject_config", lambda _root: {})
    _patch_main_pipeline_stubs(monkeypatch, project_metrics=_sample_project_metrics())
    with pytest.raises(SystemExit) as exc:
        cli._main_impl()
    assert exc.value.code == 2


def test_main_impl_update_metrics_baseline_separate_path_message_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    baseline_path = tmp_path / "baseline.json"
    metrics_path = tmp_path / "metrics.json"
    metrics_baseline_mod.MetricsBaseline.from_project_metrics(
        project_metrics=_sample_project_metrics(),
        path=metrics_path,
    ).save()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codeclone",
            str(tmp_path),
            "--quiet",
            "--baseline",
            str(baseline_path),
            "--metrics-baseline",
            str(metrics_path),
            "--update-metrics-baseline",
        ],
    )
    monkeypatch.setattr(cli, "load_pyproject_config", lambda _root: {})
    _patch_main_pipeline_stubs(monkeypatch, project_metrics=_sample_project_metrics())
    cli._main_impl()
    assert metrics_path.exists()


def test_main_impl_ci_enables_fail_on_new_metrics_when_metrics_baseline_loaded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    baseline_path = tmp_path / "baseline.json"
    metrics_path = tmp_path / "metrics.json"

    baseline_mod.Baseline.from_groups({}, {}, path=baseline_path).save()
    metrics_baseline_mod.MetricsBaseline.from_project_metrics(
        project_metrics=_sample_project_metrics(),
        path=metrics_path,
    ).save()

    observed: dict[str, bool] = {}

    def _capture_gate(**kwargs: object) -> pipeline.GatingResult:
        boot = kwargs["boot"]
        assert isinstance(boot, pipeline.BootstrapResult)
        observed["fail_on_new_metrics"] = bool(boot.args.fail_on_new_metrics)
        return pipeline.GatingResult(exit_code=0, reasons=())

    monkeypatch.setattr(cli, "gate", _capture_gate)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codeclone",
            str(tmp_path),
            "--ci",
            "--baseline",
            str(baseline_path),
            "--metrics-baseline",
            str(metrics_path),
        ],
    )
    monkeypatch.setattr(cli, "load_pyproject_config", lambda _root: {})
    _patch_main_pipeline_stubs(monkeypatch, project_metrics=_sample_project_metrics())
    cli._main_impl()
    assert observed["fail_on_new_metrics"] is True


def test_print_verbose_clone_hashes_noop_on_empty() -> None:
    printer = _RecordingPrinter()
    cli._print_verbose_clone_hashes(
        printer,
        label="Function clone hashes",
        clone_hashes=set(),
    )
    assert printer.lines == []


def test_print_verbose_clone_hashes_prints_sorted_values() -> None:
    printer = _RecordingPrinter()
    cli._print_verbose_clone_hashes(
        printer,
        label="Block clone hashes",
        clone_hashes={"b-hash", "a-hash"},
    )
    assert printer.lines == [
        "\n    Block clone hashes:",
        "      - a-hash",
        "      - b-hash",
    ]
