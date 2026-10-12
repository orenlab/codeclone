# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A run found again by a server that did not analyse it (ruling 2026-10-12,
recovery).

Held here, in one process with two services (the separate-process proof is
``test_mcp_run_recovery_acceptance``):

* an analysis registers its execution -- the record names the execution, the
  root, the report and the store run, and carries the run's resident identity
  under this surface's contract;
* a service that never analysed the run restores it by ``(root, run_id)`` and
  answers from the store; it holds the run by its resident identity, never
  whole, and never as its "latest";
* every miss is a typed answer -- ``run_not_found`` (no record, no proof),
  ``run_expired`` (record, collected run: the record is the proof),
  ``store_disabled``, ``incompatible_generation``, ``store_unavailable``,
  ``integrity`` -- each saying whether repeating the call can help;
* an unrecorded finalization is said, and is not restorable;
* the ``payload_evicted`` answer no longer sends a caller round a loop;
* the authority candidates of a run without its payload are served from the
  store.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from codeclone.api import run_restoration as door
from codeclone.api.run_residence import ResidentRun
from codeclone.surfaces.mcp import _run_restoration as restoration
from codeclone.surfaces.mcp._run_residence import resident_identity
from codeclone.surfaces.mcp._run_restoration import (
    RESIDENT_RUN_CONTRACT,
    decode_resident_run,
    encode_resident_run,
)
from codeclone.surfaces.mcp._session_shared import (
    DEFAULT_MCP_HISTORY_LIMIT,
    MCP_RESIDENT_HISTORY_LIMIT,
    MCPRunRecord,
    MCPServiceContractError,
)
from codeclone.surfaces.mcp.messages.run_restoration import (
    RUN_NOT_RESTORABLE_WARNING,
    RUN_UNAVAILABLE_MESSAGES,
    RUN_UNAVAILABLE_NEXT_STEPS,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest
from tests._mcp_restoration_fixtures import Repo, enable_store, make_repo


def _analyze(service: CodeCloneMCPService, repo: Repo) -> str:
    summary = service.analyze_repository(
        MCPAnalysisRequest(root=str(repo.root), respect_pyproject=True)
    )
    return str(summary["run_id"])


def _record(service: CodeCloneMCPService, run_id: str, repo: Repo) -> MCPRunRecord:
    return service._runs.get_for_root(run_id, root=repo.root)


def _analyzed(repo: Repo) -> tuple[str, MCPRunRecord, door.RunSnapshotLink]:
    """One analysis by a service that is then left: the run, its record and
    its stated link."""
    service = CodeCloneMCPService()
    run_id = _analyze(service, repo)
    record = _record(service, run_id, repo)
    link = record.execution.run_snapshot_link
    assert link is not None
    return run_id, record, link


def _write_record(
    repo: Repo,
    link: door.RunSnapshotLink,
    identity: ResidentRun[MCPAnalysisRequest],
    *,
    execution: str,
    contract: str = RESIDENT_RUN_CONTRACT,
) -> None:
    """Finalize one more execution record of ``link``'s run, carrying
    ``identity`` as its overlay -- a record the test crafts, proven against
    its own digest like any other."""
    door.finalize_execution_record(
        store_path=repo.store,
        link=link,
        publisher_lease="",
        execution_event_id=execution,
        root=repo.root,
        record_contract=contract,
        overlay=encode_resident_run(identity),
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    made = make_repo(tmp_path)
    enable_store(monkeypatch, made)
    return made


# -- the policy's numbers, derived from the server's own bounds ---------------


def test_the_retention_window_is_the_servers_own_bounds_and_seven_days() -> None:
    """Four registered runs -- the whole runs one server holds -- 32 records
    -- the identities it keeps of runs whose payload it let go -- and the
    ruling's seven days, spelled as days."""
    window = door.PUBLICATION_RETENTION
    assert window.max_runs == DEFAULT_MCP_HISTORY_LIMIT
    assert window.max_execution_records == MCP_RESIDENT_HISTORY_LIMIT
    assert window.max_age_seconds == int(timedelta(days=7).total_seconds())


# -- an analysis registers its execution --------------------------------------


def test_an_analysis_registers_its_execution_with_its_resident_identity(
    repo: Repo,
) -> None:
    _run_id, record, link = _analyzed(repo)
    rows = repo.rows(
        "SELECT execution_event_id, root, report_run_identity, store_run_id, "
        "record_contract, overlay FROM run_executions"
    )
    assert link.state == "linked"
    assert len(rows) == 1
    execution, root, report, store_run, contract, overlay = rows[0]
    assert (execution, root, report, store_run, contract) == (
        record.execution.execution_event_id,
        str(repo.root.resolve()),
        record.run_id,
        link.store_run_id,
        RESIDENT_RUN_CONTRACT,
    )
    assert isinstance(overlay, bytes)
    assert decode_resident_run(overlay) == resident_identity(record)
    # The publisher's lease ended in the finalization: nothing but the
    # registry's window holds the run now.
    assert repo.rows("SELECT lease_id FROM run_leases") == []


def test_a_fresh_service_restores_the_run_and_answers_from_the_store(
    repo: Repo,
) -> None:
    first = CodeCloneMCPService()
    run_id = _analyze(first, repo)
    expected = first.get_run_summary(run_id, root=str(repo.root))

    second = CodeCloneMCPService()
    assert second._runs.records() == ()
    answered = second.get_run_summary(run_id[:8], root=str(repo.root))
    serving = answered["serving"]
    assert isinstance(serving, dict)
    assert serving["source"] == "run_store", answered

    # The operational fields: where the answer came from, and the age of the
    # service that gave it (each service stamps its own start).
    for summary in (expected, answered):
        summary.pop("serving", None)
        provenance = summary["code_provenance"]
        assert isinstance(provenance, dict)
        provenance.pop("process_start_epoch")
    assert answered == expected
    held = second._runs.held_for_root(run_id, root=repo.root)
    assert isinstance(held, ResidentRun)
    assert held.execution == _record(first, run_id, repo).execution


def test_a_restored_run_is_never_the_sessions_latest(repo: Repo) -> None:
    first = CodeCloneMCPService()
    old = _analyze(first, repo)
    second = CodeCloneMCPService()
    repo.write(5)
    new = _analyze(second, repo)
    second.get_run_summary(old, root=str(repo.root))

    latest = second.get_run_summary(None, root=str(repo.root))
    assert latest["run_id"] == new[:8]

    third = CodeCloneMCPService()
    third.get_run_summary(old, root=str(repo.root))
    unnamed = third.get_run_summary(None, root=str(repo.root))
    assert unnamed["status"] == "unavailable"
    assert unnamed["reason"] == "run_not_found"


# -- every miss is typed ------------------------------------------------------


def test_every_reason_but_served_has_its_words_and_a_step() -> None:
    """The vocabulary is closed: every reason a restoration answers with,
    bar the one success, has a message and a next step, and nothing else
    has either."""
    unserved = set(door.RESTORATION_REASONS) - {"served"}
    assert set(RUN_UNAVAILABLE_MESSAGES) == unserved
    assert set(RUN_UNAVAILABLE_NEXT_STEPS) == unserved


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"reason": "bogus"}, id="unknown-reason"),
        pytest.param({"reason": "served"}, id="served-without-overlay"),
        pytest.param(
            {"reason": "run_not_found", "overlay": b"x"}, id="overlay-on-a-refusal"
        ),
    ],
)
def test_a_restoration_answer_is_typed_by_construction(
    fields: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        door.RunRestoration(**fields)  # type: ignore[arg-type]


def test_a_root_without_a_store_holds_no_record_and_none_is_made(
    repo: Repo,
) -> None:
    """The rollout names the root's store and nothing was ever published
    there: the run is not found -- no proof it existed -- and the read made
    no store."""
    answer = CodeCloneMCPService().get_run_summary("abcdef12", root=str(repo.root))
    assert answer["reason"] == "run_not_found", answer
    assert "no run store" in str(answer["detail"])
    assert not repo.store.exists()


def test_a_run_never_recorded_is_not_found_and_never_expired(repo: Repo) -> None:
    _analyze(CodeCloneMCPService(), repo)
    answer = CodeCloneMCPService().get_run_summary("ffffffff", root=str(repo.root))
    assert answer["reason"] == "run_not_found"
    assert answer["retryable"] is False
    assert "expired" not in answer
    assert "analyze_repository" in str(answer["next_step"])


def test_a_collected_run_is_expired_with_its_record_as_proof(repo: Repo) -> None:
    """Five analyses of five trees: the window keeps the newest four, and
    the oldest run's record survives it as the proof that it existed."""
    service = CodeCloneMCPService()
    first = _analyze(service, repo)
    first_execution = _record(service, first, repo).execution.execution_event_id
    for functions in (4, 5, 6, 7):
        repo.write(functions)
        _analyze(service, repo)
    assert (
        len(repo.rows("SELECT run_id FROM runs")) == door.PUBLICATION_RETENTION.max_runs
    )

    answer = CodeCloneMCPService().get_run_summary(first, root=str(repo.root))
    assert answer["reason"] == "run_expired"
    assert answer["retryable"] is False
    expired = answer["expired"]
    assert isinstance(expired, dict)
    assert expired["execution_event_id"] == first_execution


def test_a_store_the_rollout_does_not_name_is_not_read(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = _analyze(CodeCloneMCPService(), repo)
    monkeypatch.setenv("CODECLONE_SERVE_FROM", "memory")
    switched = CodeCloneMCPService().get_run_summary(run_id, root=str(repo.root))
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "0")
    off = CodeCloneMCPService().get_run_summary(run_id, root=str(repo.root))
    assert (switched["reason"], off["reason"]) == ("store_disabled", "store_disabled")
    assert "CODECLONE_SERVE_FROM=memory" in str(switched["detail"])


def test_a_store_without_the_registry_is_incompatible_and_names_its_cure(
    repo: Repo,
) -> None:
    run_id = _analyze(CodeCloneMCPService(), repo)
    with closing(sqlite3.connect(repo.store)) as raw:
        raw.execute("DROP TRIGGER run_executions_immutable")
        raw.commit()
    answer = CodeCloneMCPService().get_run_summary(run_id, root=str(repo.root))
    assert answer["reason"] == "incompatible_generation"
    assert answer["retryable"] is False
    assert "codeclone run-store migrate" in str(answer["next_step"])


def test_a_store_that_cannot_be_read_now_is_unavailable_and_retryable(
    repo: Repo,
) -> None:
    run_id = _analyze(CodeCloneMCPService(), repo)
    mode = repo.store.stat().st_mode
    repo.store.chmod(0)
    try:
        answer = CodeCloneMCPService().get_run_summary(run_id, root=str(repo.root))
    finally:
        repo.store.chmod(mode)
    assert answer["reason"] == "store_unavailable", answer
    assert answer["retryable"] is True


def test_a_record_whose_bytes_do_not_prove_is_an_integrity_refusal(
    repo: Repo,
) -> None:
    run_id = _analyze(CodeCloneMCPService(), repo)
    with closing(sqlite3.connect(repo.store)) as raw:
        raw.execute("DROP TRIGGER run_executions_immutable")
        raw.execute("UPDATE run_executions SET overlay = x'00'")
        raw.execute(
            "CREATE TRIGGER run_executions_immutable BEFORE UPDATE ON "
            "run_executions BEGIN SELECT RAISE(ABORT, 'an execution record "
            "is immutable once finalized'); END"
        )
        raw.commit()
    answer = CodeCloneMCPService().get_run_summary(run_id, root=str(repo.root))
    assert answer["reason"] == "integrity"
    assert answer["retryable"] is False


@pytest.mark.parametrize(
    ("damage", "expected"),
    [
        ("contract", "incompatible_generation"),
        ("foreign_root", "integrity"),
        ("other_execution", "integrity"),
        ("other_report", "integrity"),
        ("none", "served"),
    ],
)
def test_a_proven_record_that_does_not_describe_its_run_is_refused_typed(
    repo: Repo, damage: str, expected: str
) -> None:
    """A record that proves against its own digest and still does not
    describe the run it is stored for: written under another contract, or
    carrying the overlay of another checkout, another execution or another
    report.  The newest record of the report answers, so a crafted later
    record is the one the restoration reads; ``none`` is the positive
    control.  Every refusal names a step that changes it."""
    run_id, record, link = _analyzed(repo)
    identity = resident_identity(record)
    crafted = "crafted-execution"
    named = crafted if damage != "other_execution" else "another-execution"
    identity = replace(
        identity, execution=replace(identity.execution, execution_event_id=named)
    )
    if damage == "foreign_root":
        identity = replace(identity, root=repo.root.parent / "elsewhere")
    if damage == "other_report":
        foreign = "f" * 64
        identity = replace(
            identity,
            run_id=foreign,
            execution=replace(
                identity.execution,
                run_snapshot_link=replace(link, report_run_identity=foreign),
            ),
        )
    _write_record(
        repo,
        link,
        identity,
        execution=crafted,
        contract=(
            "other-contract/9" if damage == "contract" else RESIDENT_RUN_CONTRACT
        ),
    )
    answer = CodeCloneMCPService().get_run_summary(run_id, root=str(repo.root))
    reason = answer.get("reason", "served")
    assert reason == expected, answer
    if expected != "served":
        assert "analyze_repository" in str(answer["next_step"]), answer


def test_an_overlay_this_server_cannot_read_is_an_integrity_refusal(
    repo: Repo,
) -> None:
    """A record that proves against its own digest and carries bytes the
    codec cannot read: refused, never guessed at."""
    run_id, record, link = _analyzed(repo)
    door.finalize_execution_record(
        store_path=repo.store,
        link=link,
        publisher_lease="",
        execution_event_id="unreadable-execution",
        root=repo.root,
        record_contract=RESIDENT_RUN_CONTRACT,
        overlay=b"not an overlay",
    )
    answer = CodeCloneMCPService().get_run_summary(run_id, root=str(repo.root))
    assert answer["reason"] == "integrity", answer
    assert "zlib" in str(answer["detail"])
    assert record.execution.execution_event_id != "unreadable-execution"


def test_a_prefix_naming_two_reports_is_a_contract_error(repo: Repo) -> None:
    """Two records whose report identities share a prefix: the prefix is
    refused as ambiguous, never resolved to the first; one more character
    resolves it."""
    _run_id, record, link = _analyzed(repo)
    for index, report in enumerate(("ab" + "0" * 62, "ab" + "1" * 62)):
        identity = resident_identity(record)
        reported = replace(link, report_run_identity=report)
        identity = replace(
            identity,
            run_id=report,
            execution=replace(
                identity.execution,
                execution_event_id=f"prefix-{index}",
                semantic_report_id=report,
                run_snapshot_link=reported,
            ),
        )
        _write_record(repo, reported, identity, execution=f"prefix-{index}")
    fresh = CodeCloneMCPService()
    with pytest.raises(MCPServiceContractError, match="ambiguous"):
        fresh._runs.held_for_root("ab", root=repo.root)
    resolved = fresh._runs.held_for_root("ab1", root=repo.root)
    assert resolved.run_id == "ab" + "1" * 62


# -- an unrecorded finalization -----------------------------------------------


def test_an_unrecorded_finalization_is_said_and_is_not_restorable(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*, link: door.RunSnapshotLink, **_kwargs: object) -> object:
        return replace(
            link,
            state="unrecorded",
            refusal="StoreUnavailableError: database is locked",
        )

    monkeypatch.setattr(restoration, "finalize_execution_record", refuse)
    service = CodeCloneMCPService()
    summary = service.analyze_repository(
        MCPAnalysisRequest(root=str(repo.root), respect_pyproject=True)
    )
    run_id = str(summary["run_id"])
    warnings = summary["warnings"]
    assert isinstance(warnings, list)
    assert RUN_NOT_RESTORABLE_WARNING.format(run_id=run_id[:8]) in warnings
    link = _record(service, run_id, repo).execution.run_snapshot_link
    assert link is not None and link.state == "unrecorded"
    assert repo.rows("SELECT * FROM run_executions") == []
    assert door.restore_run(root=repo.root, run_id=run_id).reason == ("run_not_found")
    answer = CodeCloneMCPService().get_run_summary(run_id, root=str(repo.root))
    assert answer["reason"] == "run_not_found"


# -- payload_evicted: no loop -----------------------------------------------


def _evicted(service: CodeCloneMCPService, run_id: str, repo: Repo) -> None:
    record = _record(service, run_id, repo)
    assert service._runs.drop_payload(resident_identity(record))


def test_payload_evicted_promises_the_run_back_only_while_the_tree_is_unchanged(
    repo: Repo,
) -> None:
    service = CodeCloneMCPService()
    run_id = _analyze(service, repo)
    _evicted(service, run_id, repo)
    unchanged = service.get_production_triage(run_id=run_id, root=str(repo.root))
    repo.write(9)
    drifted = service.get_production_triage(run_id=run_id, root=str(repo.root))

    assert (unchanged["reason"], drifted["reason"]) == (
        "payload_evicted",
        "payload_evicted",
    )
    assert unchanged["retryable"] is False and drifted["retryable"] is False
    assert "registers this same run whole" in str(unchanged["next_step"])
    assert "registers this same run whole" not in str(drifted["next_step"])
    assert "Do not analyse to bring run" in str(drifted["next_step"])


# -- a reading that refused after the drop serves the same run --------------


def test_authority_candidates_of_a_run_without_payload_come_from_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path, authority=True)
    enable_store(monkeypatch, repo)
    service = CodeCloneMCPService()
    run_id = _analyze(service, repo)
    whole = service.check_authority(
        run_id=run_id, root=str(repo.root), section="candidates"
    )
    _evicted(service, run_id, repo)
    dropped = service.check_authority(
        run_id=run_id, root=str(repo.root), section="candidates"
    )
    restored = CodeCloneMCPService().check_authority(
        run_id=run_id, root=str(repo.root), section="candidates"
    )
    for answer in (dropped, restored):
        serving = answer["serving"]
        assert isinstance(serving, dict)
        assert serving["source"] == "run_store", answer
        assert {k: v for k, v in answer.items() if k != "serving"} == {
            k: v for k, v in whole.items() if k != "serving"
        }


def test_candidates_of_a_run_the_store_states_none_for_are_refused_typed(
    repo: Repo,
) -> None:
    """The same reading on a run whose analysis did not rank candidates (the
    semantic-authority lane off): the store states no population, so a
    server that does not hold the payload refuses it typed, never empty."""
    run_id = _analyze(CodeCloneMCPService(), repo)
    answer = CodeCloneMCPService().check_authority(
        run_id=run_id, root=str(repo.root), section="candidates"
    )
    assert answer["reason"] == "payload_evicted", answer
    assert answer["retryable"] is False


def test_candidates_of_a_run_that_is_not_a_full_analysis_are_a_contract_error(
    repo: Repo,
) -> None:
    """A clones-only run without its payload is refused in the record path's
    own words: the check needs a full analysis."""
    service = CodeCloneMCPService()
    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(repo.root), respect_pyproject=True, analysis_mode="clones_only"
        )
    )
    run_id = str(summary["run_id"])
    _evicted(service, run_id, repo)
    with pytest.raises(MCPServiceContractError, match="not compatible with this check"):
        service.check_authority(
            run_id=run_id, root=str(repo.root), section="candidates"
        )


def test_a_run_that_recorded_no_manifest_promises_nothing(repo: Repo) -> None:
    """A record without the run's file manifest cannot tell whether the tree
    moved: the step never promises the same run back."""
    run_id, record, link = _analyzed(repo)
    identity = resident_identity(record)
    identity = replace(
        identity,
        execution=replace(
            identity.execution, execution_event_id="no-manifest", manifest=None
        ),
    )
    _write_record(repo, link, identity, execution="no-manifest")
    answer = CodeCloneMCPService().get_production_triage(
        run_id=run_id, root=str(repo.root)
    )
    assert answer["reason"] == "payload_evicted", answer
    assert "or the run recorded no manifest" in str(answer["next_step"])
    assert "registers this same run whole" not in str(answer["next_step"])


def test_a_second_restoration_of_one_execution_is_the_run_already_held(
    repo: Repo,
) -> None:
    _run_id, record, _link = _analyzed(repo)
    identity = resident_identity(record)
    runs = CodeCloneMCPService()._runs
    first = runs.restore(identity)
    again = runs.restore(replace(identity))
    assert again is first
    assert runs._registration_seq == 1
