# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.memory.models import MemorySubject, generate_memory_id
from codeclone.memory.project import resolve_memory_db_path, resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.surfaces.cli.memory import memory_main
from tests.memory_fixtures import make_module_record


def test_semantic_status_reports_unavailable_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = memory_main(["semantic", "status", "--root", str(tmp_path)])
    out = capsys.readouterr().out.lower()
    assert code == 0
    assert "semantic index" in out
    # default config has semantic disabled -> status reason "disabled"
    assert "disabled" in out


def test_semantic_rebuild_fails_clear_without_backend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = memory_main(["semantic", "rebuild", "--root", str(tmp_path)])
    out = capsys.readouterr().out.lower()
    assert code != 0
    assert "semantic" in out
    assert "semantic-lancedb" in out


def test_semantic_search_fails_clear_without_backend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = memory_main(
        ["semantic", "search", "recover after restart", "--root", str(tmp_path)]
    )
    out = capsys.readouterr().out.lower()
    assert code != 0
    assert "unavailable" in out


def _seed_semantic_repo(tmp_path: Path, *, statement: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone.memory.semantic]\nenabled = true\ndimension = 64\n",
        encoding="utf-8",
    )
    config = resolve_memory_config(tmp_path)
    project = resolve_project_identity(tmp_path)
    db_path = resolve_memory_db_path(tmp_path, config)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteEngineeringMemoryStore(db_path)
    try:
        store.initialize(project)
        record = dataclasses.replace(
            make_module_record(project.id, "codeclone/x.py"),
            id=generate_memory_id(),
            type="contract_note",
            statement=statement,
        )
        store.upsert_record(record)
        store.write_subject(
            MemorySubject(
                id="s1",
                memory_id=record.id,
                subject_kind="path",
                subject_key="codeclone/x.py",
            )
        )
    finally:
        store.close()
    assert memory_main(["semantic", "rebuild", "--root", str(tmp_path)]) == 0


def test_semantic_search_hydrates_and_renders_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("lancedb")
    _seed_semantic_repo(
        tmp_path, statement="recover after MCP restart uses the checkpoint workflow"
    )
    capsys.readouterr()
    code = memory_main(
        ["semantic", "search", "recover restart", "--root", str(tmp_path), "--json"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["semantic"]["diagnostic"] is True
    assert payload["results"]
    top = payload["results"][0]
    assert top["source"] == "memory"
    assert top["kind"] == "contract_note"
    assert top["subject_path"] == "codeclone/x.py"
    assert "recover after MCP restart" in top["preview"]


def test_memory_search_semantic_flag_blends_ranking(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("lancedb")
    _seed_semantic_repo(
        tmp_path, statement="recover after MCP restart uses the checkpoint workflow"
    )
    capsys.readouterr()
    code = memory_main(["search", "recover", "--root", str(tmp_path), "--semantic"])
    assert code == 0
    out = capsys.readouterr().out
    assert "semantic: on" in out
    assert "diagnostic" in out
