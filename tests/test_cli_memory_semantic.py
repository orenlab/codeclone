# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

import codeclone.memory.semantic as semantic_pkg
import codeclone.surfaces.cli.memory as cli_memory
from codeclone.config.memory import resolve_memory_config
from codeclone.memory.embedding import DeterministicHashEmbeddingProvider
from codeclone.memory.exceptions import MemorySemanticUnavailableError
from codeclone.memory.models import MemorySubject, generate_memory_id
from codeclone.memory.project import resolve_memory_db_path, resolve_project_identity
from codeclone.memory.semantic.models import (
    ExistingSourceRevision,
    SemanticHit,
    SemanticIndexStatus,
    SemanticRow,
    SemanticRowFingerprint,
)
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.surfaces.cli.memory import _render_semantic_text, memory_main
from codeclone.surfaces.cli.memory_render import memory_console
from tests.memory_fixtures import make_module_record


class _FakeSemanticIndex:
    def __init__(self) -> None:
        self.rows: list[SemanticRow] = []

    def search(
        self, vector: Sequence[float], *, k: int, source: str | None = None
    ) -> list[SemanticHit]:
        rows = (
            self.rows
            if source is None
            else [row for row in self.rows if row.source == source]
        )
        return [
            SemanticHit(source_id=row.id, source=row.source, score=1.0 - index * 0.01)
            for index, row in enumerate(rows[:k])
        ]

    def status(self) -> SemanticIndexStatus:
        return SemanticIndexStatus(
            available=True,
            backend="fake",
            provider="diagnostic",
            embedding_model="diagnostic-hash-v1",
            dimension=64,
            indexed_count=len(self.rows),
        )

    def upsert(self, rows: Sequence[SemanticRow]) -> None:
        incoming = {row.id for row in rows}
        self.rows = [row for row in self.rows if row.id not in incoming]
        self.rows.extend(rows)

    def delete(self, ids: Sequence[str]) -> None:
        stale = set(ids)
        self.rows = [row for row in self.rows if row.id not in stale]

    def known_ids(self) -> set[str]:
        return {row.id for row in self.rows}

    def row_fingerprints(self, ids: Sequence[str]) -> dict[str, SemanticRowFingerprint]:
        by_id = {row.id: row for row in self.rows}
        return {
            row_id: SemanticRowFingerprint(
                id=row_id,
                text_hash=by_id[row_id].text_hash,
                embedding_model=by_id[row_id].embedding_model,
                source_revision=by_id[row_id].source_revision,
            )
            for row_id in ids
            if row_id in by_id
        }

    def existing_revisions(self) -> dict[str, ExistingSourceRevision]:
        heads: dict[str, SemanticRow] = {}
        members: dict[str, set[str]] = {}
        for row in self.rows:
            key = row.parent_id or row.id
            heads.setdefault(key, row)
            members.setdefault(key, set()).add(row.id)
        return {
            key: ExistingSourceRevision(
                source=head.source,
                source_revision=head.source_revision,
                embedding_model=head.embedding_model,
                row_ids=frozenset(members[key]),
            )
            for key, head in heads.items()
        }


def _install_fake_semantic_index(
    monkeypatch: pytest.MonkeyPatch,
) -> _FakeSemanticIndex:
    index = _FakeSemanticIndex()
    monkeypatch.setattr(
        semantic_pkg,
        "resolve_semantic_index_writer",
        lambda config: index if config.enabled else None,
    )
    monkeypatch.setattr(
        cli_memory,
        "resolve_semantic_index",
        lambda config: index,
    )
    return index


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
    assert "semantic-lancedb" in out or "disabled" in out


def test_semantic_search_fails_clear_without_backend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = memory_main(
        ["semantic", "search", "recover after restart", "--root", str(tmp_path)]
    )
    out = capsys.readouterr().out.lower()
    assert code != 0
    assert "unavailable" in out


def _seed_semantic_repo(
    tmp_path: Path,
    *,
    statement: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_semantic_index(monkeypatch)
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


def _init_semantic_repo_with_provider(tmp_path: Path, *, provider: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone.memory.semantic]\n"
        "enabled = true\n"
        f'embedding_provider = "{provider}"\n',
        encoding="utf-8",
    )
    config = resolve_memory_config(tmp_path)
    project = resolve_project_identity(tmp_path)
    db_path = resolve_memory_db_path(tmp_path, config)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteEngineeringMemoryStore(db_path)
    try:
        store.initialize(project)
    finally:
        store.close()


def test_memory_search_semantic_provider_unavailable_degrades_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init_semantic_repo_with_provider(tmp_path, provider="local_model")

    code = memory_main(["search", "anything", "--root", str(tmp_path), "--semantic"])

    assert code == 0
    out = capsys.readouterr().out
    assert "semantic: off" in out
    assert "local_model embedding provider is not" in out.replace("\n", " ")
    assert "available yet" in out.replace("\n", " ")
    assert "Traceback" not in out


def test_semantic_explicit_commands_fail_clear_when_provider_unavailable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init_semantic_repo_with_provider(tmp_path, provider="local_model")

    for command in (
        ["semantic", "rebuild", "--root", str(tmp_path)],
        ["semantic", "search", "anything", "--root", str(tmp_path)],
    ):
        code = memory_main(command)
        assert code != 0
        out = capsys.readouterr().out
        if command[1] == "rebuild":
            assert "Semantic index rebuild unavailable" in out
        else:
            assert "Semantic embedding provider unavailable" in out
        assert "local_model embedding provider is not" in out.replace("\n", " ")
        assert "available yet" in out.replace("\n", " ")
        assert "Traceback" not in out


def test_semantic_status_reports_provider_unavailable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init_semantic_repo_with_provider(tmp_path, provider="local_model")

    code = memory_main(["semantic", "status", "--root", str(tmp_path)])

    assert code == 0
    out = capsys.readouterr().out
    assert "semantic index: unavailable" in out
    assert "provider: unavailable" in out
    assert "local_model embedding provider is not" in out.replace("\n", " ")
    assert "available yet" in out.replace("\n", " ")


def test_semantic_search_degrades_when_model_unavailable_at_embed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_semantic_repo(
        tmp_path, statement="recover after restart", monkeypatch=monkeypatch
    )

    class _FailingProvider:
        model_id = "diagnostic-hash-v1"
        dimension = 64

        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            raise MemorySemanticUnavailableError(
                "model unavailable (download disabled)"
            )

    # Provider resolves (lazy); the model only fails when the search embeds.
    monkeypatch.setattr(
        cli_memory, "resolve_embedding_provider", lambda _config: _FailingProvider()
    )

    code = memory_main(
        ["semantic", "search", "recover after restart", "--root", str(tmp_path)]
    )

    out = capsys.readouterr().out
    assert code != 0
    assert "unavailable" in out.lower()
    assert "model unavailable" in out.replace("\n", " ")
    assert "Traceback" not in out


def test_semantic_search_hydrates_and_renders_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_semantic_repo(
        tmp_path,
        statement="recover after MCP restart uses the checkpoint workflow",
        monkeypatch=monkeypatch,
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
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_semantic_repo(
        tmp_path,
        statement="recover after MCP restart uses the checkpoint workflow",
        monkeypatch=monkeypatch,
    )
    capsys.readouterr()
    code = memory_main(["search", "recover", "--root", str(tmp_path), "--semantic"])
    assert code == 0
    out = capsys.readouterr().out
    assert "semantic: on" in out
    assert "diagnostic" in out


def test_semantic_search_text_renders_ranked_hits(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_semantic_repo(
        tmp_path,
        statement="recover after MCP restart uses the checkpoint workflow",
        monkeypatch=monkeypatch,
    )
    capsys.readouterr()
    code = memory_main(
        ["semantic", "search", "recover restart", "--root", str(tmp_path)]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "Semantic matches for: recover restart" in out
    assert "score=" in out
    assert "subject: codeclone/x.py" in out
    assert "recover after MCP restart" in out


def test_semantic_status_shows_provider_when_index_built(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_semantic_repo(
        tmp_path,
        statement="recover checkpoint workflow",
        monkeypatch=monkeypatch,
    )
    capsys.readouterr()
    code = memory_main(["semantic", "status", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "semantic index: available" in out
    assert "provider: diagnostic-hash" in out


def test_semantic_rebuild_requires_memory_database(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_semantic_index(monkeypatch)
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone.memory.semantic]\nenabled = true\ndimension = 64\n",
        encoding="utf-8",
    )
    code = memory_main(["semantic", "rebuild", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert code != 0
    assert "Engineering memory database not found" in out
    assert "codeclone memory init" in out


def test_memory_coverage_rejects_invalid_scope_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.memory_fixtures import cli_memory_repo

    with cli_memory_repo(tmp_path) as (root, _project, _store):
        code = memory_main(["coverage", ".", "--root", str(root)])
    out = capsys.readouterr().out
    assert code != 0
    assert "not a valid memory scope" in out.lower()


def test_memory_for_path_rejects_root_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = memory_main(["for-path", ".", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert code != 0
    assert "not a valid memory scope" in out.lower()


def test_render_semantic_text_reports_no_matches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = resolve_memory_config(tmp_path)
    provider = DeterministicHashEmbeddingProvider(dimension=config.semantic.dimension)
    code = _render_semantic_text(
        console=memory_console(),
        query="empty",
        config=config,
        provider=provider,
        results=[],
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "(no matches)" in out


def test_semantic_probe_skipped_when_disabled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = memory_main(["semantic", "probe", "--root", str(tmp_path)])
    out = capsys.readouterr().out.lower()
    assert code != 0
    assert "disabled" in out


def test_semantic_probe_json_emits_payload(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "action": "probe_semantic_projections",
        "status": "ok",
        "estimator": "chars_approx",
        "model_max_tokens": 512,
        "lanes": {
            "memory": {
                "documents": 1,
                "chars": {"p50": 10, "p95": 20, "max": 30},
                "tokens": {
                    "raw": {"p50": 3, "p95": 6, "max": 9},
                    "effective": {"p50": 3, "p95": 6, "max": 9},
                },
                "truncation": {"documents": 0, "max_dropped_tokens": 0},
                "token_overflow": {
                    "over_model_limit": 0,
                    "max_overflow_tokens": 0,
                },
            }
        },
    }
    monkeypatch.setattr(
        cli_memory,
        "execute_semantic_projection_probe",
        lambda **_kwargs: payload,
    )
    code = memory_main(["semantic", "probe", "--root", str(tmp_path), "--json"])
    assert code == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["action"] == "probe_semantic_projections"
    assert emitted["lanes"]["memory"]["documents"] == 1


def test_semantic_probe_text_renders_lane_percentiles(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "action": "probe_semantic_projections",
        "estimator": "fastembed_tokenizer",
        "model_max_tokens": 512,
        "lanes": {
            "memory": {
                "documents": 2,
                "chars": {"p50": 10, "p95": 20, "max": 30},
                "tokens": {
                    "raw": {"p50": 3, "p95": 6, "max": 9},
                    "effective": {"p50": 2, "p95": 5, "max": 8},
                },
                "truncation": {"documents": 1, "max_dropped_tokens": 4},
                "token_overflow": {
                    "over_model_limit": 0,
                    "max_overflow_tokens": 0,
                },
            },
            "audit": {},
            "trajectory": {},
        },
    }
    monkeypatch.setattr(
        cli_memory,
        "execute_semantic_projection_probe",
        lambda **_kwargs: payload,
    )
    code = memory_main(["semantic", "probe", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Semantic projection probe:" in out
    assert "fastembed_tokenizer" in out
    assert "memory: 2 documents" in out
    assert "raw tokens p50/p95/max: 3/6/9" in out
    assert "effective tokens p50/p95/max: 2/5/8" in out
    assert "truncated: 1 (max_dropped=4)" in out


def test_semantic_probe_contract_error_suggests_memory_init(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.exceptions import MemoryContractError

    def _raise_contract(**_kwargs: object) -> object:
        raise MemoryContractError("Engineering memory database not found")

    monkeypatch.setattr(
        cli_memory, "execute_semantic_projection_probe", _raise_contract
    )
    code = memory_main(["semantic", "probe", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert code != 0
    assert "database not found" in out
    assert "codeclone memory init" in out


def test_semantic_probe_invalid_payload_reports_unavailable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_memory,
        "execute_semantic_projection_probe",
        lambda **_kwargs: {"action": "probe_semantic_projections", "lanes": "bad"},
    )
    code = memory_main(["semantic", "probe", "--root", str(tmp_path)])
    out = capsys.readouterr().out.lower()
    assert code != 0
    assert "invalid payload" in out
