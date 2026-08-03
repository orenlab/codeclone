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
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TextIO, cast

import pytest

import codeclone.baseline as baseline_mod
import codeclone.baseline.metrics_baseline as metrics_baseline_mod
import codeclone.core.worker as core_worker
import codeclone.surfaces.cli.attrs as cli_attrs
import codeclone.surfaces.cli.baseline_state as cli_baselines_mod
import codeclone.surfaces.cli.changed_scope as cli_changed_scope
import codeclone.surfaces.cli.console as cli_console
import codeclone.surfaces.cli.post_run as cli_post_run
import codeclone.surfaces.cli.report_meta as cli_meta_mod
import codeclone.surfaces.cli.reports_output as cli_reports
import codeclone.surfaces.cli.runtime as cli_runtime
import codeclone.surfaces.cli.summary as cli_summary
import codeclone.surfaces.cli.tips as cli_tips
import codeclone.surfaces.cli.workflow as cli
from codeclone import __version__
from codeclone import ui_messages as ui
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.cache.store import Cache
from codeclone.config.argparse_builder import build_parser
from codeclone.config.pyproject_loader import ConfigValidationError
from codeclone.contracts import DOCS_URL, ISSUES_URL, REPOSITORY_URL
from codeclone.contracts.errors import BaselineValidationError
from codeclone.core._types import (
    AnalysisResult,
    DiscoveryResult,
    FileProcessResult,
    ProcessingResult,
)
from codeclone.core.reporting import GatingResult, resolve_report_baseline_trust
from codeclone.core.worker import (
    _install_module_registry,
)
from codeclone.core.worker import (
    process_file as _worker_process_file,
)
from codeclone.models import HealthScore, LaneTrust, ProjectMetrics, TrustVector
from tests._assertions import assert_contains_all, assert_contains_none
from tests._ast_metrics_helpers import module_registry_context, worker_registry_context
from tests.test_observation_contract import TEST_OBSERVATION_BUNDLE


def process_file(
    filepath: str,
    root: str,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
) -> FileProcessResult:
    _install_module_registry(worker_registry_context(filepath=filepath, root=root))
    return _worker_process_file(filepath, root, cfg, min_loc, min_stmt)


class _RecordingPrinter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *objects: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(obj) for obj in objects))


@pytest.mark.parametrize(
    ("trusted_lane", "expected_func", "expected_block"),
    [
        ("clones.functions", {"function:new"}, set()),
        ("clones.blocks", set(), {"block:new"}),
    ],
)
def test_diff_context_respects_independent_clone_lane_trust(
    trusted_lane: str,
    expected_func: set[str],
    expected_block: set[str],
    tmp_path: Path,
) -> None:
    baseline = SimpleNamespace(
        diff=lambda _func_groups, _block_groups: (
            {"function:new"},
            {"block:new"},
        )
    )
    baseline_state = SimpleNamespace(trusted_for_diff=True, baseline=baseline)
    metrics_baseline_state = SimpleNamespace(
        trusted_for_diff=False,
        baseline=SimpleNamespace(),
    )
    trust = TrustVector(
        root_verified=True,
        lanes=tuple(
            LaneTrust(
                name=lane,
                status="trusted" if lane == trusted_lane else "unavailable",
                reason="compatible" if lane == trusted_lane else "runtime_lane_unknown",
            )
            for lane in ("clones.blocks", "clones.functions")
        ),
    )

    diff = cli_post_run.build_diff_context(
        analysis=cast(
            Any,
            SimpleNamespace(
                func_groups={},
                block_groups={},
                project_metrics=None,
            ),
        ),
        baseline_path=tmp_path / "baseline.json",
        baseline_state=cast(Any, baseline_state),
        metrics_baseline_state=cast(Any, metrics_baseline_state),
        baseline_trust=trust,
    )

    assert diff.new_func == expected_func
    assert diff.new_block == expected_block


def test_report_baseline_trust_rejects_invalid_scope_id() -> None:
    assert (
        resolve_report_baseline_trust(
            cast(Any, object()),
            baseline_scope_id="not-a-uuid",
        )
        is None
    )


def _baseline_state_args(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "max_baseline_size_mb": 10,
        "update_baseline": False,
        "baseline_scope_id": "018f4b8e-5a5f-7d35-9c21-4af5d18df420",
        "project_label": None,
        "fail_on_new": False,
        "skip_metrics": False,
        "fail_on_new_metrics": False,
        "fail_on_typing_regression": False,
        "fail_on_docstring_regression": False,
        "fail_on_api_break": False,
        "api_surface": False,
        "coverage_xml": None,
        "coverage_min": 0.0,
        "ci": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_baseline_state_recovery_and_invalid_scope_are_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "baseline.json"
    monkeypatch.setattr(
        cli_baselines_mod,
        "recover_publish_lock",
        lambda **_kwargs: None,
    )
    assert (
        cli_baselines_mod.recover_baseline_publish_lock(
            target=target,
            expected_token="token",
            force=False,
        )
        is None
    )

    def _fail_recovery(**_kwargs: object) -> None:
        raise baseline_mod.BaselinePublicationError("foreign_lock", "foreign")

    monkeypatch.setattr(
        cli_baselines_mod,
        "recover_publish_lock",
        _fail_recovery,
    )
    assert (
        cli_baselines_mod.recover_baseline_publish_lock(
            target=target,
            expected_token="token",
            force=False,
        )
        == "foreign"
    )

    printer = _RecordingPrinter()
    assert (
        cli_baselines_mod._required_scope_id(
            args=_baseline_state_args(baseline_scope_id="invalid"),
            baseline_path=target,
            console=printer,
        )
        is None
    )
    assert "baseline_scope_id" in "\n".join(printer.lines)


@pytest.mark.parametrize("console_kind", ["rich", "plain"])
def test_missing_scope_id_error_keeps_config_table_name(
    tmp_path: Path,
    console_kind: str,
) -> None:
    """`[tool.codeclone]` is the only actionable token in this error.

    Both console implementations strip Rich markup tags, so the message must
    reach the user through a non-markup print path.
    """
    console: Any = (
        cli_console.make_console(no_color=True, width=200)
        if console_kind == "rich"
        else cli_console.PlainConsole()
    )
    buffer = StringIO()
    with redirect_stdout(buffer):
        cli_baselines_mod._required_scope_id(
            args=_baseline_state_args(
                baseline_scope_id=None,
                update_baseline=True,
            ),
            baseline_path=tmp_path / "baseline.json",
            console=console,
        )

    printed = buffer.getvalue()
    assert "CONTRACT ERROR:" in printed
    assert "[error]" not in printed
    assert "[tool.codeclone]" in printed


def test_baseline_update_forwards_configured_project_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The resolved config label must reach the publisher, not stop at the CLI."""

    forwarded: dict[str, object] = {}

    def _capture(**kwargs: object) -> None:
        forwarded.update(kwargs)

    monkeypatch.setattr(cli_baselines_mod, "publish_baseline", _capture)
    monkeypatch.setattr(baseline_mod.Baseline, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(
        baseline_mod.Baseline,
        "verify_compatibility",
        lambda *_a, **_k: None,
    )

    cli_baselines_mod.resolve_clone_baseline_state(
        args=_baseline_state_args(
            update_baseline=True,
            project_label="Acme Payments",
        ),
        baseline_path=tmp_path / "baseline.json",
        baseline_exists=False,
        observation_bundle=TEST_OBSERVATION_BUNDLE,
        console=_RecordingPrinter(),
        required_lanes=frozenset(),
    )

    assert forwarded["project_label"] == "Acme Payments"


@pytest.mark.parametrize("fail_on_new", [False, True])
def test_clone_baseline_missing_scope_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_on_new: bool,
) -> None:
    path = tmp_path / "baseline.json"
    path.write_text("{}", "utf-8")
    monkeypatch.setattr(baseline_mod.Baseline, "load", lambda *_args, **_kwargs: None)
    printer = _RecordingPrinter()

    state = cli_baselines_mod.resolve_clone_baseline_state(
        args=_baseline_state_args(
            baseline_scope_id=None,
            fail_on_new=fail_on_new,
        ),
        baseline_path=path,
        baseline_exists=True,
        observation_bundle=TEST_OBSERVATION_BUNDLE,
        console=printer,
        required_lanes=frozenset(),
    )

    assert state.status is baseline_mod.BaselineStatus.MISMATCH_SCOPE_ID
    assert state.trusted_for_diff is False
    assert (state.failure_code is not None) is fail_on_new


@pytest.mark.parametrize("gate_requested", [False, True])
def test_metrics_corruption_preserves_typed_gate_behavior(
    tmp_path: Path,
    *,
    gate_requested: bool,
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("not-json", "utf-8")
    clone_state = cli_baselines_mod.CloneBaselineState(
        baseline=baseline_mod.Baseline(path),
        loaded=True,
        status=baseline_mod.BaselineStatus.OK,
        failure_code=None,
        trusted_for_diff=True,
        updated_path=None,
    )
    printer = _RecordingPrinter()

    state = cli_baselines_mod.resolve_metrics_baseline_state(
        args=_baseline_state_args(fail_on_new_metrics=gate_requested),
        metrics_baseline_path=path,
        metrics_baseline_exists=True,
        clone_baseline_state=clone_state,
        console=printer,
        required_lanes=frozenset(),
    )

    assert state.status is metrics_baseline_mod.MetricsBaselineStatus.INVALID_JSON
    assert (state.failure_code is not None) is gate_requested


def test_skip_metrics_rejects_native_publication(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        cli_baselines_mod.resolve_metrics_baseline_state(
            args=_baseline_state_args(skip_metrics=True, update_baseline=True),
            metrics_baseline_path=tmp_path / "baseline.json",
            metrics_baseline_exists=False,
            clone_baseline_state=cli_baselines_mod.CloneBaselineState(
                baseline=baseline_mod.Baseline(tmp_path / "baseline.json"),
                loaded=False,
                status=baseline_mod.BaselineStatus.MISSING,
                failure_code=None,
                trusted_for_diff=False,
                updated_path=None,
            ),
            console=_RecordingPrinter(),
            required_lanes=frozenset(),
        )


class _TTYStream(StringIO):
    def __init__(self, *, is_tty: bool) -> None:
        super().__init__()
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def _metrics_baseline_runtime_for_gate_checks() -> (
    cli_baselines_mod._MetricsBaselineRuntime
):
    runtime = cli_baselines_mod._MetricsBaselineRuntime(
        baseline=metrics_baseline_mod.MetricsBaseline("metrics.json")
    )
    runtime.loaded = True
    runtime.trusted_for_diff = True
    return runtime


def _assert_metrics_gate_schema_contract_error(
    runtime: cli_baselines_mod._MetricsBaselineRuntime,
    printer: _RecordingPrinter,
    *,
    expected_fragment: str,
) -> None:
    assert runtime.loaded is False
    assert runtime.trusted_for_diff is False
    assert (
        runtime.status
        == metrics_baseline_mod.MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION
    )
    assert runtime.failure_code == cli.ExitCode.CONTRACT_ERROR
    assert any(expected_fragment in line for line in printer.lines)


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
    src.write_text("def f():\n    return 1\n", "utf-8")
    read_calls = 0

    def _invalid_bytes(_path: Path) -> bytes:
        nonlocal read_calls
        read_calls += 1
        return b"\xff\xfe\xff"

    monkeypatch.setattr(Path, "read_bytes", _invalid_bytes)
    result = process_file(str(src), str(tmp_path), NormalizationConfig(), 1, 1)
    assert result.success is False
    assert result.error is not None
    assert "Encoding error" in result.error
    assert read_calls == 1


def test_process_file_read_oserror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    read_calls = 0

    def _boom(_path: Path) -> bytes:
        nonlocal read_calls
        read_calls += 1
        raise OSError("read denied")

    monkeypatch.setattr(Path, "read_bytes", _boom)
    result = process_file(str(src), str(tmp_path), NormalizationConfig(), 1, 1)
    assert result.success is False
    assert result.error is not None
    assert "Cannot read file" in result.error
    assert read_calls == 1


def test_process_file_unexpected_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(core_worker, "extract_units_and_stats_from_source", _boom)
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


def test_cli_attr_helpers_handle_bool_int_and_path_edges(tmp_path: Path) -> None:
    args = SimpleNamespace(
        flag="yes",
        numeric=True,
        broken=3.14,
        path_value=tmp_path / "report.json",
        invalid_text=123,
    )

    assert cli_attrs.bool_attr(args, "flag") is True
    assert cli_attrs.int_attr(args, "numeric", default=7) == 7
    assert cli_attrs.int_attr(args, "broken", default=9) == 9
    assert cli_attrs.optional_text_attr(args, "path_value") == str(
        tmp_path / "report.json"
    )
    assert cli_attrs.optional_text_attr(args, "invalid_text") is None


def test_cli_tips_detect_vscode_environment_signals() -> None:
    assert cli_tips._is_vscode_environment({"TERM_PROGRAM": "vscode"}) is True
    assert cli_tips._is_vscode_environment({"VSCODE_PID": "123"}) is True
    assert cli_tips._is_vscode_environment({"TERM_PROGRAM": "xterm-256color"}) is False


def test_cli_stream_is_tty_handles_oserror() -> None:
    class _BrokenTTY:
        def isatty(self) -> bool:
            raise OSError("tty unavailable")

    assert cli_tips._stream_is_tty(cast("TextIO", _BrokenTTY())) is False


def test_cli_load_tips_state_rejects_invalid_tip_shapes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli_tips, "read_json_object", lambda _path: {"tips": []})
    assert cli_tips._load_tips_state(tmp_path / "tips.json") == {
        "schema_version": 1,
        "tips": {},
    }


def test_cli_tip_last_shown_version_rejects_invalid_shapes() -> None:
    assert (
        cli_tips._tip_last_shown_version({"tips": []}, tip_key="vscode_extension") == ""
    )
    assert (
        cli_tips._tip_last_shown_version(
            {"tips": {"vscode_extension": {"last_shown_version": 7}}},
            tip_key="vscode_extension",
        )
        == ""
    )


def test_cli_vscode_extension_tip_uses_versioned_cache(
    tmp_path: Path,
) -> None:
    printer = _RecordingPrinter()
    args = SimpleNamespace(quiet=False, ci=False)
    env = {"TERM_PROGRAM": "vscode"}
    cache_path = tmp_path / ".codeclone" / "cache.json"

    cli_tips.maybe_print_vscode_extension_tip(
        args=args,
        console=printer,
        codeclone_version=__version__,
        cache_path=cache_path,
        environ=env,
        stream=_TTYStream(is_tty=True),
    )

    assert len(printer.lines) == 1
    assert "VS Code detected" in printer.lines[0]
    assert "marketplace.visualstudio.com" in printer.lines[0]

    tips_path = cache_path.parent / "tips.json"
    state = json.loads(tips_path.read_text("utf-8"))
    assert state["tips"]["vscode_extension"]["last_shown_version"] == __version__

    shown_again = cli_tips.maybe_print_vscode_extension_tip(
        args=args,
        console=printer,
        codeclone_version=__version__,
        cache_path=cache_path,
        environ=env,
        stream=_TTYStream(is_tty=True),
    )
    assert shown_again is False
    assert len(printer.lines) == 1

    shown_for_new_version = cli_tips.maybe_print_vscode_extension_tip(
        args=args,
        console=printer,
        codeclone_version=f"{__version__}.post1",
        cache_path=cache_path,
        environ=env,
        stream=_TTYStream(is_tty=True),
    )
    assert shown_for_new_version is True
    assert len(printer.lines) == 2


def test_cli_vscode_extension_tip_tolerates_state_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printer = _RecordingPrinter()
    args = SimpleNamespace(quiet=False, ci=False)

    def _fail_remember(**_kwargs: object) -> None:
        raise OSError("read-only cache")

    monkeypatch.setattr(cli_tips, "_remember_tip_version", _fail_remember)

    shown = cli_tips.maybe_print_vscode_extension_tip(
        args=args,
        console=printer,
        codeclone_version=__version__,
        cache_path=tmp_path / ".codeclone" / "cache.json",
        environ={"TERM_PROGRAM": "vscode"},
        stream=_TTYStream(is_tty=True),
    )

    assert shown is True
    assert len(printer.lines) == 1


@pytest.mark.parametrize(
    ("args", "env", "isatty"),
    [
        (SimpleNamespace(quiet=True, ci=False), {"TERM_PROGRAM": "vscode"}, True),
        (SimpleNamespace(quiet=False, ci=True), {"TERM_PROGRAM": "vscode"}, True),
        (
            SimpleNamespace(quiet=False, ci=False),
            {"TERM_PROGRAM": "vscode", "CI": "1"},
            True,
        ),
        (SimpleNamespace(quiet=False, ci=False), {"TERM_PROGRAM": "vscode"}, False),
        (
            SimpleNamespace(quiet=False, ci=False),
            {"TERM_PROGRAM": "xterm-256color"},
            True,
        ),
    ],
)
def test_cli_vscode_extension_tip_respects_context_gates(
    tmp_path: Path,
    args: SimpleNamespace,
    env: dict[str, str],
    isatty: bool,
) -> None:
    printer = _RecordingPrinter()
    effective_env = dict(env)

    shown = cli_tips.maybe_print_vscode_extension_tip(
        args=args,
        console=printer,
        codeclone_version=__version__,
        cache_path=tmp_path / ".codeclone" / "cache.json",
        environ=effective_env,
        stream=_TTYStream(is_tty=isatty),
    )

    assert shown is False
    assert printer.lines == []


def test_cli_gitignore_codeclone_cache_tip(tmp_path: Path) -> None:
    printer = _RecordingPrinter()
    shown = cli_tips.maybe_print_gitignore_codeclone_cache_tip(
        args=SimpleNamespace(quiet=False, ci=False),
        console=printer,
        root_path=tmp_path,
        environ={},
        stream=_TTYStream(is_tty=True),
    )
    assert shown is True
    assert len(printer.lines) == 1
    assert ".codeclone/" in printer.lines[0]

    covered_root = tmp_path / "covered"
    covered_root.mkdir()
    (covered_root / ".gitignore").write_text(".cache/\n", encoding="utf-8")
    silent_printer = _RecordingPrinter()
    assert (
        cli_tips.maybe_print_gitignore_codeclone_cache_tip(
            args=SimpleNamespace(quiet=False, ci=False),
            console=silent_printer,
            root_path=covered_root,
            environ={},
            stream=_TTYStream(is_tty=True),
        )
        is False
    )
    assert silent_printer.lines == []


@pytest.mark.parametrize(
    ("baseline_version", "current_version", "expected"),
    [
        ("2.0.0b1", "2.0.1", True),
        ("2.0.0b7", "2.0.1", True),
        ("2.0.0", "2.0.1", True),
        ("2.0.0", "2.1.0", True),
        ("2.0.1", "2.0.2", True),
        ("2.0.1", "2.1.0", True),
        ("2.0.0b0", "2.0.1", False),
        ("1.4.4", "2.0.1", False),
        ("2.0.1", "2.0.1", False),
        ("2.0.2", "2.0.2", False),
        ("dev-build", "2.0.1", False),
        ("2.0.0", "dev-build", False),
        (None, "2.0.1", False),
    ],
)
def test_cli_dead_code_reachability_migration_note_version_gate(
    baseline_version: str | None,
    current_version: str,
    expected: bool,
) -> None:
    assert (
        cli_tips._dead_code_reachability_migration(
            baseline_generator_version=baseline_version,
            codeclone_version=current_version,
        )
        is not None
    ) is expected


@pytest.mark.parametrize(
    (
        "baseline_version",
        "current_version",
        "expected_message",
        "expected_tip_key",
        "preexisting_tip_keys",
        "print_note",
    ),
    [
        (
            "2.0.0b7",
            "2.0.1",
            "Dead-code reachability was refined in 2.0.1",
            "dead_code_reachability_2_0_1_migration_shown",
            (),
            cli_tips.maybe_print_dead_code_reachability_migration_note,
        ),
        (
            "2.0.1",
            "2.0.2",
            "Dead-code reachability was refined again in 2.0.2",
            "dead_code_reachability_2_0_2_migration_shown",
            ("dead_code_reachability_2_0_1_migration_shown",),
            cli_tips.maybe_print_dead_code_reachability_migration_note,
        ),
        (
            "2.0.2",
            "2.1.0a1",
            "Class cohesion (LCOM4) applicability was refined in 2.1.0",
            "cohesion_lcom4_2_1_migration_shown",
            (),
            cli_tips.maybe_print_cohesion_lcom4_migration_note,
        ),
    ],
)
def test_cli_migration_notes_use_one_shot_cache(
    tmp_path: Path,
    baseline_version: str,
    current_version: str,
    expected_message: str,
    expected_tip_key: str,
    preexisting_tip_keys: tuple[str, ...],
    print_note: Callable[..., bool],
) -> None:
    printer = _RecordingPrinter()
    args = SimpleNamespace(quiet=False, ci=False)
    cache_path = tmp_path / ".codeclone" / "cache.json"
    tips_path = cache_path.parent / "tips.json"
    if preexisting_tip_keys:
        tips_path.parent.mkdir(parents=True)
        tips_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "tips": {key: {"shown": True} for key in preexisting_tip_keys},
                }
            ),
            "utf-8",
        )

    shown = print_note(
        args=args,
        console=printer,
        codeclone_version=current_version,
        cache_path=cache_path,
        baseline_generator_version=baseline_version,
        baseline_trusted_for_diff=True,
        environ={},
        stream=_TTYStream(is_tty=True),
    )

    assert shown is True
    assert len(printer.lines) == 1
    assert expected_message in printer.lines[0]
    assert "not weaker detection" in printer.lines[0]

    state = json.loads(tips_path.read_text("utf-8"))
    for tip_key in (*preexisting_tip_keys, expected_tip_key):
        assert state["tips"][tip_key]["shown"] is True

    shown_again = print_note(
        args=args,
        console=printer,
        codeclone_version=current_version,
        cache_path=cache_path,
        baseline_generator_version=baseline_version,
        baseline_trusted_for_diff=True,
        environ={},
        stream=_TTYStream(is_tty=True),
    )

    assert shown_again is False
    assert len(printer.lines) == 1


@pytest.mark.parametrize(
    ("args", "env", "isatty", "trusted", "baseline_version", "current_version"),
    [
        (SimpleNamespace(quiet=True, ci=False), {}, True, True, "2.0.0", "2.0.1"),
        (SimpleNamespace(quiet=False, ci=True), {}, True, True, "2.0.0", "2.0.1"),
        (
            SimpleNamespace(quiet=False, ci=False),
            {"CI": "1"},
            True,
            True,
            "2.0.0",
            "2.0.1",
        ),
        (SimpleNamespace(quiet=False, ci=False), {}, False, True, "2.0.0", "2.0.1"),
        (SimpleNamespace(quiet=False, ci=False), {}, True, False, "2.0.0", "2.0.1"),
        (SimpleNamespace(quiet=False, ci=False), {}, True, True, "2.0.1", "2.0.1"),
        (SimpleNamespace(quiet=False, ci=False), {}, True, True, "2.0.0", "2.0.0"),
    ],
)
def test_cli_dead_code_reachability_migration_note_respects_gates(
    tmp_path: Path,
    args: SimpleNamespace,
    env: dict[str, str],
    isatty: bool,
    trusted: bool,
    baseline_version: str,
    current_version: str,
) -> None:
    printer = _RecordingPrinter()

    shown = cli_tips.maybe_print_dead_code_reachability_migration_note(
        args=args,
        console=printer,
        codeclone_version=current_version,
        cache_path=tmp_path / ".codeclone" / "cache.json",
        baseline_generator_version=baseline_version,
        baseline_trusted_for_diff=trusted,
        environ=env,
        stream=_TTYStream(is_tty=isatty),
    )

    assert shown is False
    assert printer.lines == []


@pytest.mark.parametrize(
    ("baseline_version", "current_version", "expected"),
    [
        ("2.0.2", "2.1.0a1", True),
        ("2.0.2", "2.1.0", True),
        ("2.0.2", "2.0.2", False),
        ("2.0.1", "2.1.0a1", False),
        ("2.0.1", "2.1.0", False),
        ("2.0.0", "2.1.0", False),
        (None, "2.1.0a1", False),
    ],
)
def test_cli_cohesion_lcom4_migration_note_version_gate(
    baseline_version: str | None,
    current_version: str,
    expected: bool,
) -> None:
    assert (
        cli_tips._cohesion_lcom4_migration(
            baseline_generator_version=baseline_version,
            codeclone_version=current_version,
        )
        is not None
    ) is expected


def test_tip_was_shown_returns_false_for_malformed_state() -> None:
    assert cli_tips._tip_was_shown({"tips": "not-a-mapping"}, tip_key="x") is False


def test_migration_note_still_reports_when_tip_cache_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printer = _RecordingPrinter()
    args = SimpleNamespace(quiet=False, ci=False)
    cache_path = tmp_path / ".codeclone" / "cache.json"

    def _fail_remember(**_kwargs: object) -> None:
        raise OSError("read-only tips cache")

    monkeypatch.setattr(cli_tips, "_remember_tip_shown", _fail_remember)

    shown = cli_tips.maybe_print_cohesion_lcom4_migration_note(
        args=args,
        console=printer,
        codeclone_version="2.1.0a1",
        cache_path=cache_path,
        baseline_generator_version="2.0.2",
        baseline_trusted_for_diff=True,
        environ={},
        stream=_TTYStream(is_tty=True),
    )

    assert shown is True
    assert len(printer.lines) == 1
    assert "Class cohesion (LCOM4) applicability was refined" in printer.lines[0]


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
    assert_contains_none(out, "Scanning root")
    assert_contains_none(out, "Architectural duplication detector")


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
        "--interactive-help",
        (
            "Deterministic Structural Change Controller for AI-assisted "
            "Python development."
        ),
        "Target:",
        "Analysis:",
        "--changed-only",
        "--diff-against GIT_REF",
        "--paths-from-git-diff GIT_REF",
        "--blast-radius FILE [FILE ...]",
        "--patch-verify",
        "--strictness LEVEL",
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
        "<root>/.codeclone/cache.json",
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
    assert_contains_none(out, "\x1b[")


def test_report_path_origins_distinguish_bare_and_explicit_flags() -> None:
    assert cli_reports._report_path_origins(
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
    assert cli_reports._report_path_origins(("--json=out.json", "--", "--html")) == {
        "html": None,
        "json": "explicit",
        "md": None,
        "sarif": None,
        "text": None,
    }


def test_timestamped_report_path_appends_utc_slug() -> None:
    path = Path("/tmp/report.html")
    assert cli_reports._timestamped_report_path(
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


def test_main_dispatches_memory_subcommand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def _memory_main(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    monkeypatch.setattr(sys, "argv", ["codeclone", "memory", "status", "--root", "."])
    monkeypatch.setattr(
        "codeclone.surfaces.cli.memory.memory_main",
        _memory_main,
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert calls == [["status", "--root", "."]]


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
    assert_contains_all(out, "INTERNAL ERROR:")
    assert_contains_all(out, "Unexpected exception.")
    assert_contains_all(out, "Reason: RuntimeError: boom")
    assert_contains_all(out, "Next steps:")
    assert_contains_all(out, "Re-run with --debug to include a traceback.")
    assert_contains_all(out, f"{ISSUES_URL}/new?template=bug_report.yml")
    assert_contains_none(out, "Traceback:")


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
    assert_contains_all(out, "INTERNAL ERROR:")
    assert_contains_all(out, "DEBUG DETAILS")
    assert_contains_all(out, "Traceback:")
    assert_contains_all(out, "Command: codeclone --debug")


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
    assert_contains_all(out, "INTERNAL ERROR:")
    assert_contains_all(out, "DEBUG DETAILS")
    assert_contains_all(out, "Traceback:")


def test_argument_parser_contract_error_marker_for_invalid_args(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_parser(__version__)
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--unknown-flag"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "CONTRACT ERROR:" in err


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(
            Namespace(
                changed_only=True,
                diff_against=None,
                paths_from_git_diff=None,
            ),
            id="requires_diff_source",
        ),
        pytest.param(
            Namespace(
                changed_only=False,
                diff_against="main",
                paths_from_git_diff=None,
            ),
            id="diff_against_requires_changed_only",
        ),
        pytest.param(
            Namespace(
                changed_only=True,
                diff_against="HEAD~1",
                paths_from_git_diff="HEAD~2",
            ),
            id="conflicting_diff_sources",
        ),
    ],
)
def test_validate_changed_scope_args_rejects_invalid_combinations(
    args: Namespace,
) -> None:
    cli.console = cli._make_console(no_color=True)
    with pytest.raises(SystemExit) as exc:
        cli_changed_scope._validate_changed_scope_args(args=args)
    assert exc.value.code == 2


def test_validate_changed_scope_args_promotes_paths_from_git_diff() -> None:
    args = Namespace(
        changed_only=False,
        diff_against=None,
        paths_from_git_diff="HEAD~1",
    )
    assert cli_changed_scope._validate_changed_scope_args(args=args) == "HEAD~1"
    assert args.changed_only is True


def test_normalize_changed_paths_relativizes_dedupes_and_sorts(tmp_path: Path) -> None:
    root_path = tmp_path.resolve()
    pkg_dir = root_path / "pkg"
    pkg_dir.mkdir()
    first = pkg_dir / "b.py"
    second = pkg_dir / "a.py"
    first.write_text("pass\n", "utf-8")
    second.write_text("pass\n", "utf-8")

    assert cli_changed_scope._normalize_changed_paths(
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
        cli_changed_scope._normalize_changed_paths(
            root_path=root_path,
            paths=(str(candidate),),
        )
        == ()
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
        cli_changed_scope._normalize_changed_paths(
            root_path=root_path,
            paths=("broken.py",),
        )
    assert exc.value.code == 2


def test_normalize_changed_paths_rejects_outside_root(tmp_path: Path) -> None:
    cli.console = cli._make_console(no_color=True)
    root_path = tmp_path.resolve()
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside"
    outside_dir.mkdir()
    outside_path = outside_dir / "external.py"
    outside_path.write_text("pass\n", "utf-8")

    with pytest.raises(SystemExit) as exc:
        cli_changed_scope._normalize_changed_paths(
            root_path=root_path,
            paths=(str(outside_path),),
        )
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
    assert cli_changed_scope._git_diff_changed_paths(
        root_path=root_path,
        git_diff_ref="HEAD~1",
    ) == (
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
        cli_changed_scope._git_diff_changed_paths(
            root_path=tmp_path.resolve(),
            git_diff_ref="HEAD~1",
        )
    assert exc.value.code == 2


def test_git_diff_changed_paths_rejects_option_like_ref(tmp_path: Path) -> None:
    cli.console = cli._make_console(no_color=True)
    with pytest.raises(SystemExit) as exc:
        cli_changed_scope._git_diff_changed_paths(
            root_path=tmp_path.resolve(), git_diff_ref="--cached"
        )
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "git_diff_ref",
    [
        "HEAD~1;rm",
        "HEAD path",
        "HEAD:path",
        "../HEAD",
        " HEAD",
    ],
)
def test_git_diff_changed_paths_rejects_unsafe_ref_syntax(
    tmp_path: Path,
    git_diff_ref: str,
) -> None:
    cli.console = cli._make_console(no_color=True)
    with pytest.raises(SystemExit) as exc:
        cli_changed_scope._git_diff_changed_paths(
            root_path=tmp_path.resolve(),
            git_diff_ref=git_diff_ref,
        )
    assert exc.value.code == 2


def test_report_path_origins_ignores_unrelated_equals_tokens() -> None:
    assert cli_reports._report_path_origins(("--unknown=value", "--json=out.json")) == {
        "html": None,
        "json": "explicit",
        "md": None,
        "sarif": None,
        "text": None,
    }


def test_changed_clone_gate_from_report_filters_changed_scope() -> None:
    gate = cli_changed_scope._changed_clone_gate_from_report(
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


def test_enforce_gating_uses_precomputed_changed_scope_threshold_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli.console = cli._make_console(no_color=True)
    observed: dict[str, object] = {}
    analysis = AnalysisResult(
        func_groups={},
        block_groups={},
        block_groups_report={},
        segment_groups={},
        suppressed_segment_groups=0,
        block_group_facts={},
        func_clones_count=8,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=0,
        project_metrics=None,
        metrics_payload=None,
        suggestions=(),
        segment_groups_raw_digest="",
        observation_bundle=TEST_OBSERVATION_BUNDLE,
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
            analysis=analysis,
            processing=cast(Any, Namespace(source_read_failures=[])),
            source_read_contract_failure=False,
            baseline_failure_code=None,
            metrics_baseline_failure_code=None,
            new_func=set(),
            new_block=set(),
            gate_result=GatingResult(
                exit_code=3,
                reasons=("clone:threshold:2:1",),
            ),
            html_report_path=None,
        )

    assert exc.value.code == 3
    assert observed["code"] == "threshold"
    assert observed["entries"] == (
        ("clone_groups_total", 2),
        ("clone_groups_limit", 1),
    )


def test_enforce_gating_uses_precomputed_changed_scope_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli.console = cli._make_console(no_color=True)
    observed: dict[str, object] = {}
    analysis = AnalysisResult(
        func_groups={},
        block_groups={},
        block_groups_report={},
        segment_groups={},
        suppressed_segment_groups=0,
        block_group_facts={},
        func_clones_count=8,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=0,
        project_metrics=None,
        metrics_payload=None,
        suggestions=(),
        segment_groups_raw_digest="",
        observation_bundle=TEST_OBSERVATION_BUNDLE,
    )

    monkeypatch.setattr(
        cli,
        "_print_gating_failure_block",
        lambda **kwargs: observed.update(kwargs),
    )

    cli._enforce_gating(
        args=Namespace(fail_threshold=5, verbose=False),
        analysis=analysis,
        processing=cast(Any, Namespace(source_read_failures=[])),
        source_read_contract_failure=False,
        baseline_failure_code=None,
        metrics_baseline_failure_code=None,
        new_func=set(),
        new_block=set(),
        gate_result=GatingResult(exit_code=0, reasons=()),
        html_report_path=None,
    )

    assert observed == {}


def test_enforce_gating_exits_two_for_required_unavailable_lane() -> None:
    cli.console = cli._make_console(no_color=True)
    with pytest.raises(SystemExit) as exc:
        cli._enforce_gating(
            args=Namespace(
                fail_on_untested_hotspots=False,
                fail_threshold=-1,
                verbose=False,
            ),
            analysis=cast(Any, SimpleNamespace(coverage_join=None)),
            processing=cast(Any, Namespace(source_read_failures=[])),
            source_read_contract_failure=False,
            baseline_failure_code=None,
            metrics_baseline_failure_code=None,
            new_func=set(),
            new_block=set(),
            gate_result=GatingResult(
                exit_code=2,
                reasons=("lane:unavailable:clones.functions",),
                required_lanes=("clones.functions",),
                unavailable_lanes=("clones.functions",),
            ),
            html_report_path=None,
        )

    assert exc.value.code == 2


def test_main_impl_prints_changed_scope_when_changed_projection_is_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "baseline.json"
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
            "--cache-path",
            str(cache_path),
        ],
    )
    observed: dict[str, object] = {}
    gate_result = GatingResult(exit_code=0, reasons=())

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
                # The report meta now declares metric families from the payload
                # the analysis emitted, so the stub must carry that evidence.
                metrics_payload=None,
                observation_bundle=SimpleNamespace(
                    contract=SimpleNamespace(enabled_lanes=()),
                ),
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
            baseline=metrics_baseline_mod.MetricsBaseline(baseline_path),
            loaded=False,
            status=metrics_baseline_mod.MetricsBaselineStatus.MISSING,
            trusted_for_diff=False,
            failure_code=None,
        ),
    )
    monkeypatch.setattr(cli_meta_mod, "_build_report_meta", lambda **_kwargs: {})
    monkeypatch.setattr(cli, "_print_summary", lambda **_kwargs: None)
    monkeypatch.setattr(cli, "build_report_body_for_analysis", lambda **_kwargs: {})
    gate_calls = 0

    def _gate_once(**_kwargs: object) -> tuple[object, GatingResult]:
        nonlocal gate_calls
        gate_calls += 1
        return object(), gate_result

    def _report(**kwargs: object) -> SimpleNamespace:
        observed["report_gate_result"] = kwargs["gate_result"]
        return SimpleNamespace(report_document={})

    def _enforce(**kwargs: object) -> None:
        observed["enforce_gate_result"] = kwargs["gate_result"]

    monkeypatch.setattr(cli, "gate_with_config", _gate_once)
    monkeypatch.setattr(cli, "report", _report)
    monkeypatch.setattr(
        cli,
        "_changed_clone_gate_from_report",
        lambda _report, changed_paths: cli_changed_scope.ChangedCloneGate(
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
    monkeypatch.setattr(cli, "_enforce_gating", _enforce)

    cli._main_impl()

    changed_scope = cast(Any, observed["changed_scope"])
    assert observed["quiet"] is True
    assert changed_scope.paths_count == 1
    assert changed_scope.findings_total == 3
    assert gate_calls == 1
    assert observed["report_gate_result"] is gate_result
    assert observed["enforce_gate_result"] is gate_result


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


@pytest.mark.parametrize(
    "report_document",
    (
        {},
        {"integrity": {}},
        {"integrity": {"digests": {}}},
    ),
)
def test_report_digest_from_document_requires_comparison_tier(
    report_document: dict[str, object],
) -> None:
    assert cli._report_digest_from_document(report_document) == ""


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
        suppressed_golden_fixture_groups=0,
        suppressed_segment_groups=0,
        new_clones_count=0,
    )
    out = capsys.readouterr().out
    assert_contains_all(out, "Summary accounting mismatch")


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
            overloaded_modules=3,
        )
        == "Metrics  cc=2.8/21  cbo=0.6/8  lcom4=1.2/4"
        "  cycles=0  dead_code=1  health=85(B)  overloaded_modules=3"
    )
    assert (
        ui.fmt_summary_compact_dependencies(
            avg_depth=4.0,
            p95_depth=13,
            max_depth=16,
        )
        == "Dependencies  avg=4.0  p95=13  max=16"
    )
    assert (
        ui.fmt_summary_compact_security_surfaces(
            items=5,
            categories=3,
            production=4,
            tests=1,
        )
        == "Security  items=5  categories=3  production=4  tests=1"
    )
    assert (
        ui.fmt_summary_compact_adoption(
            param_permille=750,
            return_permille=500,
            docstring_permille=667,
            any_annotation_count=1,
        )
        == "Adoption  params=75.0%  returns=50.0%  docstrings=66.7%  any=1"
    )
    assert (
        ui.fmt_summary_compact_api_surface(
            public_symbols=3,
            modules=2,
            breaking=1,
            added=4,
        )
        == "Public API  symbols=3  modules=2  breaking=1  added=4"
    )
    assert (
        ui.fmt_summary_compact_clones(
            function=1,
            block=2,
            segment=0,
            suppressed=3,
            fixture_excluded=2,
            new=4,
        )
        == "Clones   func=1  block=2  seg=0  suppressed=3  fixtures=2  new=4"
    )
    assert (
        ui.fmt_summary_compact_coverage_join(
            status="ok",
            overall_permille=735,
            coverage_hotspots=2,
            scope_gap_hotspots=1,
            threshold_percent=50,
            source_label="coverage.xml",
        )
        == "Coverage  status=ok  overall=73.5%  coverage_hotspots=2"
        "  threshold=50  scope_gaps=1  source=coverage.xml"
    )
    assert (
        ui.fmt_coverage_join_ignored("bad xml")
        == "[warning]Coverage join ignored: bad xml[/warning]"
    )


def test_ui_summary_formatters_cover_optional_branches() -> None:
    from codeclone.ui_messages.styling import _vn

    assert _vn(0) == "[dim]0[/dim]"
    assert _vn(1200) == "1,200"

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
        fixture_excluded=2,
        new=0,
    )
    assert "[bold yellow]3[/bold yellow] seg" in clones
    assert "[yellow]2[/yellow] fixtures" in clones

    assert "5 detected" in ui.fmt_metrics_cycles(5)
    dependencies = ui.fmt_metrics_dependencies(
        avg_depth=4.0,
        p95_depth=13,
        max_depth=16,
    )
    assert_contains_all(dependencies, "avg 4.0", "p95 13", "max 16")
    security_surfaces = ui.fmt_metrics_security_surfaces(
        items=5,
        categories=3,
        production=4,
        tests=1,
    )
    assert_contains_all(
        security_surfaces,
        "5",
        "surfaces",
        "3",
        "categories",
        "production 4",
        "tests 1",
    )
    dead_with_suppressed = ui.fmt_metrics_dead_code(447, suppressed=9)
    assert "447 found" in dead_with_suppressed
    assert "(9 suppressed)" in dead_with_suppressed
    assert "✔ clean" in ui.fmt_metrics_dead_code(0, suppressed=0)
    clean_with_suppressed = ui.fmt_metrics_dead_code(0, suppressed=9)
    assert "✔ clean" in clean_with_suppressed
    assert "(9 suppressed)" in clean_with_suppressed
    overloaded_modules = ui.fmt_metrics_overloaded_modules(
        candidates=4,
        total=158,
        population_status="ok",
        top_score=0.98,
    )
    assert all(
        fragment in overloaded_modules
        for fragment in ("4", "max score 0.98", "158 ranked", "(report-only)")
    )
    limited_overloaded_modules = ui.fmt_metrics_overloaded_modules(
        candidates=0,
        total=12,
        population_status="limited",
        top_score=0.0,
    )
    assert "12 ranked" in limited_overloaded_modules
    assert "report-only; limited population" in limited_overloaded_modules
    adoption = ui.fmt_metrics_adoption(
        param_permille=750,
        return_permille=500,
        docstring_permille=667,
        any_annotation_count=1,
    )
    assert_contains_all(
        adoption,
        "params 75.0%",
        "returns 50.0%",
        "docstrings 66.7%",
        "Any 1",
    )
    api_surface = ui.fmt_metrics_api_surface(
        public_symbols=3,
        modules=2,
        breaking=1,
        added=4,
    )
    assert_contains_all(api_surface, "symbols", "modules", "breaking", "added")
    coverage_join = ui.fmt_metrics_coverage_join(
        status="ok",
        overall_permille=735,
        coverage_hotspots=2,
        scope_gap_hotspots=1,
        threshold_percent=50,
        source_label="coverage.xml",
    )
    assert_contains_all(
        coverage_join,
        "73.5% overall",
        "[bold red]2[/bold red] hotspots < 50%",
        "[bold yellow]1[/bold yellow] scope gaps",
        "coverage.xml",
    )
    coverage_join_unavailable = ui.fmt_metrics_coverage_join(
        status="invalid",
        overall_permille=0,
        coverage_hotspots=0,
        scope_gap_hotspots=0,
        threshold_percent=50,
        source_label="coverage.xml",
    )
    assert_contains_all(
        coverage_join_unavailable,
        "join unavailable",
        "coverage.xml",
    )
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
    assert_contains_all(out, "Changed Scope")
    assert_contains_all(out, "Paths")
    assert_contains_all(out, "Findings")
    assert_contains_all(out, "from git diff")


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
    assert_contains_all(out, "Changed", "paths=45", "findings=7", "new=2", "known=5")


def test_print_metrics_in_quiet_mode_includes_overloaded_modules(
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
            overloaded_modules_candidates=3,
            overloaded_modules_total=158,
            overloaded_modules_population_status="ok",
            overloaded_modules_top_score=0.98,
        ),
    )
    out = capsys.readouterr().out
    assert_contains_all(out, "overloaded_modules=3")
    assert_contains_none(out, "Adoption")
    assert_contains_none(out, "Public API")


def test_print_metrics_in_quiet_mode_includes_security_surfaces(
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
            security_surfaces_items=5,
            security_surfaces_category_count=3,
            security_surfaces_production=4,
            security_surfaces_tests=1,
        ),
    )
    out = capsys.readouterr().out
    assert_contains_all(
        out,
        "Security",
        "items=5",
        "categories=3",
        "production=4",
        "tests=1",
    )


def test_print_metrics_in_quiet_mode_includes_adoption_public_api_and_coverage(
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
            security_surfaces_items=5,
            security_surfaces_category_count=3,
            security_surfaces_production=4,
            security_surfaces_tests=1,
            adoption_param_permille=750,
            adoption_return_permille=500,
            adoption_docstring_permille=667,
            adoption_any_annotation_count=1,
            api_surface_enabled=True,
            api_surface_modules=2,
            api_surface_public_symbols=3,
            api_surface_added=4,
            api_surface_breaking=1,
            coverage_join_status="ok",
            coverage_join_overall_permille=735,
            coverage_join_coverage_hotspots=2,
            coverage_join_scope_gap_hotspots=1,
            coverage_join_threshold_percent=50,
            coverage_join_source_label="coverage.xml",
            overloaded_modules_candidates=3,
            overloaded_modules_total=158,
            overloaded_modules_population_status="ok",
            overloaded_modules_top_score=0.98,
        ),
    )
    out = capsys.readouterr().out
    assert_contains_all(
        out,
        "Security",
        "items=5",
        "production=4",
        "Adoption",
        "params=75.0%",
        "Public API",
        "breaking=1",
        "Coverage",
        "coverage_hotspots=2",
        "source=coverage.xml",
    )


def test_print_metrics_in_normal_mode_includes_adoption_public_api_and_coverage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    cli_summary._print_metrics(
        console=cast("cli_summary._Printer", cli.console),
        quiet=False,
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
            security_surfaces_items=5,
            security_surfaces_category_count=3,
            security_surfaces_production=4,
            security_surfaces_tests=1,
            adoption_param_permille=750,
            adoption_return_permille=500,
            adoption_docstring_permille=667,
            adoption_any_annotation_count=1,
            api_surface_enabled=True,
            api_surface_modules=2,
            api_surface_public_symbols=3,
            api_surface_added=4,
            api_surface_breaking=1,
            coverage_join_status="ok",
            coverage_join_overall_permille=735,
            coverage_join_coverage_hotspots=2,
            coverage_join_scope_gap_hotspots=1,
            coverage_join_threshold_percent=50,
            coverage_join_source_label="coverage.xml",
            overloaded_modules_candidates=3,
            overloaded_modules_total=158,
            overloaded_modules_population_status="ok",
            overloaded_modules_top_score=0.98,
        ),
    )
    out = capsys.readouterr().out
    assert_contains_all(
        out,
        "Security",
        "5 surfaces",
        "Adoption",
        "params 75.0%",
        "docstrings 66.7%",
        "Public API",
        "3 symbols",
        "1 breaking",
        "Coverage",
        "73.5% overall",
        "2 hotspots < 50%",
    )


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
        cli_runtime._configure_metrics_mode(args=args, metrics_baseline_exists=False)
    assert exc.value.code == 2


def test_configure_metrics_mode_preserves_explicit_full_metrics_request() -> None:
    args = Namespace(
        skip_metrics=False,
        _full_metrics_explicit=True,
        skip_dead_code=False,
        skip_dependencies=False,
    )

    cli_runtime._configure_metrics_mode(args=args, metrics_baseline_exists=False)

    assert args.skip_metrics is False


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
    cli_runtime._configure_metrics_mode(args=args, metrics_baseline_exists=True)
    assert args.skip_dead_code is False
    assert args.skip_dependencies is False


def test_configure_metrics_mode_does_not_force_api_surface_for_baseline_update() -> (
    None
):
    args = Namespace(
        skip_metrics=False,
        fail_complexity=-1,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=False,
        fail_dead_code=False,
        fail_health=-1,
        fail_on_new_metrics=False,
        fail_on_typing_regression=False,
        fail_on_docstring_regression=False,
        fail_on_api_break=False,
        fail_on_untested_hotspots=False,
        min_typing_coverage=-1,
        min_docstring_coverage=-1,
        update_metrics_baseline=True,
        skip_dead_code=False,
        skip_dependencies=False,
        api_surface=False,
        coverage_xml=None,
    )

    cli_runtime._configure_metrics_mode(args=args, metrics_baseline_exists=True)

    assert args.api_surface is False


def test_configure_metrics_mode_forces_api_surface_for_api_break_gate() -> None:
    args = Namespace(
        skip_metrics=False,
        fail_complexity=-1,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=False,
        fail_dead_code=False,
        fail_health=-1,
        fail_on_new_metrics=False,
        fail_on_typing_regression=False,
        fail_on_docstring_regression=False,
        fail_on_api_break=True,
        fail_on_untested_hotspots=False,
        min_typing_coverage=-1,
        min_docstring_coverage=-1,
        update_metrics_baseline=False,
        skip_dead_code=False,
        skip_dependencies=False,
        api_surface=False,
        coverage_xml=None,
    )

    cli_runtime._configure_metrics_mode(args=args, metrics_baseline_exists=True)

    assert args.api_surface is True


def test_prepare_metrics_mode_and_ui_invokes_hooks_and_skips_banner_when_quiet(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, object]] = []

    def _configure_metrics_mode(
        *,
        args: object,
        metrics_baseline_exists: bool,
    ) -> None:
        calls.append(("configure", metrics_baseline_exists))

    def _print_banner(*, root: Path) -> None:
        calls.append(("banner", root))

    args = Namespace(
        update_baseline=False,
        skip_metrics=False,
        update_metrics_baseline=False,
        quiet=False,
        no_progress=False,
    )
    baseline_path = tmp_path / "codeclone.baseline.json"

    cli_runtime.prepare_metrics_mode_and_ui(
        args=args,
        root_path=tmp_path,
        baseline_path=baseline_path,
        baseline_exists=False,
        metrics_baseline_path=baseline_path,
        metrics_baseline_exists=False,
        configure_metrics_mode=_configure_metrics_mode,
        print_banner=_print_banner,
    )

    assert calls == [("configure", False), ("banner", tmp_path)]
    assert args.no_progress is False

    args.quiet = True
    calls.clear()
    cli_runtime.prepare_metrics_mode_and_ui(
        args=args,
        root_path=tmp_path,
        baseline_path=baseline_path,
        baseline_exists=False,
        metrics_baseline_path=baseline_path,
        metrics_baseline_exists=False,
        configure_metrics_mode=_configure_metrics_mode,
        print_banner=_print_banner,
    )

    assert calls == [("configure", False)]
    assert args.no_progress is True


def test_prepare_metrics_mode_and_ui_skips_optional_hooks_when_none(
    tmp_path: Path,
) -> None:
    args = Namespace(
        update_baseline=False,
        skip_metrics=False,
        update_metrics_baseline=False,
        quiet=False,
        no_progress=False,
    )
    baseline_path = tmp_path / "codeclone.baseline.json"

    cli_runtime.prepare_metrics_mode_and_ui(
        args=args,
        root_path=tmp_path,
        baseline_path=baseline_path,
        baseline_exists=False,
        metrics_baseline_path=baseline_path,
        metrics_baseline_exists=False,
        configure_metrics_mode=None,
        print_banner=None,
    )

    assert args.no_progress is False


def test_probe_metrics_baseline_section_for_non_object_payload(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text("[]", "utf-8")
    probe = cli_baselines_mod._probe_metrics_baseline_section(path)
    assert probe.has_metrics_section is True
    assert probe.payload is None


def test_enforce_gating_requires_coverage_input_for_hotspot_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli.console = cli._make_console(no_color=True)
    with pytest.raises(SystemExit) as exc:
        cli._enforce_gating(
            args=Namespace(
                fail_on_untested_hotspots=True,
                fail_threshold=-1,
                verbose=False,
            ),
            analysis=cast(Any, SimpleNamespace(coverage_join=None)),
            processing=cast(Any, Namespace(source_read_failures=[])),
            source_read_contract_failure=False,
            baseline_failure_code=None,
            metrics_baseline_failure_code=None,
            new_func=set(),
            new_block=set(),
            gate_result=GatingResult(0, ()),
            html_report_path=None,
        )
    assert exc.value.code == 2


def test_enforce_gating_requires_valid_coverage_input_for_hotspot_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli.console = cli._make_console(no_color=True)
    with pytest.raises(SystemExit) as exc:
        cli._enforce_gating(
            args=Namespace(
                fail_on_untested_hotspots=True,
                fail_threshold=-1,
                verbose=False,
            ),
            analysis=cast(
                Any,
                SimpleNamespace(
                    coverage_join=SimpleNamespace(
                        status="invalid",
                        invalid_reason="broken xml",
                    )
                ),
            ),
            processing=cast(Any, Namespace(source_read_failures=[])),
            source_read_contract_failure=False,
            baseline_failure_code=None,
            metrics_baseline_failure_code=None,
            new_func=set(),
            new_block=set(),
            gate_result=GatingResult(0, ()),
            html_report_path=None,
        )
    assert exc.value.code == 2


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


def test_main_impl_debug_sets_env_and_handles_baseline_resolve_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    monkeypatch.delenv("CODECLONE_DEBUG", raising=False)
    bad_baseline = tmp_path / "bad_baseline.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codeclone",
            str(tmp_path),
            "--debug",
            "--baseline",
            str(bad_baseline),
        ],
    )
    monkeypatch.setattr(cli, "load_pyproject_config", lambda _root: {})
    original_resolve = Path.resolve

    def _resolve(self: Path, *, strict: bool = False) -> Path:
        if self == bad_baseline:
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve)
    with pytest.raises(SystemExit) as exc:
        cli._main_impl()
    assert exc.value.code == 2
    assert os.environ.get("CODECLONE_DEBUG") == "1"


def _stub_discovery_result() -> DiscoveryResult:
    return DiscoveryResult(
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
        module_registry=module_registry_context(
            filepath="placeholder.py",
            module_name="placeholder",
        )[1],
    )


def _stub_processing_result() -> ProcessingResult:
    return ProcessingResult(
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
) -> AnalysisResult:
    return AnalysisResult(
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
        observation_bundle=TEST_OBSERVATION_BUNDLE,
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


def test_main_impl_exits_on_pre_analysis_session_stats(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    monkeypatch.setattr(
        sys,
        "argv",
        ["codeclone", str(tmp_path), "--quiet", "--session-stats"],
    )
    monkeypatch.setattr(cli, "load_pyproject_config", lambda _root: {})
    monkeypatch.setattr(
        "codeclone.surfaces.cli.session_stats.render_session_stats",
        lambda **_kwargs: 0,
    )
    with pytest.raises(SystemExit) as exc:
        cli._main_impl()
    assert exc.value.code == 0


def test_main_impl_exits_on_post_analysis_controller_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import codeclone.surfaces.cli.workflow as wf

    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    monkeypatch.setattr(
        sys,
        "argv",
        ["codeclone", str(tmp_path), "--quiet", "--patch-verify"],
    )
    monkeypatch.setattr(cli, "load_pyproject_config", lambda _root: {})
    _patch_main_pipeline_stubs(monkeypatch)
    monkeypatch.setattr(wf, "_run_controller_query", lambda **_kwargs: 3)
    with pytest.raises(SystemExit) as exc:
        cli._main_impl()
    assert exc.value.code == 3


def _prepare_fail_on_new_metrics_case(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> list[str]:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{}", "utf-8")
    return [
        "codeclone",
        str(tmp_path),
        "--quiet",
        "--baseline",
        str(baseline_path),
        "--fail-on-new-metrics",
    ]


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
        ],
    )
    monkeypatch.setattr(cli, "load_pyproject_config", lambda _root: {})
    _patch_main_pipeline_stubs(monkeypatch)
    monkeypatch.setattr(
        cli,
        "gate_with_config",
        lambda **_kwargs: (
            object(),
            GatingResult(
                exit_code=3,
                reasons=(
                    "metric:Health score regressed vs metrics baseline: delta=-1.",
                    "metric:Complexity threshold exceeded: max CC=21, threshold=20.",
                ),
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


def test_main_impl_skip_metrics_defensive_contract_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline_path = tmp_path / "baseline.json"
    _assert_main_impl_exit_code(
        monkeypatch,
        [
            "codeclone",
            str(tmp_path),
            "--quiet",
            "--skip-metrics",
            "--update-baseline",
            "--baseline",
            str(baseline_path),
        ],
        expected_code=2,
        configure_metrics_mode=lambda **_kwargs: None,
    )


def test_main_impl_fail_on_new_metrics_requires_existing_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline_path = tmp_path / "baseline.json"
    _assert_main_impl_exit_code(
        monkeypatch,
        [
            "codeclone",
            str(tmp_path),
            "--quiet",
            "--baseline",
            str(baseline_path),
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


def test_metrics_baseline_runtime_requires_adoption_snapshot_for_regression_gates() -> (
    None
):
    runtime = _metrics_baseline_runtime_for_gate_checks()
    runtime.baseline.has_coverage_adoption_snapshot = False
    printer = _RecordingPrinter()

    cli_baselines_mod._enforce_metrics_gate_schema_requirements(
        args=SimpleNamespace(
            fail_on_typing_regression=True,
            fail_on_docstring_regression=False,
            fail_on_api_break=False,
        ),
        state=runtime,
        console=printer,
    )

    _assert_metrics_gate_schema_contract_error(
        runtime,
        printer,
        expected_fragment="coverage adoption data",
    )


def test_metrics_baseline_runtime_requires_api_surface_snapshot_for_api_gate() -> None:
    runtime = _metrics_baseline_runtime_for_gate_checks()
    runtime.baseline.has_coverage_adoption_snapshot = True
    runtime.baseline.api_surface_snapshot = None
    printer = _RecordingPrinter()

    cli_baselines_mod._enforce_metrics_gate_schema_requirements(
        args=SimpleNamespace(
            fail_on_typing_regression=False,
            fail_on_docstring_regression=False,
            fail_on_api_break=True,
        ),
        state=runtime,
        console=printer,
    )

    _assert_metrics_gate_schema_contract_error(
        runtime,
        printer,
        expected_fragment="public API surface data",
    )


def test_print_verbose_clone_hashes_noop_on_empty() -> None:
    printer = _RecordingPrinter()
    cli_console._print_verbose_clone_hashes(
        printer,
        label="Function clone hashes",
        clone_hashes=set(),
    )
    assert printer.lines == []


def test_print_verbose_clone_hashes_prints_sorted_values() -> None:
    printer = _RecordingPrinter()
    cli_console._print_verbose_clone_hashes(
        printer,
        label="Block clone hashes",
        clone_hashes={"b-hash", "a-hash"},
    )
    assert printer.lines == [
        "\n    Block clone hashes:",
        "      - a-hash",
        "      - b-hash",
    ]


def test_resolve_intent_registry_db_path_maps_repo_path_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.config.intent_registry import (
        IntentRegistryConfigError,
        resolve_intent_registry_db_path,
    )
    from codeclone.utils.repo_paths import RepoPathError

    def _raise_repo_path_error(*_args: object, **_kwargs: object) -> Path:
        raise RepoPathError("invalid segment")

    monkeypatch.setattr(
        "codeclone.config.intent_registry.resolve_under_repo_root",
        _raise_repo_path_error,
    )
    with pytest.raises(IntentRegistryConfigError, match="invalid intent_registry_path"):
        resolve_intent_registry_db_path(
            root_path=tmp_path,
            value=".codeclone/db/intents.sqlite3",
        )


def test_resolve_memory_state_path_maps_repo_path_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.config.memory import _resolve_memory_state_path
    from codeclone.utils.repo_paths import RepoPathError

    root = tmp_path / "repo"
    root.mkdir()

    def _raise_repo_path_error(*_args: object, **_kwargs: object) -> Path:
        raise RepoPathError("invalid segment")

    monkeypatch.setattr(
        "codeclone.config.memory.resolve_under_repo_root",
        _raise_repo_path_error,
    )
    with pytest.raises(
        ValueError, match=r"Invalid tool\.codeclone\.memory\.semantic\.index_path"
    ):
        _resolve_memory_state_path(
            key="memory.semantic.index_path",
            value=".codeclone/memory/semantic_index.lance",
            root_path=root,
        )


def test_fail_on_unresolved_dead_code_flag_is_declared_and_defaults_off() -> None:
    """The abstention gate is opt-in at the CLI surface.

    39Y brief section 6: unresolved_external_override is neither dead nor
    live and is excluded from default dead-code gates, so the flag must parse
    as a bool_optional pair and default to False. The gate-reason behaviour
    itself is asserted in tests/test_gating.py, which is the ring that may
    reach report.gates.evaluator; the Phase 39S boundary ratchet forbids this
    file from importing it.
    """
    parser = build_parser(__version__)

    defaults = parser.parse_args([])
    assert defaults.fail_on_unresolved_dead_code is False

    enabled = parser.parse_args(["--fail-on-unresolved-dead-code"])
    assert enabled.fail_on_unresolved_dead_code is True

    disabled = parser.parse_args(["--no-fail-on-unresolved-dead-code"])
    assert disabled.fail_on_unresolved_dead_code is False

    # Independent of the ordinary dead-code gate in both directions.
    assert defaults.fail_dead_code is False
    assert enabled.fail_dead_code is False
