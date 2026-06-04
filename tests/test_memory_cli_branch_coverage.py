# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from codeclone.contracts import ExitCode
from codeclone.memory.ingest import InitReport
from codeclone.surfaces.cli.memory import memory_main

from .memory_fixtures import cli_memory_repo


@pytest.mark.parametrize(
    "rejected_cache_reason, source, expected_substring",
    [
        (
            "digest_mismatch",
            "trusted_cache",
            "cached report rejected; running fresh analysis",
        ),
        (None, "fresh_analysis", "no trusted cached report; running fresh analysis"),
        (None, "trusted_cache", "reusing trusted cached report"),
    ],
)
def test_memory_cli_init_renders_init_note_for_cache_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rejected_cache_reason: str | None,
    source: str,
    expected_substring: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    loaded = SimpleNamespace(
        rejected_cache_reason=rejected_cache_reason,
        source=source,
        document={},
    )
    monkeypatch.setattr(
        "codeclone.surfaces.cli.memory.load_report_for_memory_init",
        lambda **_kwargs: loaded,
    )
    monkeypatch.setattr(
        "codeclone.surfaces.cli.memory.run_memory_init",
        lambda **_kwargs: InitReport(
            project_id="proj-test",
            db_path=None,
            dry_run=True,
            analysis_fingerprint="fp",
            stats={},
            planned_counts={},
            warnings=[],
        ),
    )

    rendered_messages: list[str] = []

    def _capture_init_note(*, console: object, message: str) -> None:
        rendered_messages.append(message)

    monkeypatch.setattr(
        "codeclone.surfaces.cli.memory.render_init_note",
        _capture_init_note,
    )
    monkeypatch.setattr(
        "codeclone.surfaces.cli.memory.render_init_result",
        lambda **_kwargs: None,
    )

    code = memory_main(
        [
            "init",
            "--root",
            str(root.resolve()),
            "--from-report",
            "ignored.json",
            "--dry-run",
            "--no-docs",
            "--no-tests",
        ]
    )
    assert code == int(ExitCode.SUCCESS)
    assert any(expected_substring in m for m in rendered_messages)


def test_memory_cli_init_fails_when_load_report_throws(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    monkeypatch.setattr(
        "codeclone.surfaces.cli.memory.load_report_for_memory_init",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    code = memory_main(
        [
            "init",
            "--root",
            str(root.resolve()),
            "--from-report",
            "ignored.json",
            "--dry-run",
        ]
    )
    assert code == int(ExitCode.CONTRACT_ERROR)


def test_memory_cli_init_fails_when_run_init_throws(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    loaded = SimpleNamespace(
        rejected_cache_reason=None,
        source="fresh_analysis",
        document={},
    )
    monkeypatch.setattr(
        "codeclone.surfaces.cli.memory.load_report_for_memory_init",
        lambda **_kwargs: loaded,
    )
    monkeypatch.setattr(
        "codeclone.surfaces.cli.memory.run_memory_init",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("init failed")),
    )
    monkeypatch.setattr(
        "codeclone.surfaces.cli.memory.render_init_note",
        lambda **_kwargs: None,
    )

    code = memory_main(
        [
            "init",
            "--root",
            str(root.resolve()),
            "--from-report",
            "ignored.json",
            "--dry-run",
            "--no-docs",
            "--no-tests",
        ]
    )
    assert code == int(ExitCode.INTERNAL_ERROR)


@pytest.mark.parametrize(
    "argv",
    [
        ["search", "fixture", "--root", "__ROOT__"],
        ["stale", "--root", "__ROOT__"],
        ["vacuum", "--root", "__ROOT__"],
        ["coverage", "pkg/mod.py", "--root", "__ROOT__"],
        ["review-candidates", "--root", "__ROOT__"],
        ["approve", "mem-missing", "--root", "__ROOT__"],
        ["reject", "mem-missing", "--root", "__ROOT__"],
        ["archive", "mem-missing", "--root", "__ROOT__"],
    ],
)
def test_memory_cli_returns_contract_error_when_db_missing(
    tmp_path: Path,
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    root_str = str(root.resolve())
    argv_real = [part if part != "__ROOT__" else root_str for part in argv]

    # Ensure we don't accidentally create db via config env overrides.
    monkeypatch.delenv("CODECLONE_MEMORY_DB_PATH", raising=False)

    code = memory_main(argv_real)
    assert code == int(ExitCode.CONTRACT_ERROR)


def test_memory_cli_search_payload_type_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with cli_memory_repo(tmp_path) as (root, _project, _store):
        root_str = str(root.resolve())

        monkeypatch.setattr(
            "codeclone.surfaces.cli.memory.query_engineering_memory",
            lambda *_args, **_kwargs: {"payload": "not-a-dict"},
        )
        monkeypatch.setattr(
            "codeclone.surfaces.cli.memory.render_search_results",
            lambda **_kwargs: None,
        )
        code = memory_main(["search", "fixture", "--root", root_str])
        assert code == int(ExitCode.INTERNAL_ERROR)

        captured_records: list[object] = []

        def _capture_render(*, records: list[object], **_kwargs: object) -> None:
            captured_records.extend(records)

        monkeypatch.setattr(
            "codeclone.surfaces.cli.memory.query_engineering_memory",
            lambda *_args, **_kwargs: {"payload": {"records": "not-a-list"}},
        )
        monkeypatch.setattr(
            "codeclone.surfaces.cli.memory.render_search_results",
            _capture_render,
        )
        code = memory_main(["search", "fixture", "--root", root_str])
        assert code == int(ExitCode.SUCCESS)
        assert captured_records == []


@pytest.mark.parametrize(
    "command, patch_attr",
    [
        ("approve", "approve_record"),
        ("reject", "reject_record"),
        ("archive", "archive_record"),
    ],
)
def test_memory_cli_action_failure_returns_contract_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    patch_attr: str,
) -> None:
    with cli_memory_repo(tmp_path) as (root, _project, _store):
        root_str = str(root.resolve())

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("action failed")

        monkeypatch.setattr(f"codeclone.surfaces.cli.memory.{patch_attr}", _boom)

        if command == "approve":
            argv = [
                "approve",
                "mem-any",
                "--root",
                root_str,
                "--by",
                "tester",
                "--i-know-what-im-doing",
            ]
        elif command == "reject":
            argv = [
                "reject",
                "mem-any",
                "--root",
                root_str,
                "--by",
                "tester",
                "--reason",
                "nope",
                "--i-know-what-im-doing",
            ]
        else:
            argv = [
                "archive",
                "mem-any",
                "--root",
                root_str,
                "--by",
                "tester",
                "--i-know-what-im-doing",
            ]

        code = memory_main(argv)
        assert code == int(ExitCode.CONTRACT_ERROR)
