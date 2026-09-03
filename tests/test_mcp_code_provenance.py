# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""X-01: a stale long-lived MCP process must be distinguishable from a fresh one.

The release string ``version`` is constant across every commit of a release, so
it cannot carry this fact.  These tests pin the *derivation rule* of the code
marker that can: it moves when the served code moves and stays put when it does
not.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from codeclone import __version__ as RELEASE_VERSION
from codeclone.surfaces.mcp import _code_provenance
from codeclone.surfaces.mcp._code_provenance import (
    compute_code_provenance,
    process_code_provenance,
)
from codeclone.surfaces.mcp._session_shared import (
    ExecutionEvent,
    MCPAnalysisRequest,
    MCPRunRecord,
    mint_execution_event_id,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService


def _reset_process_provenance() -> None:
    """Drop the per-process value so a test can stand in for a new process.

    Memoization is how "computed once" is implemented, not what is pinned: the
    pins below assert the served *value*, so they stay meaningful even if the
    memoization is removed.
    """
    cache_clear = getattr(process_code_provenance, "cache_clear", None)
    if cache_clear is not None:
        cache_clear()


@pytest.fixture(autouse=True)
def _clean_process_provenance_cache() -> Iterator[None]:
    _reset_process_provenance()
    yield
    _reset_process_provenance()


def _source_tree(root: Path, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "__init__.py").write_text(body, encoding="utf-8")
    return root


def _record(tmp_path: Path) -> MCPRunRecord:
    return MCPRunRecord(
        run_id="x01run",
        root=tmp_path,
        request=MCPAnalysisRequest(root=str(tmp_path), respect_pyproject=False),
        comparison_settings=(),
        report_document={"meta": {}},
        summary={"run_id": "x01run"},
        changed_paths=(),
        changed_projection=None,
        func_clones_count=0,
        block_clones_count=0,
        project_metrics=None,
        coverage_join=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
        execution=ExecutionEvent(
            execution_event_id=mint_execution_event_id(),
            root=tmp_path,
            semantic_report_id="x01run",
        ),
    )


def _service_on_source_tree(
    monkeypatch: pytest.MonkeyPatch,
    source_root: Path,
) -> CodeCloneMCPService:
    """A service as built by a process loaded from ``source_root``."""
    _reset_process_provenance()
    monkeypatch.setattr(
        _code_provenance,
        "package_source_root",
        lambda: source_root,
    )
    return CodeCloneMCPService(history_limit=2)


def _provenance_of(payload: Mapping[str, object]) -> Mapping[str, object]:
    provenance = payload["code_provenance"]
    assert isinstance(provenance, dict)
    return provenance


def _summary_provenance(
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_root: Path,
    tmp_path: Path,
) -> Mapping[str, object]:
    """Build a run-summary payload served by a process loaded from ``source_root``."""
    service = _service_on_source_tree(monkeypatch, source_root)
    record = _record(tmp_path)
    return _provenance_of(service._summary_payload(record.summary, record=record))


# ----------------------------------------------------------------------
# The headline fact: two code states, two distinguishable responses.
# ----------------------------------------------------------------------


def test_run_summary_distinguishes_two_code_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _summary_provenance(
        monkeypatch,
        source_root=_source_tree(tmp_path / "state_one" / "codeclone", "VALUE = 1\n"),
        tmp_path=tmp_path,
    )
    second = _summary_provenance(
        monkeypatch,
        source_root=_source_tree(tmp_path / "state_two" / "codeclone", "VALUE = 2\n"),
        tmp_path=tmp_path,
    )
    assert first["code_digest"] != second["code_digest"], (
        "two different code states produced the same marker: a stale server "
        "stays indistinguishable from a fresh one"
    )


def test_run_summary_keeps_the_release_version_next_to_the_code_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The marker is additive: it must not be smuggled into ``version``."""
    service = _service_on_source_tree(
        monkeypatch,
        _source_tree(tmp_path / "pkg" / "codeclone", "VALUE = 1\n"),
    )
    record = _record(tmp_path)
    payload = service._summary_payload(record.summary, record=record)

    # RELEASE_VERSION is bound at collection time: tests/test_init.py reloads
    # `codeclone` with a fake metadata version and leaves it rebound.
    assert payload["version"] == RELEASE_VERSION
    provenance = _provenance_of(payload)
    assert provenance["code_digest"] != payload["version"]
    assert provenance["process_start_epoch"] == service._agent_start_epoch


# ----------------------------------------------------------------------
# The derivation rule, both directions.
# ----------------------------------------------------------------------


def test_code_digest_moves_with_source_content(tmp_path: Path) -> None:
    tree = _source_tree(tmp_path / "codeclone", "VALUE = 1\n")
    before = compute_code_provenance(tree)
    assert before["source"] == "source_tree"
    assert before["code_digest"].startswith("sha256:")

    # Same byte length: a (size, mtime)-shaped rule would miss this edit.
    (tree / "__init__.py").write_text("VALUE = 2\n", encoding="utf-8")
    after = compute_code_provenance(tree)
    assert after["code_digest"] != before["code_digest"]


def test_code_digest_moves_with_source_layout(tmp_path: Path) -> None:
    tree = _source_tree(tmp_path / "codeclone", "VALUE = 1\n")
    flat = compute_code_provenance(tree)["code_digest"]

    nested = tree / "sub"
    nested.mkdir()
    (nested / "mod.py").write_text("HELPER = 1\n", encoding="utf-8")
    added = compute_code_provenance(tree)["code_digest"]
    assert added != flat

    # Identical content under a different name is still different code.
    (nested / "mod.py").rename(nested / "renamed.py")
    assert compute_code_provenance(tree)["code_digest"] != added


def test_code_digest_does_not_move_without_a_source_change(tmp_path: Path) -> None:
    """The reverse skew: a marker that drifts on its own is noise, not evidence."""
    tree = _source_tree(tmp_path / "codeclone", "VALUE = 1\n")
    before = compute_code_provenance(tree)

    # Wall clock moves, file timestamps move, a non-source file appears.
    os.utime(tree / "__init__.py", (2_000_000_000, 2_000_000_000))
    os.utime(tree, (2_000_000_000, 2_000_000_000))
    (tree / "notes.txt").write_text("unrelated\n", encoding="utf-8")
    (tree / "py.typed").write_text("", encoding="utf-8")

    after = compute_code_provenance(tree)
    assert after["code_digest"] == before["code_digest"]


def test_code_provenance_is_captured_once_at_session_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A lazily computed marker would report post-edit disk for pre-edit code."""
    state = {"digest": "sha256:before"}
    calls: list[str] = []

    def _fake(package_root: Path | None) -> dict[str, str]:
        calls.append(state["digest"])
        return {
            "code_digest": state["digest"],
            "source": "source_tree",
            "source_root": "/probe",
        }

    monkeypatch.setattr(_code_provenance, "compute_code_provenance", _fake)
    _reset_process_provenance()

    service = CodeCloneMCPService(history_limit=2)
    # The disk moves on after the process is up; the served code did not.
    state["digest"] = "sha256:after"

    record = _record(tmp_path)
    first = service._summary_payload(record.summary, record=record)
    second = service._summary_payload(record.summary, record=record)

    first_provenance = first["code_provenance"]
    second_provenance = second["code_provenance"]
    assert isinstance(first_provenance, dict)
    assert isinstance(second_provenance, dict)
    assert first_provenance["code_digest"] == "sha256:before"
    assert second_provenance["code_digest"] == "sha256:before"
    assert calls == ["sha256:before"]


# ----------------------------------------------------------------------
# Honest unknown: no git, no sources, no fabricated value.
# ----------------------------------------------------------------------


def test_installed_tree_without_git_still_reports_a_real_digest(
    tmp_path: Path,
) -> None:
    tree = _source_tree(tmp_path / "site-packages" / "codeclone", "VALUE = 1\n")
    assert not any(tmp_path.rglob(".git"))

    provenance = compute_code_provenance(tree)
    assert provenance["source"] == "source_tree"
    assert provenance["code_digest"].startswith("sha256:")
    assert provenance["source_root"] == str(tree)


@pytest.mark.parametrize("case", ["missing", "no_python_sources", "no_root"])
def test_sources_that_cannot_be_read_report_unknown(
    tmp_path: Path,
    case: str,
) -> None:
    if case == "missing":
        target: Path | None = tmp_path / "absent"
    elif case == "no_python_sources":
        target = tmp_path / "compiled"
        target.mkdir()
        (target / "__init__.pyc").write_bytes(b"\x00\x01")
    else:
        target = None

    provenance = compute_code_provenance(target)
    assert provenance["source"] == "unknown"
    assert provenance["code_digest"] == "unknown"
    assert provenance["source_root"] == ""


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission semantics")
def test_unreadable_source_file_reports_unknown(tmp_path: Path) -> None:
    if os.geteuid() == 0:  # pragma: no cover - root ignores the permission bits
        pytest.skip("root can read mode 0o000 files")
    tree = _source_tree(tmp_path / "codeclone", "VALUE = 1\n")
    locked = tree / "locked.py"
    locked.write_text("SECRET = 1\n", encoding="utf-8")
    os.chmod(locked, 0o000)
    try:
        provenance = compute_code_provenance(tree)
    finally:
        os.chmod(locked, 0o600)
    assert provenance["source"] == "unknown"
    assert provenance["code_digest"] == "unknown"


def test_changed_paths_analysis_also_names_the_serving_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PR-style review is analysis truth too, so it carries the same marker."""
    service = _service_on_source_tree(
        monkeypatch,
        _source_tree(tmp_path / "pkg" / "codeclone", "VALUE = 1\n"),
    )
    record = _record(tmp_path)
    provenance = _provenance_of(service._changed_analysis_payload(record))

    assert str(provenance["code_digest"]).startswith("sha256:")
    summary = service._summary_payload(record.summary, record=record)
    assert provenance == summary["code_provenance"]


def test_process_provenance_reads_the_loaded_package(tmp_path: Path) -> None:
    """The real resolver points at the package this process actually imported."""
    root = _code_provenance.package_source_root()
    assert root is not None
    assert root.name == "codeclone"
    assert (root / "surfaces" / "mcp" / "_code_provenance.py").is_file()

    provenance = process_code_provenance()
    assert provenance["source"] == "source_tree"
    assert provenance["code_digest"].startswith("sha256:")
    assert provenance is process_code_provenance()
