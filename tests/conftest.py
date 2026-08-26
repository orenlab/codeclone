# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Callable, Generator
from pathlib import Path

import pytest

from codeclone.baseline.trust import current_python_tag
from codeclone.contracts import CACHE_VERSION, REPORT_SCHEMA_VERSION
from tests._sqlite_cleanup import (
    close_tracked_sqlite_connections,
    make_tracking_connect,
    sweep_leaked_sqlite_connections_via_gc,
)

ReportMetaFactory = Callable[..., dict[str, object]]

# ---------------------------------------------------------------------------
# The wire-freeze distinguishing corpus (ruling 2026-08-24 §10, step 2b).
#
# Shared session infrastructure: the corpus tree is materialized from inert
# ``*.txt`` carriers and analyzed once through the real CLI; the resulting
# report document feeds BOTH the report-shape pins (an r4-subject module,
# ``test_wire_freeze_corpus``) and the canonical-family pins (an r2-subject
# module, ``test_canonical_wire_freeze_corpus``).  The builder lives here so
# each test module binds to exactly one architectural ring — the Phase 39S
# test-import law — while sharing one corpus run.
# ---------------------------------------------------------------------------

_WIRE_FREEZE_CORPUS = Path(__file__).parent / "fixtures" / "wire_freeze_corpus"

# The slice-5 distinguishing stage (its own tree, its own CLI run): the
# families it exists for (security surfaces, coverage join) carry zero
# rows on the base corpus, and extending the base tree would shift every
# measured base-corpus pin — new carriers live beside it, never inside it.
_WIRE_FREEZE_CORPUS_S5 = Path(__file__).parent / "fixtures" / "wire_freeze_corpus_s5"

# The post-baseline stage: materialized only after the baseline is written,
# so its clone pair is the corpus's one genuinely NEW novelty row.
_WIRE_FREEZE_POST_BASELINE = "pkg/clones_three.py"


def _materialize_corpus_tree(
    source: Path, target: Path, *, withhold: str | None = None
) -> None:
    """Write one corpus tree from its inert ``*.txt`` carriers.

    Every carrier becomes the file named by stripping the trailing
    ``.txt``; ``withhold`` names one relative destination to leave out.
    """
    for carrier in sorted(source.rglob("*.txt")):
        relative = carrier.relative_to(source).with_suffix("")
        if withhold is not None and relative.as_posix() == withhold:
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(carrier.read_text("utf-8"), "utf-8")


def materialize_wire_freeze_corpus(target: Path, *, post_baseline: bool) -> None:
    """Write the base corpus tree; stage A withholds the stage-B file."""
    _materialize_corpus_tree(
        _WIRE_FREEZE_CORPUS,
        target,
        withhold=None if post_baseline else _WIRE_FREEZE_POST_BASELINE,
    )


def _run_corpus_cli(args: list[str]) -> None:
    """The ONE spelling of a corpus CLI invocation (argv patch + main) —
    both corpus fixtures ride it, so the invocation block cannot fork."""
    import codeclone.surfaces.cli.workflow as cli

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(sys, "argv", ["codeclone", *args])
        cli.main()
    finally:
        monkeypatch.undo()


def _corpus_document(report_path: Path) -> dict[str, object]:
    document = json.loads(report_path.read_text("utf-8"))
    assert isinstance(document, dict)
    return document


@pytest.fixture(scope="session")
def corpus_report(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, object]:
    """One two-stage corpus run: baseline on stage A, report on stage B."""
    root = tmp_path_factory.mktemp("wire_freeze_corpus")
    baseline = root / "corpus.baseline.json"
    report_path = root / "corpus.report.json"
    materialize_wire_freeze_corpus(root, post_baseline=False)
    _run_corpus_cli(
        [
            str(root),
            "--baseline",
            str(baseline),
            "--update-baseline",
            "--no-progress",
        ]
    )
    materialize_wire_freeze_corpus(root, post_baseline=True)
    _run_corpus_cli(
        [
            str(root),
            "--baseline",
            str(baseline),
            "--json",
            str(report_path),
            "--no-progress",
        ]
    )
    return _corpus_document(report_path)


@pytest.fixture(scope="session")
def corpus_s5_report(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, object]:
    """One single-stage slice-5 corpus run (no baseline: the families it
    distinguishes are analysis-tier facts of the current run)."""
    root = tmp_path_factory.mktemp("wire_freeze_corpus_s5")
    report_path = root / "corpus.report.json"
    _materialize_corpus_tree(_WIRE_FREEZE_CORPUS_S5, root)
    _run_corpus_cli([str(root), "--json", str(report_path), "--no-progress"])
    return _corpus_document(report_path)


@pytest.fixture(autouse=True)
def _clear_workspace_intent_store_cache() -> Generator[None, None, None]:
    from codeclone.surfaces.mcp._workspace_intent_store import (
        clear_workspace_intent_store_cache,
    )

    clear_workspace_intent_store_cache()
    yield
    clear_workspace_intent_store_cache()


@pytest.fixture(autouse=True)
def _track_sqlite_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.setattr(
        sqlite3,
        "connect",
        make_tracking_connect(sqlite3.connect),
    )
    yield


@pytest.fixture(autouse=True)
def _reset_observability_runtime(
    request: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    yield
    from codeclone.observability.runtime import shutdown

    shutdown()
    close_tracked_sqlite_connections()
    if request.node.get_closest_marker("needs_sqlite_cleanup") is not None:
        sweep_leaked_sqlite_connections_via_gc()


@pytest.fixture
def report_meta_factory() -> ReportMetaFactory:
    def _make(**overrides: object) -> dict[str, object]:
        runtime_tag = current_python_tag()
        runtime_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        meta: dict[str, object] = {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "codeclone_version": "1.4.0",
            "python_version": runtime_version,
            "python_tag": runtime_tag,
            "baseline_path": "/repo/codeclone.baseline.json",
            "baseline_fingerprint_version": "1",
            "baseline_schema_version": "1.0",
            "baseline_python_tag": runtime_tag,
            "baseline_generator_name": "codeclone",
            "baseline_generator_version": "1.4.0",
            "baseline_payload_sha256": "a" * 64,
            "baseline_payload_sha256_verified": True,
            "baseline_loaded": True,
            "baseline_status": "ok",
            "cache_path": "/repo/.codeclone/cache.json",
            "cache_schema_version": CACHE_VERSION,
            "cache_status": "ok",
            "cache_used": True,
            "files_skipped_source_io": 0,
            "report_generated_at_utc": "2026-03-10T12:00:00Z",
        }
        meta.update(overrides)
        return meta

    return _make
