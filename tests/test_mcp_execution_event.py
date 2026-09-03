# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Execution events: one execution, one event; one semantic report, many events.

``run_id`` is the report's semantic identity (RULING-2026-08-31): two
executions that state the same canonical claims share it by design.  What must
never collapse is the EXECUTION -- the event that read one particular source
state and produced that report (RULING-2026-09-02; RFC 2026-09-02 §III.1).

The session used to hold one record per ``(root, run_id)`` and replace it on
re-registration.  Measured live on b4feb0ff (probe A, 2026-09-03): after a
comment-only edit was re-analysed under the same ``run_id``, the record the
intent was declared against answered with the *after* bytes, and finish still
accepted with ``observed_changed_files: True``.  The evidentiary value of the
before-run was destroyed by the after-run that shared its name.

The acceptance below is the ratified one, in its ratified order: witness
before equality.  Step 1 proves the edit really was analysis-invariant; without
it a slightly-not-invariant edit would fail step 2 for the wrong reason.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.surfaces.mcp._analyzer_invariance import observation_evidence
from codeclone.surfaces.mcp._session_shared import (
    CodeCloneMCPRunStore,
    ExecutionEvent,
    MCPAnalysisRequest,
    MCPRunNotFoundError,
    MCPRunRecord,
    build_served_projection,
    mint_execution_event_id,
)
from codeclone.surfaces.mcp._workspace_hygiene import DirtySnapshot, DirtySnapshotEntry
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.utils.mapping_paths import section

_MODULE = (
    "def widen(values):\n"
    "    total = 0  # accumulator\n"
    "    for value in values:\n"
    "        total += value\n"
    "    return total\n"
)
# Change the TEXT of an existing comment line.  Not a new line (a new line
# moves start_line on every later unit, and risk observations carry lines) and
# not a docstring (docstring_permille would move): the edit must be invisible
# to analysis, and step 1 of the acceptance checks that it was.
_EDITED_MODULE = _MODULE.replace("# accumulator", "# running accumulator")
_PYPROJECT = '[project]\nname = "invariant"\nversion = "0.1.0"\n'
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@e.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@e.com",
}
_SCOPE = {"allowed_files": ["pkg/a.py"]}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evaluation_digest(document: Mapping[str, object]) -> str:
    value = section(document, "integrity.digests.evaluation").get("value")
    assert isinstance(value, str) and value
    return value


def _analyze(service: CodeCloneMCPService, root: Path) -> tuple[str, MCPRunRecord]:
    payload = service.analyze_repository(MCPAnalysisRequest(root=str(root)))
    run_id = str(payload["run_id"])
    return run_id, service._runs.get_for_root(run_id, root=root)


def _first_execution(root: Path) -> tuple[CodeCloneMCPService, str, MCPRunRecord]:
    """A committed repository and the first execution over it."""

    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    package.joinpath("__init__.py").write_text("", encoding="utf-8")
    package.joinpath("a.py").write_text(_MODULE, encoding="utf-8")
    root.joinpath("pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    root.joinpath(".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    for args in (("init",), ("add", "-A"), ("commit", "-m", "init")):
        subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, env=_GIT_ENV
        )
    service = CodeCloneMCPService(history_limit=6)
    return service, *_analyze(service, root)


def _declared(root: Path, intent: str) -> tuple[CodeCloneMCPService, str, MCPRunRecord]:
    """First execution, then an active intent declared against it."""

    service, _run_a, record_a = _first_execution(root)
    started = service.start_controlled_change(
        root=str(root), scope=_SCOPE, intent=intent
    )
    assert started["edit_allowed"] is True
    return service, str(started["intent_id"]), record_a


def _edit_comment(root: Path) -> str:
    root.joinpath("pkg", "a.py").write_text(_EDITED_MODULE, encoding="utf-8")
    return _sha256(root / "pkg" / "a.py")


def _verification(finished: Mapping[str, object]) -> Mapping[str, object]:
    verification = finished["verification"]
    assert isinstance(verification, Mapping)
    return verification


def test_two_executions_of_one_semantic_report_are_both_retained(
    tmp_path: Path,
) -> None:
    """Boundary one: two distinct executions must not collapse into one record.

    Witness before equality (RFC §III.1): the invariance premise first, then
    the shared semantic identity, then the fact that the two executions are
    two records the session still holds, then their distinct witnesses.
    """

    service, _intent_id, record_a = _declared(
        tmp_path, "change the text of one comment"
    )
    _edit_comment(tmp_path)
    _run_b, record_b = _analyze(service, tmp_path)
    # 1. Premise: the edit was analysis-invariant.
    assert _evaluation_digest(record_a.served_report) == _evaluation_digest(
        record_b.served_report
    )
    # 2. One semantic identity, by design.
    assert record_a.run_id == record_b.run_id
    # 3. Two executions, both held: the after-run must not replace the before-run.
    held = [
        record
        for record in service._runs.records()
        if record.run_id == record_a.run_id and record.root == tmp_path.resolve()
    ]
    assert len(held) == 2, "the before execution was replaced by its successor"
    # 4. Two events, two witnesses: the execution id never enters the run id,
    #    and the source state the second execution read is not the first's.
    assert (
        record_a.execution.execution_event_id != record_b.execution.execution_event_id
    )
    assert (
        record_a.execution.source_state_digest != record_b.execution.source_state_digest
    )
    assert record_a.execution.workspace_witness != record_b.execution.workspace_witness


def test_the_intent_answers_with_the_execution_it_was_declared_against(
    tmp_path: Path,
) -> None:
    """Boundary one, seen from verification: before is A's execution, not B's.

    The intent was declared while execution A's bytes were on disk.  After
    execution B under the same run_id, the record the intent resolves to must
    still carry A's content witness for the edited file -- otherwise the
    structural comparison is an analyzer invariant of the edited tree, not a
    before/after.  Verification then addresses A as before and B as after.
    """

    service, intent_id, _record_a = _declared(
        tmp_path, "change the text of one comment"
    )
    before_bytes = _sha256(tmp_path / "pkg" / "a.py")
    after_bytes = _edit_comment(tmp_path)
    assert before_bytes != after_bytes
    run_b, _record_b = _analyze(service, tmp_path)
    bound, _intent = service._resolve_intent(run_id=None, intent_id=intent_id)
    witness = (bound.execution.content_manifest or {}).get("pkg/a.py")
    assert witness != after_bytes, "the intent resolved to the after execution"
    assert witness == before_bytes
    # 5. Accepted: the change is proven invisible to analysis by a later
    #    execution that read different bytes.
    finished = service.finish_controlled_change(
        intent_id=intent_id, changed_files=["pkg/a.py"], after_run_id=run_b
    )
    verification = _verification(finished)
    assert (finished["status"], verification["reason"]) == (
        "accepted",
        "analyzer_invariant",
    )
    assert verification["observed_changed_files"] is True


def test_a_later_execution_that_observed_no_edit_is_the_typed_dead_end(
    tmp_path: Path,
) -> None:
    """Fresh is not enough: the after execution must have read a changed state.

    analyze A -> start -> analyze B with nothing edited.  B is a later
    execution, so the old ordinal law accepted it and reported the claimed
    file as observed.  Its workspace witness equals A's: it read exactly the
    state the intent was declared on, so it observed no edit and the answer is
    the existing typed dead end, whose remedy is to analyse after editing.
    """

    service, intent_id, record_a = _declared(tmp_path, "nothing edited yet")
    run_b, record_b = _analyze(service, tmp_path)
    assert (
        record_a.execution.execution_event_id != record_b.execution.execution_event_id
    )
    assert record_a.execution.workspace_witness == record_b.execution.workspace_witness
    finished = service.finish_controlled_change(
        intent_id=intent_id, changed_files=["pkg/a.py"], after_run_id=run_b
    )
    assert (finished["status"], _verification(finished)["reason"]) == (
        "unverified",
        "after_run_not_new",
    )


def test_a_vanished_before_execution_is_never_replaced_by_a_sibling_execution(
    tmp_path: Path,
) -> None:
    """When the intent's execution is gone, a later execution of the same
    report is not handed back as the before-run: the answer is the typed
    ``no_before_run``, whose remedy is to analyse and declare again."""

    service, intent_id, record_a = _declared(tmp_path, "before execution lost")
    # Held now: the next analysis prunes an intent whose execution is gone,
    # so the resolver below is probed with the binding, not through the map.
    intent = service._active_intents[intent_id]
    with service._runs._lock:
        service._runs._forget_locked(record_a.execution.execution_event_id)
    _edit_comment(tmp_path)
    run_b, _record_b = _analyze(service, tmp_path)
    verified = service.check_patch_contract(
        mode="verify",
        intent_id=intent_id,
        after_run_id=run_b,
        changed_files=["pkg/a.py"],
    )
    assert (verified["status"], verified["reason"]) == ("unverified", "no_before_run")
    # The before-run resolver alone, isolated from the intent resolution and
    # the pruning around it: it refuses rather than answering with B.
    with pytest.raises(MCPRunNotFoundError):
        service._before_run_for(run_b, binding_intent=intent, root=None)


def test_two_executions_of_one_unchanged_tree_share_the_report_and_the_witness(
    tmp_path: Path,
) -> None:
    """Boundary two: one tree, two executions -- one report, one witness, two events."""

    service, run_a, record_a = _first_execution(tmp_path)
    run_b, record_b = _analyze(service, tmp_path)
    assert run_a == run_b
    assert (
        record_a.execution.source_state_digest == record_b.execution.source_state_digest
    )
    assert record_a.execution.workspace_witness == record_b.execution.workspace_witness
    assert (
        record_a.execution.execution_event_id != record_b.execution.execution_event_id
    )
    # The execution id is not part of the report's identity.
    assert _evaluation_digest(record_a.served_report) == _evaluation_digest(
        record_b.served_report
    )


def test_a_path_both_executions_recorded_under_one_digest_is_not_an_observed_change(
    tmp_path: Path,
) -> None:
    """Per path: the after-run read the bytes on disk, but so did the before-run.

    Such a path was not witnessed as a change by this pair -- the edit never
    reached it or predates the before-run -- so it is *unobserved*, never
    silently counted as observed.  A path whose digest moved between the two
    executions stays observed.
    """

    files = {"kept.py": "x = 1\n", "moved.py": "y = 2\n"}
    for name, text in files.items():
        tmp_path.joinpath(name).write_text(text, encoding="utf-8")
    digests = {name: _sha256(tmp_path / name) for name in files}
    contradicted, unobserved = observation_evidence(
        root=tmp_path,
        changed_files=[*files],
        manifest=None,
        content_manifest=digests,
        dirty_paths=frozenset(files),
        before_content_manifest={**digests, "moved.py": "0" * 64},
    )
    assert (contradicted, unobserved) == ((), ("kept.py",))


# ---------------------------------------------------------------------------
# The event and the store, in isolation
# ---------------------------------------------------------------------------


def _record(
    root: Path, run_id: str, *, event: ExecutionEvent | None = None
) -> MCPRunRecord:
    return MCPRunRecord(
        run_id=run_id,
        root=root,
        request=MCPAnalysisRequest(root=str(root), respect_pyproject=False),
        comparison_settings=(),
        served_report=build_served_projection({}),
        summary={"run_id": run_id},
        changed_paths=(),
        changed_projection=None,
        func_clones_count=0,
        block_clones_count=0,
        reachable_qualnames=frozenset(),
        coverage_join=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
        execution=event
        or ExecutionEvent(
            execution_event_id=mint_execution_event_id(),
            root=root,
            semantic_report_id=run_id,
        ),
    )


def _snapshot(
    *entries: tuple[str, str], captured_at: str = "2026-09-03T00:00:00Z"
) -> DirtySnapshot:
    return DirtySnapshot(
        git_available=True,
        captured_at_utc=captured_at,
        entries=tuple(
            DirtySnapshotEntry(
                path=path, status_xy=" M", digest=digest, digest_status="sha256"
            )
            for path, digest in entries
        ),
    )


def _event(root: Path, event_id: str, **carriers: object) -> ExecutionEvent:
    return ExecutionEvent(
        execution_event_id=event_id,
        root=root,
        semantic_report_id="r",
        **carriers,  # type: ignore[arg-type]
    )


def test_the_source_witness_is_the_bytes_the_analysis_read_in_any_order(
    tmp_path: Path,
) -> None:
    """Order-free, content-sensitive, and recomputed on replace."""

    a, b = "a" * 64, "b" * 64
    forward = _event(tmp_path, "e1", content_manifest={"pkg/a.py": a, "pkg/b.py": b})
    backward = _event(tmp_path, "e2", content_manifest={"pkg/b.py": b, "pkg/a.py": a})
    assert forward.source_state_digest == backward.source_state_digest
    assert forward.execution_event_id != backward.execution_event_id
    moved = replace(forward, content_manifest={"pkg/a.py": a, "pkg/b.py": "c" * 64})
    assert moved.source_state_digest != forward.source_state_digest
    # No witness at all is a different fact from an empty measurement.
    assert _event(tmp_path, "e3").source_state_digest is None
    assert _event(tmp_path, "e4", content_manifest={}).source_state_digest is not None


def test_the_workspace_witness_reads_git_state_but_never_the_clock(
    tmp_path: Path,
) -> None:
    base = _event(
        tmp_path,
        "e1",
        content_manifest={"pkg/a.py": "a" * 64},
        dirty_snapshot=_snapshot(("pyproject.toml", "d" * 64)),
    )
    later_clock = replace(
        base,
        dirty_snapshot=_snapshot(
            ("pyproject.toml", "d" * 64), captured_at="2026-09-04T00:00:00Z"
        ),
    )
    assert later_clock.workspace_witness == base.workspace_witness
    other_dirt = replace(base, dirty_snapshot=_snapshot(("pyproject.toml", "e" * 64)))
    assert other_dirt.workspace_witness != base.workspace_witness
    assert other_dirt.source_state_digest == base.source_state_digest
    # A stat-only field never reaches either witness: the manifest is navigation.
    restatted = replace(base, manifest={"pkg/a.py": {"mtime_ns": 1, "size": 2}})
    assert restatted.workspace_witness == base.workspace_witness


def test_an_execution_event_refuses_an_empty_id_or_an_unnamed_report(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="non-empty id"):
        ExecutionEvent(execution_event_id=" ", root=tmp_path, semantic_report_id="r1")
    with pytest.raises(ValueError, match="names the report"):
        ExecutionEvent(execution_event_id="e", root=tmp_path, semantic_report_id="")


def test_the_store_keeps_a_pinned_execution_beside_its_successor(
    tmp_path: Path,
) -> None:
    """Boundary one at the store: the same report twice is two executions.

    Unpinned, the superseded execution is released at once -- nothing can
    name it.  Pinned (an intent's before-run), it survives its successor, and
    the key still resolves to the newest execution.
    """

    store = CodeCloneMCPRunStore(history_limit=4)
    first = store.register(_record(tmp_path, "run1"))
    second = store.register(_record(tmp_path, "run1"))
    assert [r.execution.execution_event_id for r in store.records()] == [
        second.execution.execution_event_id
    ]
    assert not store.holds_execution(first.execution.execution_event_id)

    store = CodeCloneMCPRunStore(history_limit=4)
    first = store.register(_record(tmp_path, "run1"))
    store.pin_execution(first.execution.execution_event_id)
    second = store.register(_record(tmp_path, "run1"))
    assert [r.execution.execution_event_id for r in store.records()] == [
        first.execution.execution_event_id,
        second.execution.execution_event_id,
    ]
    assert store.get_for_root("run1", root=tmp_path) is second
    assert store.get_execution(first.execution.execution_event_id) is first
    assert store.execution_ordinal(first.execution.execution_event_id) == 1
    assert store.execution_ordinal(second.execution.execution_event_id) == 2
    assert store.is_latest_execution(second.execution.execution_event_id, root=tmp_path)
    assert not store.is_latest_execution(
        first.execution.execution_event_id, root=tmp_path
    )
    store.unpin_execution(first.execution.execution_event_id)
    assert [r.execution.execution_event_id for r in store.records()] == [
        second.execution.execution_event_id
    ]


def test_one_execution_registered_twice_stays_one_execution(tmp_path: Path) -> None:
    """Boundary two at the store: re-registering an event does not split it."""

    store = CodeCloneMCPRunStore(history_limit=4)
    record = _record(tmp_path, "run1")
    store.register(record)
    store.register(replace(record, summary={"run_id": "run1", "refreshed": True}))
    assert len(store.records()) == 1
    assert store.execution_ordinal(record.execution.execution_event_id) == 1
    assert store.records()[0].summary == {"run_id": "run1", "refreshed": True}
