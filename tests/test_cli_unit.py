import os
import sys
from pathlib import Path

import pytest

import codeclone.cli as cli
from codeclone import __version__
from codeclone.cli import expand_path, process_file
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
    assert "CI preset: --fail-on-new --no-color --quiet." in out
    assert "total clone groups (function +" in out
    assert "block) exceed this number" in out


def test_aligned_summary_lines_empty() -> None:
    assert cli._aligned_summary_lines([]) == []


def test_aligned_summary_lines_non_empty() -> None:
    lines = cli._aligned_summary_lines([("Files found", 12), ("Cache hits", 3)])
    assert len(lines) == 2
    assert "Files found:" in lines[0]
    assert "12" in lines[0]
    assert "Cache hits:" in lines[1]
    assert "3" in lines[1]


def test_print_summary_invariant_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "console", cli._make_console(no_color=True))
    cli._print_summary(
        quiet=False,
        files_found=1,
        files_parsed=0,
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
