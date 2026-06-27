# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.memory.exceptions import (
    MemoryContractError,
    MemorySemanticUnavailableError,
)
from codeclone.memory.semantic.rebuild import RebuildReport
from codeclone.memory.semantic.rebuild_workflow import execute_semantic_index_rebuild

from .memory_fixtures import memory_store


def test_execute_semantic_rebuild_skipped_when_disabled(tmp_path: Path) -> None:
    config = resolve_memory_config(tmp_path)
    payload = execute_semantic_index_rebuild(root_path=tmp_path, config=config)
    assert payload["action"] == "rebuild_semantic_index"
    assert payload["status"] == "skipped"
    assert payload["reason"] == "disabled"
    assert payload["indexed"] == 0


def test_execute_semantic_rebuild_unavailable_without_lancedb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone.memory.semantic]\nenabled = true\n",
        encoding="utf-8",
    )
    config = resolve_memory_config(tmp_path)
    import codeclone.memory.semantic as semantic_pkg

    monkeypatch.setattr(semantic_pkg, "resolve_semantic_index_writer", lambda _c: None)
    payload = execute_semantic_index_rebuild(root_path=tmp_path, config=config)
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "lancedb_not_installed"


def test_execute_semantic_rebuild_requires_memory_db_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone.memory.semantic]\nenabled = true\n",
        encoding="utf-8",
    )
    config = resolve_memory_config(tmp_path)

    class _Writer:
        closed = False

        def known_ids(self) -> set[str]:
            return set()

        def delete(self, ids: object) -> None:
            return None

        def upsert(self, rows: object) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    import codeclone.memory.semantic as semantic_pkg

    writer = _Writer()
    monkeypatch.setattr(
        semantic_pkg,
        "resolve_semantic_index_writer",
        lambda _config: writer,
    )
    with pytest.raises(MemoryContractError, match="database not found"):
        execute_semantic_index_rebuild(root_path=tmp_path, config=config)
    assert writer.closed is True


def test_execute_semantic_rebuild_unavailable_when_model_fails_at_embed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = resolve_memory_config(tmp_path)
    config = dataclasses.replace(
        base,
        semantic=base.semantic.model_copy(
            update={"enabled": True, "embedding_provider": "diagnostic"}
        ),
    )

    class _Writer:
        def known_ids(self) -> set[str]:
            return set()

        def delete(self, ids: object) -> None:
            return None

        def upsert(self, rows: object) -> None:
            return None

        def close(self) -> None:
            return None

    import codeclone.memory.semantic as semantic_pkg
    from codeclone.memory.semantic import rebuild_workflow

    monkeypatch.setattr(
        semantic_pkg, "resolve_semantic_index_writer", lambda _config: _Writer()
    )
    monkeypatch.setattr(
        rebuild_workflow, "build_semantic_index_sources", lambda **_kwargs: []
    )

    def _raise_unavailable(**_kwargs: object) -> object:
        # Provider resolves fine (lazy); the model only fails when the rebuild
        # actually embeds.
        raise MemorySemanticUnavailableError("model unavailable (download disabled)")

    monkeypatch.setattr(rebuild_workflow, "rebuild_semantic_index", _raise_unavailable)

    with memory_store(tmp_path) as (root, project, store, _db_path):
        payload = execute_semantic_index_rebuild(
            root_path=root, config=config, store=store, project=project
        )
    assert payload["status"] == "unavailable"
    assert "model unavailable" in str(payload["reason"])


def test_rebuild_reason_kind_warm_skip_is_manual_rebuild() -> None:
    from codeclone.memory.semantic import rebuild_workflow as wf

    report = RebuildReport(
        indexed=1502,
        embedded=0,
        skipped_unchanged=1502,
        by_source={"memory": 238, "audit": 673, "trajectory": 591},
    )
    assert wf._rebuild_reason_kind(report) == "manual_rebuild"


def test_rebuild_reason_kind_embed_or_prune_is_content_changed() -> None:
    from codeclone.memory.semantic import rebuild_workflow as wf

    assert (
        wf._rebuild_reason_kind(
            RebuildReport(indexed=10, embedded=3, skipped_unchanged=7)
        )
        == "content_changed"
    )
    assert (
        wf._rebuild_reason_kind(
            RebuildReport(indexed=10, embedded=0, deleted=2, skipped_unchanged=8)
        )
        == "content_changed"
    )


def test_rebuild_reason_kind_first_index_when_empty() -> None:
    from codeclone.memory.semantic import rebuild_workflow as wf

    assert (
        wf._rebuild_reason_kind(
            RebuildReport(indexed=0, embedded=0, skipped_unchanged=0)
        )
        == "first_index"
    )


def test_rebuild_reason_kind_manual_without_embed_or_skip() -> None:
    from codeclone.memory.semantic import rebuild_workflow as wf

    assert (
        wf._rebuild_reason_kind(
            RebuildReport(indexed=4, embedded=0, deleted=0, skipped_unchanged=0)
        )
        == "manual_rebuild"
    )


def test_apply_rebuild_counters_records_lane_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.semantic import rebuild_workflow as wf

    counters: dict[str, int] = {}

    class _Span:
        def set_counter(self, key: str, value: int) -> None:
            counters[key] = value

    monkeypatch.setattr(wf, "is_observability_enabled", lambda: True)
    report = RebuildReport(
        indexed=5,
        embedded=2,
        deleted=1,
        skipped_unchanged=2,
        by_source={"memory": 3, "audit": 2},
    )
    wf._apply_rebuild_counters(
        cast(Any, _Span()),
        report,
        dimensions=384,
        batch_size=8,
        max_padded_tokens=4096,
    )
    assert counters["indexed"] == 5
    assert counters["lane_audit"] == 2
    assert counters["lane_memory"] == 3


def test_execute_semantic_index_rebuild_ok_returns_model_and_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = resolve_memory_config(tmp_path)
    config = dataclasses.replace(
        base,
        semantic=base.semantic.model_copy(update={"enabled": True}),
    )

    class _Writer:
        closed = False

        def known_ids(self) -> set[str]:
            return set()

        def delete(self, ids: object) -> None:
            return None

        def upsert(self, rows: object) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    import codeclone.memory.semantic as semantic_pkg
    from codeclone.memory.semantic import rebuild_workflow

    writer = _Writer()
    monkeypatch.setattr(
        semantic_pkg, "resolve_semantic_index_writer", lambda _config: writer
    )
    monkeypatch.setattr(
        rebuild_workflow,
        "rebuild_semantic_index",
        lambda **_kwargs: RebuildReport(
            indexed=4,
            embedded=2,
            deleted=1,
            skipped_unchanged=1,
            by_source={"trajectory": 2, "memory": 2},
        ),
    )

    with memory_store(tmp_path) as (root, project, store, _db_path):
        payload = execute_semantic_index_rebuild(
            root_path=root, config=config, store=store, project=project
        )
    assert payload["status"] == "ok"
    assert payload["embedding_model"] == "diagnostic-hash-v1"
    assert payload["by_source"] == {"memory": 2, "trajectory": 2}
    assert writer.closed is True


def test_execute_semantic_projection_probe_skipped_when_disabled(
    tmp_path: Path,
) -> None:
    from codeclone.memory.semantic.rebuild_workflow import (
        execute_semantic_projection_probe,
    )

    config = resolve_memory_config(tmp_path)
    payload = execute_semantic_projection_probe(root_path=tmp_path, config=config)
    skipped = cast(dict[str, str], payload)
    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "disabled"


def test_execute_semantic_projection_probe_reports_lane_stats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.semantic.rebuild_workflow import (
        build_semantic_index_sources,
        execute_semantic_projection_probe,
    )

    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone.memory.semantic]\nenabled = true\n",
        encoding="utf-8",
    )
    config = resolve_memory_config(tmp_path)
    with memory_store(tmp_path) as (root, project, store, _db_path):
        sources = build_semantic_index_sources(
            root_path=root,
            config=config,
            store=store,
            project=project,
        )
        assert {source.name() for source in sources} == {
            "memory",
            "audit",
            "trajectory",
        }
        payload = execute_semantic_projection_probe(
            root_path=root,
            config=config,
            store=store,
            project=project,
        )
    assert payload["action"] == "probe_semantic_projections"
    assert "lanes" in payload


def test_resolve_projection_helpers_use_fastembed_when_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.semantic import rebuild_workflow as wf

    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone.memory.semantic]\n"
        "enabled = true\n"
        'embedding_provider = "fastembed"\n',
        encoding="utf-8",
    )
    config = resolve_memory_config(tmp_path)

    class _Provider:
        model_id = "fastembed:test"

        @property
        def estimator_label(self) -> str:
            return "fastembed_tokenizer"

        def max_sequence_tokens(self) -> int | None:
            return 512

        def probe_passage_token_counts(self, texts: object) -> object:
            return texts

        def chunk_text(self, text: str) -> tuple[str, ...]:
            return (text,)

    provider = _Provider()
    monkeypatch.setattr(wf, "resolve_embedding_provider", lambda _cfg: provider)
    token_prober = wf._resolve_projection_token_prober(
        config.semantic,
        exact_tokens=True,
    )
    chunker = wf._resolve_projection_passage_chunker(
        config.semantic,
        exact_tokens=True,
    )
    assert cast(Any, token_prober) is provider
    assert chunker is not None
    assert wf._resolve_projection_passage_chunker(config.semantic) is None


def test_execute_semantic_projection_probe_requires_memory_db(
    tmp_path: Path,
) -> None:
    from codeclone.memory.semantic.rebuild_workflow import (
        execute_semantic_projection_probe,
    )

    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone.memory.semantic]\nenabled = true\n",
        encoding="utf-8",
    )
    config = resolve_memory_config(tmp_path)
    with pytest.raises(MemoryContractError, match="database not found"):
        execute_semantic_projection_probe(root_path=tmp_path, config=config)


def test_execute_semantic_projection_probe_opens_and_closes_store(
    tmp_path: Path,
) -> None:
    from codeclone.memory.semantic.rebuild_workflow import (
        execute_semantic_projection_probe,
    )

    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone.memory.semantic]\nenabled = true\n",
        encoding="utf-8",
    )
    config = resolve_memory_config(tmp_path)
    with memory_store(tmp_path) as (root, project, store, _db_path):
        payload = execute_semantic_projection_probe(
            root_path=root,
            config=config,
            project=project,
            store=store,
        )
    assert payload["action"] == "probe_semantic_projections"


def test_rebuild_semantic_index_records_observability_counters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.semantic import rebuild as rebuild_mod

    counters: dict[str, int] = {}

    class _Span:
        def __enter__(self) -> _Span:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def set_counter(self, key: str, value: int) -> None:
            counters[key] = value

    class _Writer:
        def known_ids(self) -> set[str]:
            return {"stale-1", "stale-2"}

        def delete(self, row_ids: list[str]) -> None:
            assert row_ids == ["stale-1", "stale-2"]

        def row_fingerprints(self, row_ids: list[str]) -> dict[str, object]:
            return {}

        def existing_revisions(self) -> dict[str, object]:
            return {}

        def upsert(self, rows: list[object]) -> None:
            return None

    class _Source:
        def name(self) -> str:
            return "memory"

        def available(self) -> bool:
            return True

        def iter_projections(self) -> Iterator[object]:
            return iter(())

    monkeypatch.setattr(rebuild_mod, "is_observability_enabled", lambda: True)
    monkeypatch.setattr(rebuild_mod, "span", lambda **_kwargs: _Span())
    monkeypatch.setattr(
        rebuild_mod, "resolve_passage_chunker", lambda _provider: SimpleNamespace()
    )
    monkeypatch.setattr(
        rebuild_mod,
        "_index_source",
        lambda *_args, **_kwargs: rebuild_mod._SourceIndexStats(
            seen_ids=set(),
            embedded=0,
            skipped_unchanged=0,
        ),
    )
    report = rebuild_mod.rebuild_semantic_index(
        sources=[cast(Any, _Source())],
        writer=_Writer(),  # type: ignore[arg-type]
        provider=SimpleNamespace(model_id="test-model"),
    )
    assert report.deleted == 2
    assert counters["deleted"] == 2


def test_embed_and_upsert_records_observability_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.embedding import DeterministicHashEmbeddingProvider
    from codeclone.memory.embedding.batching import EmbedBatchLimits
    from codeclone.memory.semantic import rebuild as rebuild_mod
    from codeclone.memory.semantic.chunking import IndexedSemanticUnit

    counters: dict[str, int] = {}

    class _Span:
        def __enter__(self) -> _Span:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def set_counter(self, key: str, value: int) -> None:
            counters[key] = value

    class _Writer:
        def upsert(self, rows: list[object]) -> None:
            assert rows

    unit = IndexedSemanticUnit(
        row_id="row-1",
        parent_id="parent-1",
        chunk_index=0,
        chunk_count=1,
        source="memory",
        project_id="project",
        subject_path="pkg/mod.py",
        kind="record",
        status="approved",
        text="semantic text",
        text_hash="hash",
    )
    provider = DeterministicHashEmbeddingProvider(dimension=8)
    monkeypatch.setattr(rebuild_mod, "is_observability_enabled", lambda: True)
    monkeypatch.setattr(rebuild_mod, "span", lambda **_kwargs: _Span())
    embedded = rebuild_mod._embed_and_upsert(
        (unit,),
        writer=_Writer(),  # type: ignore[arg-type]
        provider=provider,
        embed_batch_limits=EmbedBatchLimits(max_documents=4, max_padded_tokens=32),
    )
    assert embedded == 1
    assert counters["pending"] == 1
    assert counters["embedded"] == 1
    assert counters["batches"] == 1
