import os
import sys
from pathlib import Path
from typing import cast

import pytest
from rich.text import Text

import codeclone._cli_summary as cli_summary
import codeclone.cli as cli
from codeclone import __version__
from codeclone import ui_messages as ui
from codeclone._cli_args import build_parser
from codeclone._cli_paths import expand_path
from codeclone.cli import process_file
from codeclone.contracts import DOCS_URL, ISSUES_URL, REPOSITORY_URL
from codeclone.normalize import NormalizationConfig


def test_expand_path() -> None:
    p = expand_path(".")
    assert isinstance(p, Path)


def test_process_file_stat_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    def _boom(_path: str) -> int:
        raise OSError("nope")

    monkeypatch.setattr(os.path, "getsize", _boom)
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

    monkeypatch.setattr(cli, "extract_units_from_source", _boom)
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
    assert "Default:" in out
    assert "<root>/.cache/codeclone/cache.json" in out
    assert "Legacy alias for --cache-path" in out
    assert "--max-baseline-size-mb MB" in out
    assert "--max-cache-size-mb MB" in out
    assert "--debug" in out
    assert "CI preset: --fail-on-new --no-color --quiet." in out
    assert "total clone groups (function +" in out
    assert "block) exceed this number" in out
    assert "Exit codes" in out
    assert "0 - success" in out
    assert "2 - contract error" in out
    assert "baseline missing/untrusted" in out
    assert "invalid output extensions" in out
    assert "3 - gating failure" in out
    assert "new clones detected" in out
    assert "threshold exceeded" in out
    assert "5 - internal error" in out
    assert "please report" in out
    assert f"Repository: {REPOSITORY_URL}" in out
    assert f"Issues: {ISSUES_URL}" in out
    assert f"Docs: {DOCS_URL}" in out
    assert "\x1b[" not in out


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


def test_summary_value_style_mapping() -> None:
    assert (
        cli_summary._summary_value_style(label=ui.SUMMARY_LABEL_FUNCTION, value=0)
        == "dim"
    )
    assert (
        cli_summary._summary_value_style(label=ui.SUMMARY_LABEL_FUNCTION, value=2)
        == "bold yellow"
    )
    assert (
        cli_summary._summary_value_style(label=ui.SUMMARY_LABEL_SUPPRESSED, value=1)
        == "yellow"
    )
    assert (
        cli_summary._summary_value_style(label=ui.SUMMARY_LABEL_NEW_BASELINE, value=3)
        == "bold red"
    )


def test_build_summary_table_rows_and_styles() -> None:
    rows = cli_summary._build_summary_rows(
        files_found=2,
        files_analyzed=0,
        cache_hits=2,
        files_skipped=0,
        func_clones_count=1,
        block_clones_count=0,
        segment_clones_count=0,
        suppressed_segment_groups=1,
        new_clones_count=1,
    )
    table = cli_summary._build_summary_table(rows)
    assert table.title == ui.SUMMARY_TITLE
    assert table.columns[0]._cells == [label for label, _ in rows]
    value_cells = table.columns[1]._cells
    assert isinstance(value_cells[0], Text)
    assert str(value_cells[0]) == "2"
    assert cast(Text, value_cells[1]).style == "dim"
    assert cast(Text, value_cells[7]).style == "yellow"
    assert cast(Text, value_cells[8]).style == "bold red"


def test_build_summary_rows_order() -> None:
    rows = cli_summary._build_summary_rows(
        files_found=1,
        files_analyzed=1,
        cache_hits=0,
        files_skipped=0,
        func_clones_count=0,
        block_clones_count=0,
        segment_clones_count=0,
        suppressed_segment_groups=0,
        new_clones_count=0,
    )
    labels = [label for label, _ in rows]
    assert labels == [
        ui.SUMMARY_LABEL_FILES_FOUND,
        ui.SUMMARY_LABEL_FILES_ANALYZED,
        ui.SUMMARY_LABEL_CACHE_HITS,
        ui.SUMMARY_LABEL_FILES_SKIPPED,
        ui.SUMMARY_LABEL_FUNCTION,
        ui.SUMMARY_LABEL_BLOCK,
        ui.SUMMARY_LABEL_SEGMENT,
        ui.SUMMARY_LABEL_SUPPRESSED,
        ui.SUMMARY_LABEL_NEW_BASELINE,
    ]


def test_print_summary_invariant_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    cli_summary._print_summary(
        console=cli.console,
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
