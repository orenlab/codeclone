import json
import os
import sys
import webbrowser
from argparse import Namespace
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

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
        )
        == "Metrics  cc=2.8/21  cbo=0.6/8  lcom4=1.2/4"
        "  cycles=0  dead_code=1  health=85(B)"
    )


def test_ui_summary_formatters_cover_optional_branches() -> None:
    assert ui._vn(0) == "[dim]0[/dim]"
    assert ui._vn(1200) == "1,200"

    parsed = ui.fmt_summary_parsed(lines=1200, functions=3, methods=2, classes=1)
    assert parsed is not None
    assert "1,200" in parsed
    assert "[bold cyan]3[/bold cyan] functions" in parsed
    assert "[bold cyan]2[/bold cyan] methods" in parsed
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
