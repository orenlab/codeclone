# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from codeclone.memory.report_trust import cached_report_untrusted_reason


def _base_report_document(*, root: Path, items: list[str]) -> dict[str, object]:
    return {
        "meta": {"scan_root": str(root)},
        "inventory": {"file_registry": {"items": items}},
    }


_FakeRunFn = Callable[
    [list[str], Path, bool, bool, bool, float],
    CompletedProcess[str],
]


def _git_root_and_report_doc(
    tmp_path: Path,
    *,
    items: list[str],
    old_ts: int | None,
) -> tuple[Path, Path, dict[str, object]]:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()

    report_path = root / "report.json"
    report_path.write_text("{}", encoding="utf-8")
    if old_ts is not None:
        os.utime(report_path, (old_ts, old_ts))

    return root, report_path, _base_report_document(root=root, items=items)


def _make_fake_git_run(
    *,
    tracked_out: str,
    head_stdout: str,
    git_log_stdout: str,
    fail_cmd: str | None,
) -> _FakeRunFn:
    def _run(
        cmd: list[str],
        cwd: Path,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> CompletedProcess[str]:
        if cmd[1] == "ls-files":
            return CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=tracked_out,
                stderr="",
            )
        if cmd[1] == "rev-parse":
            if fail_cmd == "rev-parse":
                raise OSError("rev-parse failed")
            return CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=head_stdout,
                stderr="",
            )
        if cmd[1] == "log":
            if fail_cmd == "log":
                raise OSError("git log failed")
            return CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=git_log_stdout,
                stderr="",
            )
        raise AssertionError(f"unexpected cmd: {cmd}")

    return _run


def test_cached_report_untrusted_when_report_mtime_older_than_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, report_path, report_doc = _git_root_and_report_doc(
        tmp_path,
        items=["pkg/a.py"],
        old_ts=100,
    )
    fake_run = _make_fake_git_run(
        tracked_out="pkg/a.py\n",
        head_stdout="deadbeef\n",
        git_log_stdout="9999999999\n",
        fail_cmd=None,
    )
    monkeypatch.setattr("codeclone.memory.report_trust.subprocess.run", fake_run)

    reason = cached_report_untrusted_reason(
        root_path=root,
        report_path=report_path,
        report_document=report_doc,
    )
    assert reason is not None
    assert "older than current git HEAD" in reason


def test_cached_report_untrusted_reason_scan_root_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "root"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()

    reason = cached_report_untrusted_reason(
        root_path=root,
        report_path=root / "report.json",
        report_document=_base_report_document(root=root, items=["pkg/a.py"])
        | {"meta": {"scan_root": str(other)}},
    )
    assert reason == "cached report scan_root does not match init root"


@pytest.mark.parametrize(
    "old_ts, git_log_stdout, expected_reason",
    [
        (1000, "2000\n", "cached report is older than current git HEAD commit"),
        (None, "\n", None),
    ],
)
def test_cached_report_untrusted_reason_git_log_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    old_ts: int | None,
    git_log_stdout: str,
    expected_reason: str | None,
) -> None:
    root, report_path, report_doc = _git_root_and_report_doc(
        tmp_path, items=["pkg/a.py"], old_ts=old_ts
    )

    tracked_out = "pkg/a.py\n"
    fake_run = _make_fake_git_run(
        tracked_out=tracked_out,
        head_stdout="deadbeef\n",
        git_log_stdout=git_log_stdout,
        fail_cmd=None,
    )
    monkeypatch.setattr("codeclone.memory.report_trust.subprocess.run", fake_run)

    reason = cached_report_untrusted_reason(
        root_path=root,
        report_path=report_path,
        report_document=report_doc,
    )
    assert reason == expected_reason


def test_cached_report_untrusted_reason_handles_ls_files_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, report_doc = _git_root_and_report_doc(
        tmp_path, items=["pkg/a.py"], old_ts=None
    )

    def _run(
        cmd: list[str],
        cwd: Path,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> CompletedProcess[str]:
        if cmd[1] == "ls-files":
            raise OSError("ls-files failed")
        if cmd[1] == "rev-parse":
            return CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="",
                stderr="",
            )
        if cmd[1] == "log":
            return CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="0\n",
                stderr="",
            )
        raise AssertionError(f"unexpected cmd: {cmd}")

    monkeypatch.setattr("codeclone.memory.report_trust.subprocess.run", _run)

    reason = cached_report_untrusted_reason(
        root_path=root,
        report_path=root / "report.json",
        report_document=report_doc,
    )
    assert reason is None


@pytest.mark.parametrize("fail_cmd", ["rev-parse", "log"])
def test_cached_report_untrusted_reason_git_subprocess_failure_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_cmd: str,
) -> None:
    root, report_path, report_doc = _git_root_and_report_doc(
        tmp_path, items=["pkg/a.py"], old_ts=None
    )
    tracked_out = "pkg/a.py\n"
    fake_run = _make_fake_git_run(
        tracked_out=tracked_out,
        head_stdout="deadbeef\n",
        git_log_stdout="0\n",
        fail_cmd=fail_cmd,
    )
    monkeypatch.setattr("codeclone.memory.report_trust.subprocess.run", fake_run)

    reason = cached_report_untrusted_reason(
        root_path=root,
        report_path=report_path,
        report_document=report_doc,
    )
    assert reason is None
