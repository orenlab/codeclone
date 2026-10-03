# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Paths an analysed repository chooses for itself stay inside it.

Security review 2026-10 (A-01, A-02, A-04, A-05, D-02), rebuilt from the
reviewer's reproductions. A repository whose ``pyproject.toml`` named report
or baseline files outside itself made a plain ``codeclone .`` overwrite files
the user owns and create directories next to them; a report path that was a
symbolic link inside the repository reached a file of any name; a committed
link in place of the cache database turned a file outside the repository into
a cache store.

The model these tests pin: a path from the repository's own configuration is
the repository author's word and must resolve inside the repository; a path
typed on the command line is the user's word and may point anywhere; a report
is never written through a symbolic link, whoever named it. Every victim is a
plain file under the test's temporary directory, and ``HOME`` points there
too, so the ``~`` spelling has a victim of its own.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

import codeclone.surfaces.cli.workflow as cli
from tests._assertions import strip_ansi

_SOURCE = (
    "def alpha(x):\n    y = x + 1\n    if y > 3:\n        return y * 2\n    return y\n"
)
_SCOPE_ID = "3b105a97-6476-4760-bc0b-a294370f731c"
_VICTIM_FILES = {
    "Documents/notes.md": "MY PRECIOUS NOTES\n",
    "Documents/settings.json": '{"editor.fontSize": 14}\n',
    "Documents/todo.txt": "todo list\n",
    ".claude/CLAUDE.md": "my own agent instructions\n",
    "dotrc": "export PATH=/usr/bin\n",
}


@dataclass(frozen=True, slots=True)
class _Sandbox:
    repo: Path
    victim: Path


def _sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str = ""
) -> _Sandbox:
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("", "utf-8")
    (repo / "pkg" / "a.py").write_text(_SOURCE, "utf-8")
    (repo / "pkg" / "b.py").write_text(_SOURCE.replace("alpha", "beta"), "utf-8")
    (repo / "pyproject.toml").write_text(
        "[tool.codeclone]\nmin_loc = 1\nmin_stmt = 1\n"
        f'baseline_scope_id = "{_SCOPE_ID}"\n{config}',
        "utf-8",
    )
    victim = tmp_path / "victim_home"
    for relative, text in _VICTIM_FILES.items():
        (victim / relative).parent.mkdir(parents=True, exist_ok=True)
        (victim / relative).write_text(text, "utf-8")
    monkeypatch.setenv("HOME", str(victim))
    monkeypatch.chdir(repo)
    return _Sandbox(repo=repo, victim=victim)


def _tree(directory: Path) -> dict[str, bytes | None]:
    """Every entry under *directory*: a file's bytes, ``None`` for a directory."""

    return {
        entry.relative_to(directory).as_posix(): (
            None if entry.is_dir() else entry.read_bytes()
        )
        for entry in sorted(directory.rglob("*"))
    }


def _codeclone(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *flags: str,
) -> tuple[int, str]:
    monkeypatch.setattr(sys, "argv", ["codeclone", ".", "--no-progress", *flags])
    try:
        cli.main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    else:
        code = 0
    return code, _squash(strip_ansi(capsys.readouterr().out))


def _squash(text: str) -> str:
    """Drop every whitespace character: the console folds long paths mid-word."""

    return "".join(text.split())


# -- A-01 / D-02: report paths from the repository's pyproject ---------------


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("md_out", "{victim}/Documents/notes.md"),
        ("json_out", "../victim_home/Documents/settings.json"),
        ("text_out", "{victim}/new/dir/r.txt"),
        ("html_out", "../victim_home/r.html"),
        ("sarif_out", "../victim_home/new/r.sarif"),
        ("md_out", "~/.claude/CLAUDE.md"),
    ],
    ids=["absolute", "parent", "new-dirs", "html", "sarif", "tilde"],
)
def test_report_path_from_pyproject_outside_repository_is_refused_before_any_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    key: str,
    value: str,
) -> None:
    victim = tmp_path / "victim_home"
    spelled = value.format(victim=victim)
    box = _sandbox(tmp_path, monkeypatch, f'{key} = "{spelled}"\n')
    before = _tree(box.victim)

    code, out = _codeclone(monkeypatch, capsys)

    assert code == 2, out
    assert _tree(box.victim) == before
    assert not (box.repo / ".codeclone").exists()
    assert _squash(f"tool.codeclone.{key} = '{spelled}' must stay under the") in out


def test_report_path_from_pyproject_inside_repository_is_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    box = _sandbox(
        tmp_path,
        monkeypatch,
        'md_out = "reports/notes.md"\n'
        f'json_out = "{tmp_path}/repo/reports/settings.json"\n'
        'text_out = "reports/../reports/todo.txt"\n',
    )
    before = _tree(box.victim)

    code, out = _codeclone(monkeypatch, capsys)

    assert code == 0, out
    assert sorted(_tree(box.repo / "reports")) == [
        "notes.md",
        "settings.json",
        "todo.txt",
    ]
    assert _tree(box.victim) == before


def test_report_path_on_the_command_line_outside_repository_is_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    box = _sandbox(tmp_path, monkeypatch)
    linked = tmp_path / "linked"
    linked.symlink_to(box.victim / "Documents", target_is_directory=True)

    code, out = _codeclone(
        monkeypatch,
        capsys,
        "--md",
        str(box.victim / "out" / "notes.md"),
        "--json",
        "../victim_home/settings-from-flag.json",
        "--html",
        str(linked / "fresh.html"),
    )

    assert code == 0, out
    assert (
        (box.victim / "out" / "notes.md").read_text("utf-8").startswith("# CodeClone")
    )
    assert (box.victim / "settings-from-flag.json").read_text("utf-8").startswith("{")
    assert (box.victim / "Documents" / "fresh.html").is_file()


def test_report_path_without_an_allowed_suffix_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    box = _sandbox(tmp_path, monkeypatch)
    before = _tree(box.victim)

    code, out = _codeclone(monkeypatch, capsys, "--text", str(box.victim / "dotrc"))

    assert code == 2, out
    assert _squash("Invalid text output extension") in out
    assert _tree(box.victim) == before


# -- A-02: the report path is checked as it resolves, not as it is spelled ---


def test_report_path_from_pyproject_through_symlink_to_outside_file_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    box = _sandbox(tmp_path, monkeypatch, 'text_out = "reports/out.txt"\n')
    (box.repo / "reports").mkdir()
    (box.repo / "reports" / "out.txt").symlink_to(box.victim / "dotrc")
    before = _tree(box.victim)

    code, out = _codeclone(monkeypatch, capsys)

    assert code == 2, out
    assert _tree(box.victim) == before


def test_report_path_from_pyproject_under_symlinked_directory_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    box = _sandbox(tmp_path, monkeypatch, 'text_out = "reports/out.txt"\n')
    (box.repo / "reports").symlink_to(
        box.victim / "Documents", target_is_directory=True
    )
    before = _tree(box.victim)

    code, out = _codeclone(monkeypatch, capsys)

    assert code == 2, out
    assert _tree(box.victim) == before
    assert _squash("tool.codeclone.text_out = 'reports/out.txt' must stay under") in out


@pytest.mark.parametrize(
    ("target", "said"),
    [
        ("Documents/todo.txt", ("Invalid text output path", "it is a symbolic link")),
        ("dotrc", ()),
    ],
    ids=["allowed-suffix", "no-suffix"],
)
def test_report_path_on_the_command_line_through_planted_symlink_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: str,
    said: tuple[str, ...],
) -> None:
    box = _sandbox(tmp_path, monkeypatch)
    (box.repo / "reports").mkdir()
    (box.repo / "reports" / "out.txt").symlink_to(box.victim / target)
    before = _tree(box.victim)

    code, out = _codeclone(monkeypatch, capsys, "--text", "reports/out.txt")

    assert code == 2, out
    assert _tree(box.victim) == before
    for sentence in said:
        assert _squash(sentence) in out


# -- A-05: the baseline path from the repository's pyproject -----------------


def test_baseline_from_pyproject_outside_repository_is_not_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    planted = tmp_path / "victim_home" / "a" / "b" / "c" / "planted.json"
    box = _sandbox(
        tmp_path, monkeypatch, f'baseline = "{planted}"\nupdate_baseline = true\n'
    )
    before = _tree(box.victim)

    code, out = _codeclone(monkeypatch, capsys)

    assert code == 2, out
    assert _tree(box.victim) == before
    assert _squash(f"tool.codeclone.baseline = '{planted}' must stay under") in out


def test_baseline_from_pyproject_inside_repository_is_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    box = _sandbox(
        tmp_path,
        monkeypatch,
        'baseline = "codeclone.baseline.json"\nupdate_baseline = true\n',
    )

    code, out = _codeclone(monkeypatch, capsys)

    assert code == 0, out
    assert (box.repo / "codeclone.baseline.json").is_file()


def test_baseline_on_the_command_line_outside_repository_is_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    box = _sandbox(tmp_path, monkeypatch)
    chosen = box.victim / "baselines" / "mine.json"

    code, out = _codeclone(
        monkeypatch, capsys, "--baseline", str(chosen), "--update-baseline"
    )

    assert code == 0, out
    assert chosen.is_file()


# -- the other path keys of [tool.codeclone] ----------------------------------


@pytest.mark.parametrize(
    ("key", "relative"),
    [("cache_path", "cache.sqlite3"), ("coverage_xml", "coverage.xml")],
)
def test_service_path_from_pyproject_outside_repository_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    key: str,
    relative: str,
) -> None:
    outside = tmp_path / "victim_home" / relative
    box = _sandbox(tmp_path, monkeypatch, f'{key} = "{outside}"\n')
    before = _tree(box.victim)

    code, out = _codeclone(monkeypatch, capsys)

    assert code == 2, out
    assert _tree(box.victim) == before
    assert _squash(f"tool.codeclone.{key} = '{outside}' must stay under") in out


# -- A-04: the cache database behind a committed symbolic link ---------------


def test_cache_database_behind_a_committed_symlink_is_not_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    box = _sandbox(tmp_path, monkeypatch)
    victim_db = box.victim / "important.dat"
    victim_db.write_bytes(b"")
    (box.repo / ".codeclone" / "db").mkdir(parents=True)
    (box.repo / ".codeclone" / "db" / "cache.sqlite3").symlink_to(victim_db)
    before = _tree(box.victim)

    code, out = _codeclone(monkeypatch, capsys)

    assert code == 0, out
    assert _tree(box.victim) == before
    assert (box.repo / ".codeclone" / "db" / "cache.sqlite3").is_symlink()
