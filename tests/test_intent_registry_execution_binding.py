# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The registry's durable before-execution binding, across a process death.

``run_id`` names a report, not a reading of the source.  In RAM the session
already keeps the two apart (RULING-2026-09-02): executions are keyed by
``execution_event_id`` and the before-run is addressed as an event.  Across a
restart none of that survived -- the persisted record carried the report's
name and nothing about the execution that produced it -- so recovery took
``(root, run_id)``, found the newest execution answering to that name, and
declared it the historical before-run.

Measured on 57719dee: after a restart and an analysis-invariant edit, recovery
accepted, and the recovered intent's before-run answered with the *post-edit*
bytes.  The report digest is the only guard on that path and it collides by
design for exactly this class of edit, so the guard is blind where it matters.

The edit below is same-size with ``mtime_ns`` restored: it defeats every
stat-based witness, so only a content digest can tell the two executions
apart.  That is the point of the acceptance -- the semantic identity collides
on purpose, and the execution witness is the only thing left that can speak.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from codeclone.surfaces.mcp._session_shared import (
    MCPAnalysisRequest,
    MCPRunRecord,
)
from codeclone.surfaces.mcp._workspace_intent_store import (
    clear_workspace_intent_store_cache,
)
from codeclone.surfaces.mcp._workspace_intents import (
    LEGACY_REGISTRY_VERSION,
    REGISTRY_VERSION,
    compute_intent_digest,
    find_workspace_intent,
    validate_workspace_record,
    verify_intent_integrity,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService

_MODULE = (
    "def widen(values):\n"
    "    total = 0  # accumulator\n"
    "    for value in values:\n"
    "        total += value\n"
    "    return total\n"
)
# Same length, so (mtime_ns, size) is restorable to the byte: 'accumulator'
# and 'accumulated' are both eleven characters.  A comment's text is invisible
# to analysis, which is what makes the two executions share one run_id.
_EDITED_MODULE = _MODULE.replace("# accumulator", "# accumulated")
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


def _analyze(service: CodeCloneMCPService, root: Path) -> tuple[str, MCPRunRecord]:
    payload = service.analyze_repository(MCPAnalysisRequest(root=str(root)))
    run_id = str(payload["run_id"])
    return run_id, service._runs.get_for_root(run_id, root=root)


def _dead_pid() -> int:
    """A pid whose process has really exited, reaped before it is used."""

    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def _declared(root: Path, intent: str) -> tuple[CodeCloneMCPService, str, MCPRunRecord]:
    """A committed repository, one execution over it, and an active intent.

    The server stamps a pid that is already dead, so the restart below needs no
    monkeypatched liveness: the real probe reads the real fate of a real pid.
    """

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
    pid = _dead_pid()
    service._agent_pid, service._agent_label = pid, f"pid-{pid}"
    _run_a, record_a = _analyze(service, root)
    started = service.start_controlled_change(
        root=str(root), scope=_SCOPE, intent=intent
    )
    assert started["edit_allowed"] is True
    return service, str(started["intent_id"]), record_a


def _restart() -> CodeCloneMCPService:
    """The server process is gone: no session state, and a fresh store handle.

    Clearing the store cache is what makes this a restart rather than a second
    concurrent agent -- the new session re-opens the registry from disk instead
    of inheriting the writer's live connection.
    """

    clear_workspace_intent_store_cache()
    return CodeCloneMCPService(history_limit=6)


def _invariant_edit(root: Path) -> str:
    """Rewrite one comment in place: same bytes count, same ``mtime_ns``."""

    target = root / "pkg" / "a.py"
    before = target.stat()
    target.write_text(_EDITED_MODULE, encoding="utf-8")
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = target.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    return _sha256(target)


def _persisted_payload(root: Path, intent_id: str) -> Mapping[str, object]:
    """The signed document as it sits on disk, read back as bytes."""

    registry = root / ".codeclone" / "intents"
    matches = sorted(registry.glob(f"*-{intent_id}.json"))
    assert matches, f"no persisted record for {intent_id}"
    payload = json.loads(matches[-1].read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _rewrite_persisted_record(
    root: Path, intent_id: str, changes: Mapping[str, object]
) -> dict[str, object]:
    """Leave a differently-shaped record on disk, validly signed for its shape.

    ``None`` in ``changes`` removes the key, which is how the pre-binding
    generation is reproduced.  Re-signing matters: an unsigned forgery would
    be refused by the integrity check and prove nothing about the generation
    gate under test.
    """

    path = sorted((root / ".codeclone" / "intents").glob(f"*-{intent_id}.json"))[-1]
    payload = dict(json.loads(path.read_text(encoding="utf-8")))
    for key, value in changes.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    payload.pop("integrity", None)
    payload["integrity"] = {"payload_sha256": compute_intent_digest(payload)}
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return payload


def _refusal_after_restart(root: Path, intent_id: str) -> Mapping[str, object]:
    """Restart, analyse the untouched tree, and offer that run to recovery.

    Nothing is edited, so any refusal here is about the RECORD rather than
    about the tree having moved -- which is what separates these two boundary
    tests from the superseded-execution one.
    """

    restarted = _restart()
    stored = find_workspace_intent(
        root=root, intent_id=intent_id, apply_lazy_close=False
    )
    assert stored is not None, "the record must stay readable to be refused"
    run_id, _record = _analyze(restarted, root)
    rejected = _recover(restarted, root, run_id=run_id, intent_id=intent_id)
    assert rejected["action_taken"] == "recovery_rejected"
    assert intent_id not in restarted._active_intents
    assert str(rejected["next_step"]).strip()
    return rejected


def _recover(
    service: CodeCloneMCPService, root: Path, *, run_id: str, intent_id: str
) -> Mapping[str, object]:
    payload = service.manage_change_intent(
        action="recover", root=str(root), run_id=run_id, intent_id=intent_id
    )
    assert isinstance(payload, dict)
    return payload


# ---------------------------------------------------------------------------
# The acceptance: the binding survives the process, and names one execution
# ---------------------------------------------------------------------------


def test_the_persisted_record_names_the_execution_the_intent_was_declared_on(
    tmp_path: Path,
) -> None:
    """The durable witness is content-bound, and it is A's.

    Witness before equality: the run ids collide by design, so the assertions
    that matter are the two that do not -- a different event, over different
    bytes.  The record on disk must carry both, or a restart has nothing left
    to tell A from B with.
    """

    _service, intent_id, record_a = _declared(tmp_path, "one comment, same length")
    restarted = _restart()
    _invariant_edit(tmp_path)
    _run_b, record_b = _analyze(restarted, tmp_path)

    assert record_a.run_id == record_b.run_id
    assert (
        record_a.execution.execution_event_id != record_b.execution.execution_event_id
    )
    assert (
        record_a.execution.source_state_digest != record_b.execution.source_state_digest
    )

    payload = _persisted_payload(tmp_path, intent_id)
    assert payload["registry_version"] == REGISTRY_VERSION
    witness = payload["before_execution"]
    assert isinstance(witness, dict)
    assert witness["execution_event_id"] == record_a.execution.execution_event_id
    assert witness["report_semantic_id"] == record_a.run_id
    assert witness["source_state_digest"] == record_a.execution.source_state_digest
    assert witness["workspace_witness"] == record_a.execution.workspace_witness


def test_a_later_execution_of_the_same_report_never_takes_the_before_runs_place(
    tmp_path: Path,
) -> None:
    """Boundary one: silent adoption.

    ``analyze A -> start -> restart -> invariant edit -> analyze B``.  B shares
    A's name and read different bytes.  Recovery must refuse it, and the
    refusal must resolve both sides: the before-execution it is holding out
    for, and the execution it was offered.
    """

    _service, intent_id, record_a = _declared(tmp_path, "B must not become A")
    restarted = _restart()
    before_bytes = _sha256(tmp_path / "pkg" / "a.py")
    after_bytes = _invariant_edit(tmp_path)
    assert before_bytes != after_bytes
    run_b, record_b = _analyze(restarted, tmp_path)

    recovered = _recover(restarted, tmp_path, run_id=run_b, intent_id=intent_id)
    assert recovered["action_taken"] == "recovery_rejected"
    assert recovered["reason"] == "before_execution_superseded"
    assert intent_id not in restarted._active_intents

    details = recovered["details"]
    assert isinstance(details, dict)
    # before resolves to A; after resolves to B.
    assert details["before_execution_event_id"] == record_a.execution.execution_event_id
    assert (
        details["before_source_state_digest"] == record_a.execution.source_state_digest
    )
    assert (
        details["offered_execution_event_id"] == record_b.execution.execution_event_id
    )
    assert (
        details["offered_source_state_digest"] == record_b.execution.source_state_digest
    )
    # A typed outcome the caller can act on, not a bare error.
    assert "next_step" in recovered
    assert str(recovered["next_step"]).strip()


def test_a_content_proven_execution_re_establishes_the_binding(
    tmp_path: Path,
) -> None:
    """Boundary two: over-refusal.

    A migration that refuses everything is as broken as one that adopts
    everything.  Restart with nothing edited and analyse again: the new
    execution is a different event that read *exactly* the bytes the intent was
    declared on.  Equality is proven by digest, never by the shared name, so
    the binding is re-established and the edit window re-opens for real work.
    """

    _service, intent_id, record_a = _declared(tmp_path, "nothing edited yet")
    restarted = _restart()
    run_a2, record_a2 = _analyze(restarted, tmp_path)
    assert (
        record_a2.execution.execution_event_id != record_a.execution.execution_event_id
    )
    assert (
        record_a2.execution.source_state_digest
        == record_a.execution.source_state_digest
    )

    recovered = _recover(restarted, tmp_path, run_id=run_a2, intent_id=intent_id)
    assert recovered["action_taken"] == "recovered"
    assert intent_id in restarted._active_intents

    # The recovered intent is not a museum piece: it still verifies real work.
    _invariant_edit(tmp_path)
    run_c, _record_c = _analyze(restarted, tmp_path)
    finished = restarted.finish_controlled_change(
        intent_id=intent_id, changed_files=["pkg/a.py"], after_run_id=run_c
    )
    assert finished["status"] == "accepted"


def test_a_record_without_the_witness_is_a_typed_legacy_refusal(
    tmp_path: Path,
) -> None:
    """A legacy record is not upgraded by binding it to the newest execution.

    The pre-binding registry wrote the report's name and nothing about the
    reading that produced it.  Such a record cannot prove which execution it
    was declared on -- not even against an execution that would in fact match
    -- so the only honest answer is a refusal that says so by version.
    """

    _service, intent_id, _record_a = _declared(tmp_path, "written by an old server")
    # Exactly the shape the previous registry produced: no witness, older
    # version, re-signed so it is a valid record of its own generation.
    _rewrite_persisted_record(
        tmp_path, intent_id, {"before_execution": None, "registry_version": "2"}
    )

    rejected = _refusal_after_restart(tmp_path, intent_id)
    assert rejected["reason"] == "registry_record_predates_execution_binding"
    details = rejected["details"]
    assert isinstance(details, dict)
    assert details["registry_version"] == "2"
    assert details["required_registry_version"] == REGISTRY_VERSION


def test_the_integrity_signature_covers_the_before_execution_witness(
    tmp_path: Path,
) -> None:
    """A witness that can be edited in place is not a witness.

    The signature is over the whole unsigned payload, so it must move when the
    witness moves.  Both readers are probed: the integrity check, and the
    document parser that every read goes through.
    """

    _service, intent_id, _record_a = _declared(tmp_path, "tamper with the witness")
    payload = dict(_persisted_payload(tmp_path, intent_id))
    assert verify_intent_integrity(payload) is True
    assert validate_workspace_record(payload) is not None

    stored = payload["before_execution"]
    assert isinstance(stored, dict)
    witness = dict(stored)
    witness["source_state_digest"] = "0" * 64
    tampered = {**payload, "before_execution": witness}
    assert verify_intent_integrity(tampered) is False
    assert validate_workspace_record(tampered) is None

    swapped = {
        **payload,
        "before_execution": {**witness, "execution_event_id": "f" * 32},
    }
    assert verify_intent_integrity(swapped) is False
    assert validate_workspace_record(swapped) is None


def test_the_registry_version_moves_only_with_the_binding(tmp_path: Path) -> None:
    """The version is the wire fact that a witness is there to be read.

    ``LEGACY_REGISTRY_VERSION`` keeps naming the lease-less first generation;
    the constant that moved is the one the writer stamps.
    """

    assert LEGACY_REGISTRY_VERSION == "1"
    assert REGISTRY_VERSION == "3"
    _service, intent_id, _record = _declared(tmp_path, "version rides the binding")
    payload = _persisted_payload(tmp_path, intent_id)
    assert payload["registry_version"] == "3"
    assert "before_execution" in payload


def test_every_production_execution_carries_a_content_witness(tmp_path: Path) -> None:
    """The abstention above is unreachable from any real analysis.

    A pair of executions that both recorded nothing keeps the older
    name-addressed behaviour, which would be a hole if production could
    produce such an execution.  It cannot: ``build_run_content_manifest``
    returns a mapping, never ``None``, and ``session.py`` is the only place in
    the package that builds an :class:`ExecutionEvent`.  Both halves are
    asserted here, so a second producer or a nullable manifest reds this.
    """

    sources = Path("codeclone/surfaces/mcp").rglob("*.py")
    producers = [
        path
        for path in [*sources, *Path("codeclone").rglob("*.py")]
        if "ExecutionEvent(" in path.read_text(encoding="utf-8")
        and path.name != "execution_event.py"
    ]
    assert {path.as_posix() for path in producers} == {
        "codeclone/surfaces/mcp/session.py"
    }

    _service, _intent_id, record_a = _declared(tmp_path, "content witness always")
    assert record_a.execution.content_manifest is not None
    assert record_a.execution.source_state_digest is not None


def test_a_witness_that_recorded_nothing_is_not_promoted_by_a_run_that_did(
    tmp_path: Path,
) -> None:
    """Asymmetric absence is a refusal, never a free pass.

    A persisted witness with a null content digest cannot be repaired by
    offering it a run that does have one: they are of different generations,
    and the younger one's evidence says nothing about what the older one read.
    """

    _service, intent_id, record_a = _declared(tmp_path, "null digest on the wire")
    witness = record_a.execution
    _rewrite_persisted_record(
        tmp_path,
        intent_id,
        {
            "before_execution": {
                "execution_event_id": witness.execution_event_id,
                "report_semantic_id": record_a.run_id,
                "source_state_digest": None,
                "workspace_witness": witness.workspace_witness,
            }
        },
    )

    rejected = _refusal_after_restart(tmp_path, intent_id)
    assert rejected["reason"] == "before_execution_has_no_content_witness"
