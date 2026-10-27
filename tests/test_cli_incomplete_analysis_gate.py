# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A gate never passes over an analysis that skipped a file it found.

A file that was found but could not be read or analysed -- a parse error, a
file over the size limit, an internal error, a file that vanished between the
walk and its stat -- is missing from every finding and metric. Before 2.0.3
only unreadable files stopped a gated run; a file the parser rejected was
skipped silently and ``--ci`` passed over what remained. In gating mode the
run now ends with the existing contract error (exit 2) whatever the reason.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Concatenate, ParamSpec, TypeVar

import pytest

import codeclone.core.discovery as core_discovery
import codeclone.core.worker as core_worker
import codeclone.qualnames as qualnames_module
from codeclone.analysis.units import extract_units_and_stats_from_source
from codeclone.cache.store import file_stat_signature
from codeclone.core._types import FileProcessResult
from tests._cli_inprocess_run import flat, run_cli

_CLEAN = "def used(x):\n    return x + 1\n\n\nprint(used(1))\n"
_DEAD = "def never_called(x):\n    return x * 2\n"
_SYNTAX_ERROR = "def broken(:\n    pass\n"
_HEADLINE = "could not be read in CI/gating mode or could not be analyzed"


_flat = flat
_run_cli = run_cli


def _repo(tmp_path: Path, **files: str) -> Path:
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    for name, text in files.items():
        (repo / "pkg" / f"{name}.py").write_text(text, encoding="utf-8")
    return repo


def _skip_by_parse_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, str]:
    return _repo(tmp_path, clean=_CLEAN, broken=_SYNTAX_ERROR), "broken.py"


_P = ParamSpec("_P")
_R = TypeVar("_R")
_MakeRepo = Callable[[pytest.MonkeyPatch, Path], tuple[Path, str]]


def _raising_for(name: str, real: Callable[_P, _R]) -> Callable[_P, _R]:
    """*real*, except that it fails like a worker bug for the file *name*."""

    def _probe(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        if str(kwargs.get("filepath", "")).endswith(name):
            raise RuntimeError("worker failure probe")
        return real(*args, **kwargs)

    return _probe


def _unexplained_failure_for(
    name: str, real: Callable[Concatenate[str, _P], FileProcessResult]
) -> Callable[Concatenate[str, _P], FileProcessResult]:
    """*real*, except that the file *name* fails without any reason given."""

    def _probe(
        filepath: str, /, *args: _P.args, **kwargs: _P.kwargs
    ) -> FileProcessResult:
        if filepath.endswith(name):
            return FileProcessResult(filepath=filepath, success=False, error="?")
        return real(filepath, *args, **kwargs)

    return _probe


def _skip_by_size(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, str]:
    repo = _repo(tmp_path, clean=_CLEAN, huge="x = 1\n" * 40)
    monkeypatch.setattr(core_worker, "MAX_FILE_SIZE", 120)
    return repo, "huge.py"


def _skip_by_internal_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, str]:
    repo = _repo(tmp_path, clean=_CLEAN, boom="y = 2\n")
    monkeypatch.setattr(
        core_worker,
        "extract_units_and_stats_from_source",
        _raising_for("boom.py", extract_units_and_stats_from_source),
    )
    return repo, "boom.py"


def _skip_at_discovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, str]:
    repo = _repo(tmp_path, clean=_CLEAN, gone="z = 3\n")

    def _stat(filepath: str) -> object:
        if filepath.endswith("gone.py"):
            raise OSError("vanished between the walk and its stat")
        return file_stat_signature(filepath)

    monkeypatch.setattr(core_discovery, "file_stat_signature", _stat)
    return repo, "gone.py"


def _skip_by_parse_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, str]:
    # A parse that ran out of time is a resource limit, not a proven syntax
    # rejection of the file.
    import codeclone.analysis.parser as analysis_parser
    import codeclone.analysis.units as analysis_units
    from codeclone.contracts.errors import ParseError

    repo = _repo(tmp_path, clean=_CLEAN, slow="w = 4\n")
    real = analysis_parser._parse_with_limits

    def _parse(source: str, timeout_s: int) -> object:
        if "w = 4" in source:
            # The shape analysis/parser.py gives a parse that ran out of time.
            timeout = analysis_parser._ParseTimeoutError("AST parsing timeout")
            raise ParseError(str(timeout)) from timeout
        return real(source, timeout_s)

    monkeypatch.setattr(analysis_units, "_parse_with_limits", _parse)
    return repo, "slow.py"


def _skip_with_no_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, str]:
    repo = _repo(tmp_path, clean=_CLEAN, odd="v = 5\n")
    monkeypatch.setattr(
        core_worker,
        "process_file",
        _unexplained_failure_for("odd.py", core_worker.process_file),
    )
    return repo, "odd.py"


def _gated_run_excluding(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    repo: Path,
    excluded: str,
) -> tuple[int, str]:
    """A ``--fail-dead-code`` run that names *excluded*; exit code and output."""

    code = _run_cli(
        monkeypatch,
        repo,
        ".",
        "--no-progress",
        "--fail-dead-code",
        "--allow-syntax-error",
        excluded,
    )
    return code, _flat(capsys.readouterr().out)


_SKIP_CAUSES = (
    pytest.param(_skip_by_parse_error, id="parse-error"),
    pytest.param(_skip_by_size, id="file-too-large"),
    pytest.param(_skip_by_internal_error, id="internal-error"),
    pytest.param(_skip_at_discovery, id="discovery-stat-error"),
)


@pytest.mark.parametrize("make_repo", _SKIP_CAUSES)
def test_gated_run_over_a_skipped_file_is_a_contract_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make_repo: _MakeRepo,
) -> None:
    repo, skipped = make_repo(monkeypatch, tmp_path)

    code = _run_cli(monkeypatch, repo, ".", "--no-progress", "--fail-dead-code")

    output = _flat(capsys.readouterr().out)
    assert code == 2, output
    refusal = output[output.index("CONTRACT ERROR:") :]
    assert _HEADLINE in refusal
    assert "Source files not analyzed: 1." in refusal
    assert skipped in refusal


def test_ci_run_over_a_file_that_does_not_parse_is_a_contract_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, clean=_CLEAN, broken=_SYNTAX_ERROR)
    assert _run_cli(monkeypatch, repo, ".", "--no-progress", "--update-baseline") == 0
    capsys.readouterr()

    code = _run_cli(monkeypatch, repo, ".", "--ci")

    output = _flat(capsys.readouterr().out)
    assert code == 2, output
    assert _HEADLINE in output


def test_incomplete_analysis_wins_over_a_gating_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The dead code the gate would report is real, but a gate over a partial
    # population is not evaluated at all: contract error, not gating failure.
    repo = _repo(tmp_path, dead=_DEAD, broken=_SYNTAX_ERROR)

    code = _run_cli(monkeypatch, repo, ".", "--no-progress", "--fail-dead-code")

    output = capsys.readouterr().out
    assert code == 2, output
    assert "GATING FAILURE" not in output


def test_dead_code_gate_still_fails_on_a_complete_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, dead=_DEAD)

    code = _run_cli(monkeypatch, repo, ".", "--no-progress", "--fail-dead-code")

    output = _flat(capsys.readouterr().out)
    assert code == 3, output
    assert _HEADLINE not in output


def test_gated_run_over_a_complete_analysis_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, clean=_CLEAN)

    code = _run_cli(monkeypatch, repo, ".", "--no-progress", "--fail-dead-code")

    output = _flat(capsys.readouterr().out)
    assert code == 0, output
    assert _HEADLINE not in output


def test_ungated_run_over_a_skipped_file_warns_and_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, clean=_CLEAN, broken=_SYNTAX_ERROR)

    code = _run_cli(monkeypatch, repo, ".", "--no-progress")

    output = capsys.readouterr().out
    assert code == 0, output
    assert "CONTRACT ERROR" not in output
    assert "broken.py" in output


def test_baseline_update_over_a_skipped_file_is_not_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Same exclusion as the unreadable-source rule: writing a baseline is not
    # a gate verdict.
    repo = _repo(tmp_path, clean=_CLEAN, broken=_SYNTAX_ERROR)

    code = _run_cli(
        monkeypatch, repo, ".", "--no-progress", "--fail-dead-code", "--update-baseline"
    )

    output = _flat(capsys.readouterr().out)
    assert code == 0, output
    assert _HEADLINE not in output


def test_gated_run_lists_every_skipped_file_with_an_overflow_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    files = {f"broken{index:02d}": _SYNTAX_ERROR for index in range(12)}
    repo = _repo(tmp_path, clean=_CLEAN, **files)

    code = _run_cli(
        monkeypatch,
        repo,
        ".",
        "--no-progress",
        "--processes",
        "1",
        "--fail-dead-code",
    )

    output = capsys.readouterr().out
    assert code == 2, output
    refusal = output[output.index("CONTRACT ERROR:") :]
    assert "Source files not analyzed: 12." in _flat(refusal)
    assert sum(line.startswith("  • ") for line in refusal.splitlines()) == 10
    assert "  ... and 2 more" in refusal.splitlines()


def test_syntax_error_named_by_the_caller_is_excluded_and_listed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, clean=_CLEAN, broken=_SYNTAX_ERROR)

    code = _run_cli(
        monkeypatch,
        repo,
        ".",
        "--no-progress",
        "--fail-dead-code",
        "--allow-syntax-error",
        "pkg/broken.py",
    )

    stdout = capsys.readouterr().out
    assert code == 0, stdout
    assert _HEADLINE not in _flat(stdout)
    lines = stdout.splitlines()
    block = lines[lines.index("Analysis scope: 2 files") :][:6]
    assert block == [
        "Analysis scope: 2 files",
        "Analyzed:       1",
        "Excluded:       1 (explicitly authorized)",
        "Full scope verified: NO",
        "Excluded:",
        "  pkg/broken.py",
    ]
    assert "Gate: PASS for analyzed scope." in _flat(stdout)


def test_excluded_syntax_error_does_not_hide_another_unanalysed_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, clean=_CLEAN, broken=_SYNTAX_ERROR, other=_SYNTAX_ERROR)

    code, output = _gated_run_excluding(monkeypatch, capsys, repo, "pkg/broken.py")
    assert code == 2, output
    refusal = output[output.index("CONTRACT ERROR:") :]
    assert "Source files not analyzed: 1." in refusal
    assert "other.py" in refusal
    assert "broken.py" not in refusal


@pytest.mark.parametrize(
    ("make_repo", "reason"),
    [
        pytest.param(_skip_by_size, "file_too_large", id="file-too-large"),
        pytest.param(_skip_by_internal_error, "unexpected_error", id="internal-error"),
        pytest.param(_skip_by_parse_timeout, "parse_timeout", id="parse-timeout"),
        pytest.param(_skip_with_no_reason, "unknown", id="no-named-reason"),
        pytest.param(_skip_at_discovery, None, id="discovery-stat-error"),
    ],
)
def test_exclusion_never_covers_a_reason_other_than_syntax(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make_repo: _MakeRepo,
    reason: str | None,
) -> None:
    repo, skipped = make_repo(monkeypatch, tmp_path)

    code, output = _gated_run_excluding(monkeypatch, capsys, repo, f"pkg/{skipped}")
    if reason is not None:
        assert f"because of {reason}, which cannot be excluded" in output
    assert code == 2, output
    assert _HEADLINE in output
    assert "excluded by --allow-syntax-error" not in output


def test_exclusion_is_never_read_from_the_repository_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, clean=_CLEAN, broken=_SYNTAX_ERROR)
    (repo / "pyproject.toml").write_text(
        '[tool.codeclone]\nallow_syntax_error = ["pkg/broken.py"]\n',
        encoding="utf-8",
    )

    code = _run_cli(monkeypatch, repo, ".", "--no-progress", "--fail-dead-code")

    output = _flat(capsys.readouterr().out)
    assert code == 2, output
    assert "Unknown key(s) in tool.codeclone: allow_syntax_error" in output


def test_exclusion_outside_the_root_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, clean=_CLEAN)

    code = _run_cli(
        monkeypatch,
        repo,
        ".",
        "--no-progress",
        "--allow-syntax-error",
        str(tmp_path / "elsewhere.py"),
    )

    output = _flat(capsys.readouterr().out)
    assert code == 2, output
    assert "it is not inside the analysed root" in output


def test_unused_exclusion_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, clean=_CLEAN)

    code, output = _gated_run_excluding(monkeypatch, capsys, repo, "pkg/clean.py")
    assert code == 0, output
    assert "--allow-syntax-error pkg/clean.py this file was analyzed" in output


def test_worker_names_a_syntax_error_and_the_interpreter(tmp_path: Path) -> None:

    source = tmp_path / "bad.py"
    source.write_text(_SYNTAX_ERROR, encoding="utf-8")

    result = _process_alone(source, tmp_path)

    assert result.success is False
    assert result.error_kind == "syntax_error"
    assert result.error is not None
    assert result.error.startswith(
        f"Syntax error under Python {sys.version_info.major}.{sys.version_info.minor}: "
    )


@pytest.mark.parametrize(
    ("spelling", "reason"),
    [
        pytest.param("pkg/missing.py", "not a file this run found", id="no-such-file"),
        pytest.param("pkg", "not a file this run found", id="a-directory"),
        pytest.param("pkg/*.py", "not a file this run found", id="a-glob"),
        pytest.param("pkg/../pkg/broken.py", "'..' is not accepted", id="dot-dot"),
    ],
)
def test_exclusion_that_names_no_single_discovered_file_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    spelling: str,
    reason: str,
) -> None:
    repo = _repo(tmp_path, clean=_CLEAN, broken=_SYNTAX_ERROR)

    code = _run_cli(
        monkeypatch,
        repo,
        ".",
        "--no-progress",
        "--allow-syntax-error",
        spelling,
    )

    output = _flat(capsys.readouterr().out)
    assert code == 2, output
    assert f"--allow-syntax-error {spelling} is refused" in output
    assert reason in output


@pytest.mark.skipif(os.name == "nt", reason="symbolic links need privileges")
def test_exclusion_through_a_link_leading_outside_the_root_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, clean=_CLEAN)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "broken.py").write_text(_SYNTAX_ERROR, encoding="utf-8")
    (repo / "pkg" / "linked.py").symlink_to(outside / "broken.py")

    code = _run_cli(
        monkeypatch,
        repo,
        ".",
        "--no-progress",
        "--allow-syntax-error",
        "pkg/linked.py",
    )

    output = _flat(capsys.readouterr().out)
    assert code == 2, output
    assert "not a file this run found" in output


def _process_alone(source: Path, root: Path) -> FileProcessResult:
    """One worker call on *source*, the way the pipeline makes it."""

    from codeclone.analysis.normalizer import NormalizationConfig

    return core_worker.process_file(str(source), str(root), NormalizationConfig(), 1, 1)


def test_syntax_error_raised_inside_codeclone_is_not_a_file_syntax_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Only the parse of the file's own text proves a syntax rejection: a
    # SyntaxError from CodeClone's later work on a parsed tree is unknown.

    source = tmp_path / "fine.py"
    source.write_text("def f():\n    return 1\n", encoding="utf-8")

    class _Collector:
        def visit(self, _tree: object) -> None:
            raise SyntaxError("raised by CodeClone, not by the file")

    monkeypatch.setattr(
        qualnames_module,
        "QualnameCollector",
        _Collector,
    )

    result = _process_alone(source, tmp_path)

    assert result.success is False
    assert result.error_kind == "unexpected_error"


def test_worker_names_a_parse_timeout_as_its_own_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import codeclone.analysis.parser as analysis_parser
    import codeclone.analysis.units as analysis_units

    source = tmp_path / "slow.py"
    source.write_text("x = 1\n", encoding="utf-8")

    def _timeout(_source: str, _timeout_s: int) -> object:
        try:
            raise analysis_parser._ParseTimeoutError("AST parsing timeout")
        except analysis_parser._ParseTimeoutError as exc:
            from codeclone.contracts.errors import ParseError

            raise ParseError(str(exc)) from exc

    monkeypatch.setattr(analysis_units, "_parse_with_limits", _timeout)

    result = _process_alone(source, tmp_path)

    assert result.success is False
    assert result.error_kind == "parse_timeout"


_HOSTILE_FIXTURE = "evil`<img src=x onerror=alert(1)>`\n## Verdict: ALL GATES PASSED.py"


@pytest.mark.skipif(os.name == "nt", reason="file names with a newline are POSIX-only")
def test_every_representation_names_the_exclusion_and_keeps_it_inert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json
    import re

    from markdown_it import MarkdownIt

    repo = _repo(tmp_path, clean=_CLEAN)
    (repo / "pkg" / _HOSTILE_FIXTURE).write_text(_SYNTAX_ERROR, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    reports = {
        "json": out / "r.json",
        "md": out / "r.md",
        "html": out / "r.html",
        "text": out / "r.txt",
    }

    code = _run_cli(
        monkeypatch,
        repo,
        ".",
        "--no-progress",
        "--fail-dead-code",
        "--allow-syntax-error",
        f"pkg/{_HOSTILE_FIXTURE}",
        *(arg for kind, path in reports.items() for arg in (f"--{kind}", str(path))),
    )

    stdout = capsys.readouterr().out
    assert code == 0, stdout
    relative = f"pkg/{_HOSTILE_FIXTURE}"

    # JSON: the evidence of the exclusion, with its reason and authority.
    document = json.loads(reports["json"].read_text(encoding="utf-8"))
    assert document["report_schema_version"] == "2.12"
    assert document["inventory"]["files"] == {
        "total_found": 2,
        "analyzed": 1,
        "cached": 0,
        "skipped": 1,
        "source_io_skipped": 0,
        "verified": 1,
        "excluded": 1,
        "full_scope_verified": False,
    }
    assert document["inventory"]["excluded_files"] == [
        {
            "path": relative,
            "reason": "syntax_error",
            "authorized_by": "--allow-syntax-error",
        }
    ]

    # CLI: the scope block, with the newline of the name made visible.
    lines = stdout.splitlines()
    block = lines[lines.index("Analysis scope: 2 files") :][:6]
    assert block[1:5] == [
        "Analyzed:       1",
        "Excluded:       1 (explicitly authorized)",
        "Full scope verified: NO",
        "Excluded:",
    ]
    assert block[5] == "  pkg/" + _HOSTILE_FIXTURE.replace("\n", "\u240a")
    assert "Gate: PASS for analyzed scope." in stdout

    # Markdown: the scope block, the name inert inside one code span.
    markdown = reports["md"].read_text(encoding="utf-8")
    assert "- Full scope verified: NO" in markdown
    assert "- Excluded: 1 (explicitly authorized)" in markdown
    tokens = []
    for token in MarkdownIt("commonmark").parse(markdown):
        tokens.append(token)
        tokens.extend(token.children or ())
    owner_anchor = re.compile(r'<a id="[a-z0-9-]+">(</a>)?|</a>')
    assert [
        token.content
        for token in tokens
        if token.type in {"html_inline", "html_block"}
        and not owner_anchor.fullmatch(token.content.strip())
    ] == []
    assert not [line for line in markdown.splitlines() if line.startswith("## Verdict")]
    assert any(
        "<img src=x onerror=alert(1)>" in token.content
        for token in tokens
        if token.type == "code_inline"
    )

    # HTML: escaped, never live.
    html = reports["html"].read_text(encoding="utf-8")
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "Full scope verified" in html

    # Text: one line per excluded file, the newline replaced.
    text = reports["text"].read_text(encoding="utf-8")
    assert "Full scope verified: NO" in text
    assert not [line for line in text.splitlines() if line.startswith("## Verdict")]
    assert "␊## Verdict" in text


def test_report_without_exclusions_says_nothing_was_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    repo = _repo(tmp_path, clean=_CLEAN)
    report = tmp_path / "r.json"

    code = _run_cli(monkeypatch, repo, ".", "--no-progress", "--json", str(report))

    assert code == 0
    document = json.loads(report.read_text(encoding="utf-8"))
    files = document["inventory"]["files"]
    assert files["excluded"] == 0
    assert files["verified"] == 1
    assert files["full_scope_verified"] is True
    assert document["inventory"]["excluded_files"] == []


def test_report_of_an_ungated_run_with_a_skipped_file_is_not_fully_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    repo = _repo(tmp_path, clean=_CLEAN, broken=_SYNTAX_ERROR)
    report = tmp_path / "r.json"

    code = _run_cli(monkeypatch, repo, ".", "--no-progress", "--json", str(report))

    assert code == 0
    files = json.loads(report.read_text(encoding="utf-8"))["inventory"]["files"]
    assert files["full_scope_verified"] is False
    assert files["excluded"] == 0


def test_parse_error_that_is_neither_syntax_nor_timeout_stays_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ast

    import codeclone.analysis.units as analysis_units

    source = tmp_path / "odd.py"
    source.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        analysis_units,
        "_parse_with_limits",
        lambda _source, _timeout: ast.Expression(body=ast.Constant(value=1)),
    )

    result = _process_alone(source, tmp_path)

    assert result.success is False
    assert result.error_kind == "unexpected_error"
    assert result.error is not None
    assert "expected module AST root" in result.error


@pytest.mark.skipif(os.name == "nt", reason="file names with a newline are POSIX-only")
def test_sarif_names_the_exclusion_in_the_invocation_and_keeps_it_inert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    repo = _repo(tmp_path, clean=_CLEAN)
    (repo / "pkg" / _HOSTILE_FIXTURE).write_text(_SYNTAX_ERROR, encoding="utf-8")
    sarif_path = tmp_path / "r.sarif"

    code = _run_cli(
        monkeypatch,
        repo,
        ".",
        "--no-progress",
        "--fail-dead-code",
        "--allow-syntax-error",
        f"pkg/{_HOSTILE_FIXTURE}",
        "--sarif",
        str(sarif_path),
    )

    assert code == 0
    invocation = json.loads(sarif_path.read_text(encoding="utf-8"))["runs"][0][
        "invocations"
    ][0]
    assert invocation["executionSuccessful"] is True
    assert invocation["properties"] == {"fullScopeVerified": False, "excludedFiles": 1}
    [notification] = invocation["toolExecutionNotifications"]
    assert notification["level"] == "warning"
    assert notification["descriptor"] == {"id": "codeclone/excluded-from-analysis"}
    text = notification["message"]["text"]
    assert "\n" not in text
    assert "pkg/evil`<img src=x onerror=alert(1)>`␊## Verdict" in text
    uri = notification["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert uri == (
        "pkg/evil%60%3Cimg%20src%3Dx%20onerror%3Dalert%281%29%3E%60"
        "%0A%23%23%20Verdict%3A%20ALL%20GATES%20PASSED.py"
    )


def test_sarif_of_a_fully_verified_run_says_so(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    repo = _repo(tmp_path, clean=_CLEAN)
    sarif_path = tmp_path / "r.sarif"

    code = _run_cli(monkeypatch, repo, ".", "--no-progress", "--sarif", str(sarif_path))

    assert code == 0
    invocation = json.loads(sarif_path.read_text(encoding="utf-8"))["runs"][0][
        "invocations"
    ][0]
    assert invocation["properties"] == {"fullScopeVerified": True, "excludedFiles": 0}
    assert "toolExecutionNotifications" not in invocation
