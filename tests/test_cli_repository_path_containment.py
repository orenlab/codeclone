# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A repository's own configuration never writes or reads outside it.

The analysed repository is someone else's text. Its ``pyproject.toml`` and the
links it commits must not make a plain ``codeclone .`` write a report or a
baseline over a file elsewhere on disk, or read a file from there. A path the
user types on the command line is the user's own word and keeps working
wherever it points -- unless a link the repository planted under a path the
user spelled inside the repository leads it out.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from tests._cli_inprocess_run import flat, run_cli

_SOURCE = "def f(x):\n    return x + 1\n"
_VICTIM_BYTES = b"ORIGINAL-VICTIM-CONTENT-DO-NOT-OVERWRITE\n"

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="symbolic links need privileges on Windows"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Layout:
    """A repository next to a directory it must never touch."""

    def __init__(self, tmp_path: Path) -> None:
        self.repo = tmp_path / "repo"
        self.outside = tmp_path / "outside"
        self.repo.mkdir()
        self.outside.mkdir()
        (self.repo / "pkg").mkdir()
        (self.repo / "pkg" / "mod.py").write_text(_SOURCE, encoding="utf-8")

    def pyproject(self, body: str) -> None:
        (self.repo / "pyproject.toml").write_text(
            f"[tool.codeclone]\n{body}\n", encoding="utf-8"
        )

    def victim(self, name: str) -> Path:
        path = self.outside / name
        path.write_bytes(_VICTIM_BYTES)
        return path


_flat = flat
_run_cli = run_cli


_REPORT_KEYS = (
    pytest.param("text_out", ".txt", "--text", id="text_out"),
    pytest.param("md_out", ".md", "--md", id="md_out"),
    pytest.param("html_out", ".html", "--html", id="html_out"),
    pytest.param("json_out", ".json", "--json", id="json_out"),
    pytest.param("sarif_out", ".sarif", "--sarif", id="sarif_out"),
)


@pytest.mark.parametrize(("key", "suffix", "flag"), _REPORT_KEYS)
@pytest.mark.parametrize("spelling", ["parent", "absolute", "tilde"])
def test_pyproject_report_path_outside_repository_is_refused_before_any_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    key: str,
    suffix: str,
    flag: str,
    spelling: str,
) -> None:
    layout = _Layout(tmp_path)
    victim = layout.victim(f"VICTIM{suffix}")
    before = _sha256(victim)
    monkeypatch.setenv("HOME", str(layout.outside))
    value = {
        "parent": f"../outside/VICTIM{suffix}",
        "absolute": str(victim),
        "tilde": f"~/VICTIM{suffix}",
    }[spelling]
    layout.pyproject(f'{key} = "{value}"')

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress")

    output = _flat(capsys.readouterr().out)
    assert code == 2, output
    assert _sha256(victim) == before
    assert sorted(path.name for path in layout.outside.iterdir()) == [f"VICTIM{suffix}"]
    assert f"tool.codeclone.{key}" in output
    assert "must stay under the repository root" in output
    assert flag in output


def test_pyproject_report_path_into_a_new_outside_directory_creates_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _Layout(tmp_path)
    layout.pyproject('md_out = "../outside/new/deeper/report.md"')

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress")

    assert code == 2
    assert list(layout.outside.iterdir()) == []


def test_pyproject_report_path_through_a_linked_directory_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _Layout(tmp_path)
    victim = layout.victim("report.md")
    before = _sha256(victim)
    (layout.repo / "reports").symlink_to(layout.outside, target_is_directory=True)
    layout.pyproject('md_out = "reports/report.md"')

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress")

    assert code == 2
    assert _sha256(victim) == before


def test_pyproject_report_path_that_is_a_planted_link_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _Layout(tmp_path)
    victim = layout.victim("dotrc")
    before = _sha256(victim)
    (layout.repo / "out.txt").symlink_to(victim)
    layout.pyproject('text_out = "out.txt"')

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress")

    assert code == 2
    assert _sha256(victim) == before


def test_pyproject_report_path_inside_repository_is_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _Layout(tmp_path)
    layout.pyproject('md_out = "reports/report.md"')

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress")

    assert code == 0
    assert (
        (layout.repo / "reports" / "report.md")
        .read_text(encoding="utf-8")
        .startswith("# CodeClone Report")
    )


def test_pyproject_absolute_report_path_inside_repository_is_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _Layout(tmp_path)
    target = layout.repo / "reports" / "abs.txt"
    layout.pyproject(f'text_out = "{target}"')

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress")

    assert code == 0
    assert target.is_file()


def test_command_line_report_path_outside_repository_is_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _Layout(tmp_path)
    target = layout.outside / "user-chosen.md"

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress", "--md", str(target))

    assert code == 0
    assert target.read_text(encoding="utf-8").startswith("# CodeClone Report")


def test_command_line_report_path_through_a_link_spelled_outside_is_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The user's own link, outside the repository: their word, followed.
    layout = _Layout(tmp_path)
    user_link = tmp_path / "my-reports"
    user_link.symlink_to(layout.outside, target_is_directory=True)

    code = _run_cli(
        monkeypatch,
        layout.repo,
        ".",
        "--no-progress",
        "--md",
        str(user_link / "r.md"),
    )

    assert code == 0
    assert (layout.outside / "r.md").is_file()


def test_command_line_report_path_through_a_planted_linked_directory_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _Layout(tmp_path)
    victim = layout.victim("r.md")
    before = _sha256(victim)
    (layout.repo / "reports").symlink_to(layout.outside, target_is_directory=True)

    code = _run_cli(
        monkeypatch, layout.repo, ".", "--no-progress", "--md", "reports/r.md"
    )

    assert code == 2
    assert _sha256(victim) == before


@pytest.mark.parametrize(
    ("link_name", "flag"),
    [
        pytest.param("notes.txt", "--text", id="allowed-suffix"),
        pytest.param("notes", "--text", id="no-suffix"),
    ],
)
def test_command_line_report_path_that_is_a_planted_link_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    link_name: str,
    flag: str,
) -> None:
    layout = _Layout(tmp_path)
    victim = layout.victim("todo.txt")
    before = _sha256(victim)
    (layout.repo / link_name).symlink_to(victim)

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress", flag, link_name)

    assert code == 2
    assert _sha256(victim) == before


def test_command_line_report_suffix_is_checked_on_the_written_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    layout = _Layout(tmp_path)
    victim = layout.victim("dotrc")
    before = _sha256(victim)
    (layout.repo / "notes.txt").symlink_to(victim)

    code = _run_cli(
        monkeypatch, layout.repo, ".", "--no-progress", "--text", "notes.txt"
    )

    assert code == 2
    assert _sha256(victim) == before
    assert "symbolic link" in _flat(capsys.readouterr().out)


def test_pyproject_baseline_outside_repository_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _Layout(tmp_path)
    layout.pyproject('baseline = "../outside/a/b/planted.json"')

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress", "--update-baseline")

    assert code == 2
    assert list(layout.outside.iterdir()) == []


def test_pyproject_coverage_xml_outside_repository_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    layout = _Layout(tmp_path)
    layout.victim("coverage.xml")
    layout.pyproject('coverage_xml = "../outside/coverage.xml"')

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress")

    output = _flat(capsys.readouterr().out)
    assert code == 2, output
    assert "tool.codeclone.coverage_xml" in output
    assert "--coverage" in output


def _committed_baseline_link(layout: _Layout) -> tuple[Path, str]:
    victim = layout.victim("planted.json")
    (layout.repo / "codeclone.baseline.json").symlink_to(victim)
    return victim, _sha256(victim)


def test_update_baseline_through_a_committed_link_outside_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    layout = _Layout(tmp_path)
    victim, before = _committed_baseline_link(layout)

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress", "--update-baseline")

    output = _flat(capsys.readouterr().out)
    assert code == 2, output
    assert _sha256(victim) == before
    assert "symbolic link" in output


def test_update_metrics_baseline_through_a_committed_link_outside_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _Layout(tmp_path)
    victim, before = _committed_baseline_link(layout)

    code = _run_cli(
        monkeypatch, layout.repo, ".", "--no-progress", "--update-metrics-baseline"
    )

    assert code == 2
    assert _sha256(victim) == before


def test_update_baseline_through_a_linked_parent_directory_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Spelled inside the repository (``ci/...``); the planted directory link
    # is on the way, not at the last component.
    layout = _Layout(tmp_path)
    victim = layout.victim("codeclone.baseline.json")
    before = _sha256(victim)
    (layout.repo / "ci").symlink_to(layout.outside, target_is_directory=True)

    code = _run_cli(
        monkeypatch,
        layout.repo,
        ".",
        "--no-progress",
        "--baseline",
        "ci/codeclone.baseline.json",
        "--update-baseline",
    )

    assert code == 2
    assert _sha256(victim) == before


def test_update_baseline_to_an_outside_path_the_user_spelled_is_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _Layout(tmp_path)
    target = layout.outside / "shared" / "codeclone.baseline.json"
    target.parent.mkdir()

    code = _run_cli(
        monkeypatch,
        layout.repo,
        ".",
        "--no-progress",
        "--baseline",
        str(target),
        "--update-baseline",
    )

    assert code == 0
    assert target.read_text(encoding="utf-8").lstrip().startswith("{")


def test_baseline_read_through_a_link_outside_the_root_keeps_working(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A monorepo shares one baseline: ``pkg`` is the analysed root and its
    # baseline is a link to the shared file above it. Reading it is allowed.
    layout = _Layout(tmp_path)
    shared = layout.outside / "codeclone.baseline.json"
    assert (
        _run_cli(
            monkeypatch,
            layout.repo,
            ".",
            "--no-progress",
            "--baseline",
            str(shared),
            "--update-baseline",
        )
        == 0
    )
    (layout.repo / "codeclone.baseline.json").symlink_to(shared)
    before = _sha256(shared)
    capsys.readouterr()

    code = _run_cli(monkeypatch, layout.repo, ".", "--ci")

    output = _flat(capsys.readouterr().out)
    assert code == 0, output
    assert _sha256(shared) == before


def test_deeply_nested_pyproject_is_a_typed_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    layout = _Layout(tmp_path)
    depth = 100_000
    (layout.repo / "pyproject.toml").write_text(
        f"[tool.codeclone]\nmin_loc = 5\nx = {'[' * depth}{']' * depth}\n",
        encoding="utf-8",
    )

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress")

    output = _flat(capsys.readouterr().out)
    assert code == 2, output
    assert "CONTRACT ERROR" in output
    assert "pyproject.toml" in output


def test_report_path_that_links_to_a_repository_file_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The link stays inside the repository and points at a file with the
    # report's own suffix, so only the last-component rule protects that file
    # from being overwritten.
    layout = _Layout(tmp_path)
    source = layout.repo / "docs" / "important.txt"
    source.parent.mkdir()
    source.write_bytes(_VICTIM_BYTES)
    before = _sha256(source)
    (layout.repo / "notes.txt").symlink_to(source)

    code = _run_cli(
        monkeypatch, layout.repo, ".", "--no-progress", "--text", "notes.txt"
    )

    assert code == 2
    assert _sha256(source) == before


@pytest.mark.parametrize(
    "linked",
    [
        pytest.param(".cache", id="cache-root-directory"),
        pytest.param(".cache/codeclone", id="cache-subdirectory"),
    ],
)
def test_cache_through_a_committed_directory_link_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    linked: str,
) -> None:
    layout = _Layout(tmp_path)
    link = layout.repo / linked
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(layout.outside, target_is_directory=True)

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress")

    output = _flat(capsys.readouterr().out)
    assert code == 2, output
    assert list(layout.outside.iterdir()) == []
    assert "cache" in output
    assert "symbolic link" in output


def test_cache_file_that_is_a_committed_link_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _Layout(tmp_path)
    victim = layout.victim("cache.json")
    before = _sha256(victim)
    (layout.repo / ".cache" / "codeclone").mkdir(parents=True)
    (layout.repo / ".cache" / "codeclone" / "cache.json").symlink_to(victim)

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress")

    assert code == 2
    assert _sha256(victim) == before


def test_cache_through_a_link_that_stays_inside_the_repository_is_used(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _Layout(tmp_path)
    (layout.repo / "build-cache").mkdir()
    (layout.repo / ".cache").symlink_to(
        layout.repo / "build-cache", target_is_directory=True
    )

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress")

    assert code == 0
    assert (layout.repo / "build-cache" / "codeclone" / "cache.json").is_file()


def test_cache_path_the_user_spelled_outside_is_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _Layout(tmp_path)
    target = layout.outside / "user-cache.json"

    code = _run_cli(
        monkeypatch, layout.repo, ".", "--no-progress", "--cache-path", str(target)
    )

    assert code == 0
    assert target.is_file()


def test_cache_path_on_the_command_line_through_a_planted_link_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _Layout(tmp_path)
    (layout.repo / "ci").symlink_to(layout.outside, target_is_directory=True)

    code = _run_cli(
        monkeypatch, layout.repo, ".", "--no-progress", "--cache-path", "ci/cache.json"
    )

    assert code == 2
    assert list(layout.outside.iterdir()) == []


def test_cache_behind_a_link_that_cannot_be_resolved_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A failed resolution is not evidence that the link stays inside.
    layout = _Layout(tmp_path)
    (layout.repo / "build-cache").mkdir()
    (layout.repo / ".cache").symlink_to(
        layout.repo / "build-cache", target_is_directory=True
    )
    original_resolve = Path.resolve

    def _resolve(self: Path, strict: bool = False) -> Path:
        if ".cache" in self.parts:
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve)

    code = _run_cli(monkeypatch, layout.repo, ".", "--no-progress")

    assert code == 2
    assert not (layout.repo / "build-cache" / "codeclone").exists()


def test_link_on_the_way_reads_every_existing_component(tmp_path: Path) -> None:
    from codeclone.utils.repo_links import link_on_the_way as _link_on_the_way

    plain = tmp_path / "plain" / "cache.json"
    plain.parent.mkdir()
    plain.write_text("{}", encoding="utf-8")
    assert _link_on_the_way(plain) is False
    assert _link_on_the_way(tmp_path / "plain" / "missing" / "cache.json") is False

    (tmp_path / "linked").symlink_to(tmp_path / "plain", target_is_directory=True)
    assert _link_on_the_way(tmp_path / "linked" / "cache.json") is True

    sealed = tmp_path / "sealed"
    (sealed / "inner").mkdir(parents=True)
    sealed.chmod(0o600)
    try:
        # An unobservable component is not evidence that there is no link.
        assert _link_on_the_way(sealed / "inner" / "cache.json") is True
    finally:
        sealed.chmod(0o700)
