# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Two control-plane fields, each carrying two axes, and the split of each.

**Freshness is not observation.** ``after_run_not_new`` answered two different
questions with one refusal: "did any analysis run since the intent went
active?" and "did the pair of runs witness a change?".  Under
``dirty_scope_policy="continue_own_wip"`` the edit precedes ``start``, so both
runs read the same bytes and -- identity being content-addressed -- share a
``run_id``.  The second question is then permanently no, and the refusal's own
``next_step`` ("call analyze_repository now") can never be executed: no
analysis of an unchanged tree will make the two witnesses differ.

**A verdict is not a lifecycle.** The registry's ``status`` column answered
"what did verification say?" and "is this row still live?" at once.  A finish
whose scope check passed and whose verification failed wrote the scope
verdict ``clean`` -- a TERMINAL value the registry filters out -- into the
column that decides findability, so the refusal that tells the agent to
recover destroyed the row it named.

The contract chosen for the first defect is **B** (RULING: pre-WIP state
unavailable -> typed outcome with explicit limitation), not A.  Measured over
430 real dirty ``start`` snapshots in 33 registries on 2026-09-04: only 190
(44.2%) could have their pre-WIP tree reconstructed from git; 240 (55.8%)
carried at least one path with no HEAD pre-image (203 untracked, 29 ``A ``,
17 ``AM``).  Restricted to the Python subset the structural profile actually
analyses, 175 of 356 (49.2%).  A contract that can be honoured for under half
its population is not a contract, so the controller states the limitation
instead of fabricating a BEFORE.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator, Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.surfaces.mcp._session_shared import (
    MCPAnalysisRequest,
    MCPRunRecord,
)

# Ring r4 reads the workspace-intent vocabulary through the MCP surface's own
# re-export modules, never from ``codeclone.workspace_intent`` in r2p: the
# Phase 39S boundary ratchet owns that rule and a test is not exempt from it.
from codeclone.surfaces.mcp._workspace_intent_lifecycle import (
    WorkspaceIntentLifecycle,
    is_terminal_workspace_intent_status,
)
from codeclone.surfaces.mcp._workspace_intent_models import (
    signed_payload_dict_from_record,
)
from codeclone.surfaces.mcp._workspace_intents import (
    find_workspace_intent,
    update_workspace_intent_status,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@e.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@e.com",
}
_PYPROJECT = '[project]\nname = "axes"\nversion = "0.1.0"\n'
_MODULE = (
    "def widen(values):\n"
    "    total = 0  # accumulator\n"
    "    for value in values:\n"
    "        total += value\n"
    "    return total\n"
)
# Comment TEXT only: no new line (start_line would move on every later unit)
# and no docstring (docstring_permille would move).  The edit must be
# invisible to analysis so the two runs share a run_id by design.
_EDITED_MODULE = _MODULE.replace("# accumulator", "# running accumulator")
_SCOPE = {"allowed_files": ["pkg/a.py", "pkg/other.py"]}


def _hotspot_module() -> str:
    """A function whose complexity is a critical finding on any profile.

    Measured rather than assumed: the branch count below produces
    ``design:complexity:route`` at severity ``critical`` and a health delta of
    -19, which is what makes verification -- and only verification -- fail.
    """

    body = "def route(a, b, c, d, e):\n    total = 0\n"
    for index in range(18):
        body += (
            f"    if a == {index} and b > {index}:\n"
            f"        total += {index}\n"
            f"    elif c < {index} or d == {index}:\n"
            f"        total -= {index}\n"
        )
    return body + "    return total\n"


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, env=_GIT_ENV
    )


def _committed_repo(root: Path, *, extra: str = "") -> None:
    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    package.joinpath("__init__.py").write_text("", encoding="utf-8")
    package.joinpath("a.py").write_text(_MODULE + extra, encoding="utf-8")
    # Committed and never touched: the file a claim can reach past, so the
    # start snapshot has something to fail to account for.
    package.joinpath("other.py").write_text(_MODULE, encoding="utf-8")
    root.joinpath("pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    root.joinpath(".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    for args in (("init",), ("add", "-A"), ("commit", "-m", "init")):
        _git(root, *args)


def _analyze(service: CodeCloneMCPService, root: Path) -> tuple[str, MCPRunRecord]:
    payload = service.analyze_repository(MCPAnalysisRequest(root=str(root)))
    run_id = str(payload["run_id"])
    return run_id, service._runs.get_for_root(run_id, root=root)


def _verification(finished: Mapping[str, object]) -> Mapping[str, object]:
    verification = finished["verification"]
    assert isinstance(verification, Mapping)
    return verification


def _declared(
    root: Path,
    *,
    intent: str,
    scope: Mapping[str, object] = _SCOPE,
    dirty_scope_policy: str | None = None,
) -> tuple[CodeCloneMCPService, str, MCPRunRecord]:
    """Commit, analyse, declare -- the setup every case below shares.

    Extracted on CodeClone's own remediation for the block-clone group this
    file introduced on its first run: five copies of the same five statements.
    """

    service = CodeCloneMCPService(history_limit=6)
    _run, record = _analyze(service, root)
    extra = (
        {} if dirty_scope_policy is None else {"dirty_scope_policy": dirty_scope_policy}
    )
    started = service.start_controlled_change(
        root=str(root), scope=dict(scope), intent=intent, **extra
    )
    assert started["status"] == "active", started
    assert started["edit_allowed"] is True, started
    return service, str(started["intent_id"]), record


def _resume_known_wip(
    root: Path,
) -> tuple[CodeCloneMCPService, str, MCPRunRecord]:
    """The ``continue_own_wip`` shape: edit, THEN analyse, THEN declare.

    This is the workflow ``CLAUDE.md`` prescribes for resumed work -- the
    controller's own agents reach it whenever a session is picked back up --
    and it is the one shape in which the intent's before-run already contains
    the change it is supposed to be the before of.
    """

    _committed_repo(root)
    root.joinpath("pkg", "a.py").write_text(_EDITED_MODULE, encoding="utf-8")
    return _declared(
        root,
        intent="resume known work in progress",
        dirty_scope_policy="continue_own_wip",
    )


# ── Defect A: freshness and observation are two questions ────────────────


def test_wip_that_predates_the_declaration_is_typed_not_a_freshness_refusal(
    tmp_path: Path,
) -> None:
    """Boundary one for A: a genuinely NEW execution over the SAME bytes.

    The premise first (probe validity): the after-run must really be a second
    execution -- a different ``execution_event_id`` -- so a refusal naming
    freshness is refuted by the evidence rather than by preference.  Only then
    is the outcome read.
    """

    service, intent_id, record_a = _resume_known_wip(tmp_path)
    run_b, record_b = _analyze(service, tmp_path)
    # 1. Premise: two executions, one semantic report.
    assert (
        record_a.execution.execution_event_id != record_b.execution.execution_event_id
    ), "no second execution: this probe cannot see the effect it claims to test"
    assert record_a.run_id == record_b.run_id
    # 2. Premise: the change really does predate the declaration, so nothing
    #    the agent can analyse will separate the two witnesses.
    assert record_a.execution.workspace_witness == record_b.execution.workspace_witness
    finished = service.finish_controlled_change(
        intent_id=intent_id, changed_files=["pkg/a.py"], after_run_id=run_b
    )
    verification = _verification(finished)
    # 3. The verdict: freshness held, so the refusal must not name freshness.
    assert verification["reason"] != "after_run_not_new", (
        "a second execution after the control event was refused as stale"
    )
    assert verification["reason"] == "change_predates_declaration"
    # 4. Contract B, stated: no BEFORE exists, and the payload says so rather
    #    than presenting a tree compared against itself as structural proof.
    limitations = verification.get("limitations")
    assert isinstance(limitations, list) and limitations
    assert any("predates" in str(item) for item in limitations), limitations
    assert verification.get("structural_comparison_available") is False


def test_the_typed_outcome_for_predating_wip_carries_an_executable_next_step(
    tmp_path: Path,
) -> None:
    """The remedy must be an act the agent can perform.

    ``after_run_not_new`` told the agent to analyse again; under this shape
    that instruction is unexecutable by construction.  Whatever the new
    outcome says, it must not repeat it.
    """

    service, intent_id, _record_a = _resume_known_wip(tmp_path)
    run_b, _record_b = _analyze(service, tmp_path)
    finished = service.finish_controlled_change(
        intent_id=intent_id, changed_files=["pkg/a.py"], after_run_id=run_b
    )
    next_step = str(finished.get("next_step") or "")
    assert next_step, finished
    assert "analyzer_invariant" not in next_step
    # The escape that actually works: bind the intent to a run that predates
    # the edit.  Named, so the agent does not have to rediscover it.
    assert "declare" in next_step, next_step


def test_a_reused_before_execution_is_still_refused_as_not_new(
    tmp_path: Path,
) -> None:
    """Boundary two for A: freshness must still refuse a re-used run.

    The same intent, the same shape, but the after-run offered is the
    intent's OWN before-run.  No second execution happened, so the answer
    stays the freshness refusal whose next_step is executable here.
    """

    service, intent_id, record_a = _resume_known_wip(tmp_path)
    finished = service.finish_controlled_change(
        intent_id=intent_id,
        changed_files=["pkg/a.py"],
        after_run_id=record_a.run_id,
    )
    assert (finished["status"], _verification(finished)["reason"]) == (
        "unverified",
        "after_run_not_new",
    )


def test_a_claim_reaching_past_the_start_snapshot_is_not_predating(
    tmp_path: Path,
) -> None:
    """Boundary two, the case the empty-snapshot tests cannot see.

    A first mutation of the ``all(...)`` comparison survived every other test
    here, because in each of them the start snapshot was EMPTY and an earlier
    guard returned first: the line was never executed by the tests that
    claimed to hold it.  This one keeps the snapshot non-empty and varies only
    the claim, so the comparison itself is what decides.

    The positive control is inside the test, on the same causal path: the same
    intent, finished with only the predating file, must reach the typed
    outcome.  That proves the snapshot is populated and the comparison live
    before the negative half is read.
    """

    service, intent_id, _record_a = _resume_known_wip(tmp_path)
    run_b, _record_b = _analyze(service, tmp_path)
    # Positive control: the predating file alone does reach the new outcome.
    control = service.finish_controlled_change(
        intent_id=intent_id, changed_files=["pkg/a.py"], after_run_id=run_b
    )
    assert _verification(control)["reason"] == "change_predates_declaration", control
    # The measurement: pkg/other.py is committed and clean, so it was NOT in
    # the start snapshot.  One claim the snapshot cannot account for means the
    # patch is not wholly predating, and the freshness refusal -- whose remedy
    # IS executable for that file -- stands.
    finished = service.finish_controlled_change(
        intent_id=intent_id,
        changed_files=["pkg/a.py", "pkg/other.py"],
        after_run_id=run_b,
    )
    assert (finished["status"], _verification(finished)["reason"]) == (
        "unverified",
        "after_run_not_new",
    )


def test_an_untouched_tree_is_still_the_freshness_refusal(
    tmp_path: Path,
) -> None:
    """Boundary two, the other way: nothing was edited at all.

    A clean declaration followed by a second analysis of an unchanged tree is
    NOT the ``continue_own_wip`` shape -- the claimed path was not dirty when
    the intent was declared -- and the executable remedy really is "analyse
    after editing".  The new typed outcome must not swallow this case.
    """

    _committed_repo(tmp_path)
    service, intent_id, _record = _declared(tmp_path, intent="nothing edited yet")
    run_b, _record_b = _analyze(service, tmp_path)
    finished = service.finish_controlled_change(
        intent_id=intent_id, changed_files=["pkg/a.py"], after_run_id=run_b
    )
    assert (finished["status"], _verification(finished)["reason"]) == (
        "unverified",
        "after_run_not_new",
    )


# ── Defect B: a verdict is not a lifecycle ───────────────────────────────


def _violated_by_verification(root: Path) -> tuple[CodeCloneMCPService, str, str]:
    """A finish whose scope check passes and whose verification fails.

    The distinction matters: a SCOPE violation already persisted the
    non-terminal ``violated``, so the row survived.  Only the clean-scope /
    violated-verification pair wrote a terminal value, and that is the pair
    reproduced here -- a structural regression entirely inside the declared
    scope, so the scope check has nothing to complain about.
    """

    _committed_repo(root)
    service, intent_id, _record = _declared(
        root, intent="add a module", scope={"allowed_files": ["pkg/b.py"]}
    )
    root.joinpath("pkg", "b.py").write_text(_hotspot_module(), encoding="utf-8")
    run_b, _record_b = _analyze(service, root)
    return service, intent_id, run_b


@pytest.fixture(params=["file", "sqlite"])
def registry_backend(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """Run the lifecycle tests against BOTH registry backends.

    Measured 2026-09-04: the default backend is ``file``, whose ``remove``
    unlinks the row instead of writing a status, so a mutation of the sqlite
    store's terminal close survived every end-to-end test here.  The aggregate
    was green because a sibling mechanism did the work; probing each store
    alone is what exposes it.
    """

    from codeclone.surfaces.mcp._workspace_intent_store import (
        clear_workspace_intent_store_cache,
    )

    monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_BACKEND", request.param)
    clear_workspace_intent_store_cache()
    yield str(request.param)
    clear_workspace_intent_store_cache()


def test_a_violated_finish_leaves_its_row_findable(
    tmp_path: Path, registry_backend: str
) -> None:
    """Boundary one for B: the refusal that says "recover" keeps the row.

    Probe validity first: the scope check must really have passed and the
    verification must really have failed, or this test would be measuring the
    scope-violation path, which never had the defect.  The backend is a
    parameter, not an assumption: both stores answer findability.
    """

    service, intent_id, run_b = _violated_by_verification(tmp_path)
    finished = service.finish_controlled_change(
        intent_id=intent_id, changed_files=["pkg/b.py"], after_run_id=run_b
    )
    scope_check = finished["scope_check"]
    assert isinstance(scope_check, Mapping)
    # 1. Premise: clean scope, failed verification -- the exact pair.
    assert scope_check["status"] == "clean", scope_check
    assert finished["status"] == "violated", finished
    assert finished["intent_cleared"] is False
    # 2. The refusal names recovery, so the row it names must still exist.
    record = find_workspace_intent(root=tmp_path.resolve(), intent_id=intent_id)
    assert record is not None, (
        "the violated finish closed the registry row it told the agent to recover"
    )
    assert not is_terminal_workspace_intent_status(record.status)
    assert record.status == "needs_recovery"


def test_an_accepted_finish_still_closes_its_row_terminally(
    tmp_path: Path, registry_backend: str
) -> None:
    """Boundary two for B: keeping violated rows must not keep accepted ones.

    An intent that verified and cleared is finished business; if the fix left
    it findable the registry would fill with rows no agent will ever return
    to, and the next ``start`` would see phantom concurrency.

    Both backends, because they close a row by different mechanisms: the file
    store unlinks it, the sqlite store writes the terminal token.  Only the
    second can carry a wrong token, and only this parameter reaches it.
    """

    _committed_repo(tmp_path)
    service, intent_id, _record = _declared(tmp_path, intent="edit one comment")
    tmp_path.joinpath("pkg", "a.py").write_text(_EDITED_MODULE, encoding="utf-8")
    run_b, _record_b = _analyze(service, tmp_path)
    finished = service.finish_controlled_change(
        intent_id=intent_id, changed_files=["pkg/a.py"], after_run_id=run_b
    )
    assert finished["status"] in {"accepted", "accepted_with_external_changes"}, (
        finished
    )
    assert finished["intent_cleared"] is True
    assert find_workspace_intent(root=tmp_path.resolve(), intent_id=intent_id) is None


# ── Defect B, coverage: every writer, not one call site ──────────────────


def _status_assignment_sites() -> dict[str, str]:
    """Every ``status=`` keyword in ``codeclone/`` that builds or replaces a
    record, keyed by ``module::function`` and valued by the source of the
    expression assigned.

    Found by AST over the WHOLE package rather than by grep over a module:
    the defect being closed is precisely that a value reached a field from a
    site nobody was looking at, and a search keyed on a module name would
    carry the same blindness.  The classification below then says, for every
    site found, which of the two axes it writes -- so a site added later
    cannot be silently absorbed into either.
    """

    import ast
    from collections import defaultdict

    package = Path(__file__).resolve().parent.parent / "codeclone"
    sites: defaultdict[str, set[str]] = defaultdict(set)
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        enclosing: dict[ast.AST, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for child in ast.walk(node):
                    enclosing.setdefault(child, node.name)
        relative = path.relative_to(package.parent).as_posix()
        for node in ast.walk(tree):
            keywords = (
                node.keywords
                if isinstance(node, ast.Call)
                and ast.unparse(node.func) in {"replace", "WorkspaceIntentRecord"}
                else ()
            )
            for keyword in (kw for kw in keywords if kw.arg == "status"):
                key = f"{relative}::{enclosing.get(node, '<module>')}"
                sites[key].add(ast.unparse(keyword.value))
    return {key: " | ".join(sorted(values)) for key, values in sites.items()}


_MCP = "codeclone/surfaces/mcp"

# The reconciliation, as a classification rather than a count.  Fourteen
# ``status=`` sites exist in the package; every one is named here with the
# axis it writes and the value it writes.  Six reach the PERSISTED registry
# column and every one of those now carries a lifecycle token; five write the
# in-memory ``IntentRecord``'s verification verdict, which the registry has no
# column for; three belong to an unrelated analytics type.
#
# Two further persisted writers reach the column without a ``status=``
# keyword and so cannot appear here: ``update_workspace_intent_status`` is
# called by four sites in the intent session with a status STRING, and the
# file store's ``remove`` unlinks the row rather than writing one.  Both are
# covered by the write door below, which is the point of putting the guard
# there instead of at any call site.
_STATUS_SITES: dict[str, tuple[str, str]] = {
    # --- persisted registry lifecycle (6) ---
    f"{_MCP}/_session_intent_mixin.py::_workspace_record_from_intent": (
        "registry_lifecycle",
        "lifecycle_for_verification_outcome(intent.status.value).value",
    ),
    f"{_MCP}/_session_intent_mixin.py::_rewrite_recovered_workspace_record": (
        "registry_lifecycle",
        "WorkspaceIntentLifecycle.ACTIVE.value",
    ),
    f"{_MCP}/_workspace_intents.py::_updated_record": (
        "registry_lifecycle",
        "new_status",
    ),
    f"{_MCP}/_workspace_intent_store.py::remove": (
        "registry_lifecycle",
        "WorkspaceIntentLifecycle.CLOSED.value",
    ),
    f"{_MCP}/_workspace_intent_store.py::_close_sqlite_store": (
        "registry_lifecycle",
        "gc_status_for_reason(reason)",
    ),
    "codeclone/workspace_intent/models.py::record_from_document": (
        "registry_lifecycle",
        "lifecycle_for_status(document.status).value",
    ),
    # --- in-memory verification verdict (5) ---
    f"{_MCP}/_session_intent_mixin.py::_check_change_intent": (
        "verification_outcome",
        "IntentStatus.EXPIRED | check_result.status",
    ),
    f"{_MCP}/_session_intent_mixin.py::_downgrade_to_queued": (
        "verification_outcome",
        "IntentStatus.QUEUED",
    ),
    f"{_MCP}/_session_intent_mixin.py::_intent_payload_with_expiry": (
        "verification_outcome",
        "IntentStatus.EXPIRED",
    ),
    f"{_MCP}/_session_intent_mixin.py::_promote_queued_intent": (
        "verification_outcome",
        "IntentStatus.ACTIVE",
    ),
    # --- unrelated type (3, two share one function) ---
    "codeclone/analytics/workflow.py::_execute_single_run": (
        "analytics_run_status",
        "'completed' | 'failed'",
    ),
    "codeclone/analytics/workflow.py::assess_and_persist_profile_batch": (
        "analytics_run_status",
        "status",
    ),
}


def test_the_status_writer_inventory_is_reconciled() -> None:
    """Nothing assigns a status this task has not classified by axis.

    Both halves are asserted: no site is missing from the table (a new writer
    fails here rather than reaching the registry unexamined), and no entry in
    the table is stale (a site that moved or changed its value fails too).
    """

    assert _status_assignment_sites() == {
        key: value for key, (_axis, value) in _STATUS_SITES.items()
    }


def test_every_persisted_status_site_writes_the_lifecycle_vocabulary() -> None:
    """The claim itself: the registry column carries fates, not verdicts."""

    persisted = {
        key: value
        for key, (axis, value) in _STATUS_SITES.items()
        if axis == "registry_lifecycle"
    }
    assert len(persisted) == 6, persisted
    lifecycle_names = {
        f"WorkspaceIntentLifecycle.{m.name}.value" for m in WorkspaceIntentLifecycle
    }
    # Each persisted site either names a lifecycle member outright, or passes
    # a value through a translator whose codomain is the lifecycle enum.
    translators = {
        "lifecycle_for_verification_outcome(intent.status.value).value",
        "lifecycle_for_status(document.status).value",
        "gc_status_for_reason(reason)",
        "new_status",
    }
    for key, value in persisted.items():
        assert value in lifecycle_names | translators, (key, value)


def test_the_registry_write_door_refuses_a_verification_verdict(
    tmp_path: Path,
) -> None:
    """Coverage, structurally: every writer funnels through one serializer.

    ``signed_payload_dict_from_record`` is on the path of every persisted
    write -- both stores build their payload with it -- so refusing a
    verification verdict here refuses it for all four writers at once,
    including any written tomorrow.  Both verdicts are probed: ``violated``
    is the one that caused the incident, ``expanded`` is its silent sibling.
    """

    _committed_repo(tmp_path)
    _service, intent_id, _record = _declared(tmp_path, intent="one comment")
    record = find_workspace_intent(root=tmp_path.resolve(), intent_id=intent_id)
    assert record is not None
    # Positive control: the door passes the lifecycle value it was given.
    assert signed_payload_dict_from_record(record)["status"] == "active"
    for verdict in ("violated", "expanded"):
        with pytest.raises(ValueError):
            signed_payload_dict_from_record(replace(record, status=verdict))


def test_a_verification_verdict_cannot_reach_the_update_door(
    tmp_path: Path,
) -> None:
    """The one door that takes a caller-supplied string says no, loudly.

    ``update_workspace_intent_status`` was the single site that accepted an
    arbitrary status from its caller, and the four callers included the scope
    check.  A silent ``False`` would look like a lost race; the refusal is
    typed instead.

    ``clean`` is deliberately NOT probed here: it is a legitimate lifecycle
    token (the closing one) that merely shares its spelling with a scope
    verdict, so a caller that means "close this row" may still pass it.  The
    two words that carry no fate at all are the ones that must bounce.
    """

    _committed_repo(tmp_path)
    service, intent_id, _record = _declared(tmp_path, intent="one comment")
    # Matched on the door's OWN wording, not merely on ValueError.  The
    # serializer one layer down refuses the same words with a different
    # message, and an unmatched ``pytest.raises`` was measured to pass on that
    # sibling alone while this guard was removed -- a green test proving
    # nothing about the door it names.
    for verdict in ("violated", "expanded"):
        with pytest.raises(
            ValueError, match=r"^workspace intent status is a lifecycle"
        ):
            update_workspace_intent_status(
                root=tmp_path.resolve(),
                pid=service._agent_pid,
                start_epoch=service._agent_start_epoch,
                intent_id=intent_id,
                new_status=verdict,
            )


# ── The two translators: total where they claim to be, loud elsewhere ────


def test_the_lifecycle_tables_are_total_over_the_vocabularies_they_accept() -> None:
    """Neither table may quietly acquire a default.

    Both are decision tables, and a decision table with a fallthrough is a
    decision nobody made.  Totality is asserted over the union vocabulary the
    registry can hold and over the in-memory verification vocabulary, so a new
    word added to either enum fails here rather than picking a fate by
    accident.
    """

    from codeclone.surfaces.mcp._intent import IntentStatus
    from codeclone.surfaces.mcp._workspace_intent_lifecycle import (
        WorkspaceIntentStatus,
        lifecycle_for_status,
        lifecycle_for_verification_outcome,
    )

    for member in WorkspaceIntentStatus:
        assert isinstance(lifecycle_for_status(member.value), WorkspaceIntentLifecycle)
    for verdict in IntentStatus:
        assert isinstance(
            lifecycle_for_verification_outcome(verdict.value),
            WorkspaceIntentLifecycle,
        )
    # The one entry the incident turned on, stated as a fact rather than left
    # to be inferred from the table: a passed scope check does not close a row.
    assert (
        lifecycle_for_verification_outcome("clean") is WorkspaceIntentLifecycle.ACTIVE
    )
    assert (
        lifecycle_for_verification_outcome("violated")
        is WorkspaceIntentLifecycle.NEEDS_RECOVERY
    )
    # ...while the same spelling READ BACK off a row is the closing token,
    # because that is the only thing it has ever meant when persisted.
    assert lifecycle_for_status("clean") is WorkspaceIntentLifecycle.CLOSED


def test_an_unknown_status_word_is_refused_by_both_translators() -> None:
    """A guard no input can reach is theatre; these two are reachable.

    Coverage measured both refusal lines unexecuted, which is how a guard ends
    up structurally dead without anyone noticing.  Each is tripped here by an
    input that really reaches it.
    """

    from codeclone.surfaces.mcp._workspace_intent_lifecycle import (
        lifecycle_for_status,
        lifecycle_for_verification_outcome,
    )

    with pytest.raises(ValueError, match="unknown workspace intent status"):
        lifecycle_for_status("half_finished")
    with pytest.raises(ValueError, match="unknown verification outcome"):
        lifecycle_for_verification_outcome("half_finished")
    # A lifecycle-only word is not a verification outcome and must not be
    # smuggled through the verdict door either.
    with pytest.raises(ValueError, match="unknown verification outcome"):
        lifecycle_for_verification_outcome("orphaned")


# ── Defect C: a closed row is not a recovery candidate ───────────────────
#
# Measured 2026-09-04 and reproduced here on BOTH registry backends: after a
# ``finish`` returned ``intent_cleared: true`` and ``list_workspace`` reported
# ``workspace_intents: []`` with ``orphaned_count: 0``, the same listing still
# carried the intent under ``recovery_available`` telling the operator to
# reclaim it -- while ``recover`` answered ``not_found`` for that very id.
#
# The same two-axes shape as defect B, one layer out.  ``recovery_available``
# is fed by ``list_records_for_hygiene()``, which deliberately returns terminal
# rows (the SQLite registry retains them for 30 days), and each row is then
# judged by ``classify_intent_ownership`` -- which reads expiry, pid ownership,
# lease and agent liveness, and never the lifecycle column.  "Its agent is
# gone" (ownership) was published as "you may reopen it" (lifecycle).
#
# The join is not a new concept: ``workspace_intent.gate`` and
# ``_workspace_hygiene`` already write it by hand at their own call sites.  Two
# consumers forgot, so it is named once here and owned by the ownership module.


def _foreign_lister(record: MCPRunRecord) -> CodeCloneMCPService:
    """A second agent, holding the same run, that will read the registry."""

    service = CodeCloneMCPService(history_limit=6)
    service._agent_pid, service._agent_start_epoch, service._agent_label = (
        22222,
        200,
        "agent-b",
    )
    service._runs.register(record)
    return service


def _orphaned_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    close_it: bool,
) -> tuple[CodeCloneMCPService, str, Path]:
    """One declared intent whose declaring agent is gone, optionally closed."""

    _committed_repo(tmp_path)
    owner, intent_id, record = _declared(tmp_path, intent="owner edits pkg.a")
    if close_it:
        assert update_workspace_intent_status(
            root=tmp_path,
            pid=owner._agent_pid,
            start_epoch=owner._agent_start_epoch,
            intent_id=intent_id,
            new_status=WorkspaceIntentLifecycle.CLOSED.value,
        )
    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_intent_pid.is_agent_pid_alive",
        lambda _pid: False,
    )
    return _foreign_lister(record), intent_id, tmp_path


def _recovery_available(
    service: CodeCloneMCPService, root: Path
) -> tuple[list[Mapping[str, object]], Mapping[str, object]]:
    listing = service.manage_change_intent(action="list_workspace", root=str(root))
    entries = listing["recovery_available"]
    assert isinstance(entries, list)
    return [item for item in entries if isinstance(item, Mapping)], listing


def test_a_closed_intent_is_not_advertised_as_reclaimable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_backend: str,
) -> None:
    """The measured defect: a terminal row offered for reclaim."""

    lister, intent_id, root = _orphaned_intent(tmp_path, monkeypatch, close_it=True)
    stored = find_workspace_intent(
        root=root, intent_id=intent_id, apply_lazy_close=False
    )
    # Population, stated before the verdict: the row really is retained and
    # really is terminal.  A backend that had deleted it would make the
    # assertion below pass for the wrong reason.
    retained = _retained_statuses(root)
    assert retained == [WorkspaceIntentLifecycle.CLOSED.value], retained
    assert is_terminal_workspace_intent_status(retained[0])
    assert stored is None, "a terminal row must not be findable"

    entries, listing = _recovery_available(lister, root)
    assert listing["workspace_intents"] == []
    assert entries == [], (
        f"a terminally closed row was advertised as reclaimable: {entries}"
    )
    assert "recovery_next_step" not in listing


def test_an_orphaned_but_live_intent_is_still_advertised_for_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_backend: str,
) -> None:
    """The opposite boundary: silencing everything is the other error.

    A fix that simply stopped publishing ``recovery_available`` would pass the
    test above and destroy the feature.  This is the test such a mutant reds.
    """

    lister, intent_id, root = _orphaned_intent(tmp_path, monkeypatch, close_it=False)
    entries, listing = _recovery_available(lister, root)
    assert [item["intent_id"] for item in entries] == [intent_id], listing
    assert entries[0]["run_available"] is True
    assert "reclaim" in str(entries[0]["hint"])
    assert listing["recovery_next_step"]


def test_the_recovery_listing_never_advertises_what_recover_calls_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_backend: str,
) -> None:
    """The two doors must agree, whichever row the registry is holding.

    Stated as a relation between the listing and the action rather than as a
    fact about one row: the defect was not "this id is wrong", it was that the
    advertisement and the operation answer to different filters.
    """

    for close_it in (True, False):
        lister, intent_id, root = _orphaned_intent(
            tmp_path / f"case-{close_it}", monkeypatch, close_it=close_it
        )
        entries, _listing = _recovery_available(lister, root)
        for item in entries:
            answer = lister.manage_change_intent(
                action="recover",
                root=str(root),
                run_id=str(item["run_id"]),
                intent_id=str(item["intent_id"]),
            )
            assert answer.get("reason") != "not_found", (
                f"advertised {item['intent_id']!r} that recover cannot find: {answer}"
            )
        assert (intent_id in {str(item["intent_id"]) for item in entries}) is (
            not close_it
        )


def _retained_statuses(root: Path) -> list[str]:
    from codeclone.surfaces.mcp._workspace_intents import (
        list_workspace_intent_records_for_recovery,
    )

    return sorted(
        record.status
        for record in list_workspace_intent_records_for_recovery(root=root)
    )
