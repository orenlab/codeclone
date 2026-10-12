# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The processes of the recovery acceptance test: A analyses and leaves, B
starts from nothing and answers.

Each role runs in its own operating-system process (``python -c`` with this
module's ``main``); nothing passes between them but the repository, its run
store and a JSON file of answers.  The roles are spelled here, once, so the
acceptance test reads as a protocol and every child runs the same code.

Every store is the temporary root's own, every child's ``HOME`` and cache
directory are temporary, and the run-store rollout is switched on in the
child's environment only -- never a production store.
"""

from __future__ import annotations

import json
import os
import signal
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from codeclone.api.run_restoration import RunRestoration
    from codeclone.canonical.executions import ExecutionRecord, RegisteredExecution
    from codeclone.canonical.store import RunStore
    from codeclone.surfaces.mcp.service import CodeCloneMCPService

#: The tools whose answers B is held to, each a call on one run of one root
#: (``compare_runs`` reads the second run as well).
READINGS: tuple[str, ...] = (
    "get_run_summary",
    "get_production_triage",
    "get_blast_radius",
    "compare_runs",
    "evaluate_gates",
    "check_patch_contract",
    "check_authority_candidates",
)


class AnalysisTripwire(RuntimeError):
    """Raised by every analysis stage of a process that must not analyse."""


def _ask(call: Callable[[], object]) -> object:
    """One answer, an exception recorded as one."""
    try:
        return call()
    except Exception as error:  # the answer is the subject, typed or raw
        return {"__error__": type(error).__name__, "message": str(error)}


def readings(
    service: CodeCloneMCPService, *, root: str, run_id: str, other: str
) -> dict[str, object]:
    from codeclone.surfaces.mcp.session import MCPGateRequest

    svc = service  # the service facade the FastMCP tools call
    calls: dict[str, Callable[[], object]] = {
        "get_run_summary": lambda: svc.get_run_summary(run_id, root=root),
        "get_production_triage": lambda: svc.get_production_triage(
            run_id=run_id, root=root
        ),
        "get_blast_radius": lambda: svc.get_blast_radius(
            files=["pkg/m.py"], run_id=run_id, root=root
        ),
        "compare_runs": lambda: svc.compare_runs(
            before_run_id=run_id, after_run_id=other, root=root
        ),
        "evaluate_gates": lambda: svc.evaluate_gates(
            MCPGateRequest(run_id=run_id, root=root, fail_threshold=0, fail_health=95)
        ),
        "check_patch_contract": lambda: svc.check_patch_contract(
            mode="budget", run_id=run_id, root=root
        ),
        "check_authority_candidates": lambda: svc.check_authority(
            run_id=run_id, root=root, section="candidates"
        ),
    }
    return {name: _ask(calls[name]) for name in READINGS}


def other_readings(
    service: CodeCloneMCPService, *, root: str, run_id: str
) -> dict[str, object]:
    """The tools that read a run's payload and have no store road: each must
    answer the run typed in a process that does not hold it, never raise."""
    svc = service
    calls: dict[str, Callable[[], object]] = {
        "list_findings": lambda: svc.list_findings(run_id=run_id, root=root, limit=5),
        "get_finding": lambda: svc.get_finding(
            finding_id="missing", run_id=run_id, root=root
        ),
        "get_remediation": lambda: svc.get_remediation(
            finding_id="missing", run_id=run_id, root=root
        ),
        "list_hotspots": lambda: svc.list_hotspots(
            kind="highest_spread", run_id=run_id, root=root
        ),
        "get_report_section": lambda: svc.get_report_section(
            run_id=run_id, root=root, section="meta"
        ),
        "check_clones": lambda: svc.check_clones(run_id=run_id, root=root),
        "check_complexity": lambda: svc.check_complexity(run_id=run_id, root=root),
        "check_dead_code": lambda: svc.check_dead_code(run_id=run_id, root=root),
        "get_implementation_context": lambda: svc.get_implementation_context(
            root=root, run_id=run_id, query="f1"
        ),
        "generate_pr_summary": lambda: svc.generate_pr_summary(
            run_id=run_id, root=root, format="json"
        ),
        "list_reviewed_findings": lambda: svc.list_reviewed_findings(
            run_id=run_id, root=root
        ),
        "resource_run_summary": lambda: json.loads(
            svc.read_resource(f"codeclone://runs/{run_id}/summary")
        ),
        "resource_latest_summary": lambda: json.loads(
            svc.read_resource("codeclone://latest/summary")
        ),
    }
    return {name: _ask(calls[name]) for name in sorted(calls)}


def _write(path: str, payload: Mapping[str, object]) -> None:
    Path(path).write_text(json.dumps(payload, sort_keys=True, default=str), "utf-8")


def _module(root: Path, functions: int) -> None:
    root.joinpath("pkg", "m.py").write_text(
        "".join(
            f"def f{n}(x: int) -> int:\n    return x * {n}\n\n"
            for n in range(functions)
        ),
        "utf-8",
    )


def _die_inside_the_finalization(out: str) -> None:
    """Kill this process inside its first finalization, after every row is
    written and before the commit -- naming first, in ``out``, the report
    whose finalization it was."""
    import codeclone.canonical.store as store_module

    real = store_module.finalize_execution

    def killed(store: RunStore) -> None:
        del store
        os._exit(17)

    def named_then_finalized(
        store: RunStore,
        record: ExecutionRecord,
        *,
        expected_scope_digest: str,
        publisher_lease: str | None = None,
    ) -> RegisteredExecution:
        _write(out, {"dying_report": record.report_run_identity})
        store_module._before_finalize_commit = killed
        return real(
            store,
            record,
            expected_scope_digest=expected_scope_digest,
            publisher_lease=publisher_lease,
        )

    store_module.finalize_execution = named_then_finalized


def role_a(root: Path, out: str, exit_how: str, extra: int) -> None:
    """Analyse twice (R1, then R2 of an edited tree), answer every reading
    whole and again without the payloads, analyse ``extra`` more trees, and
    leave the way ``exit_how`` says: ``clean`` (the server's own cleanup),
    ``kill`` (SIGKILL, nothing cleaned), ``intent`` (a change intent declared
    on R2, then SIGKILL) or ``die_finalizing`` (killed inside the first
    finalization, before its commit)."""
    from codeclone.surfaces.mcp._run_residence import resident_identity
    from codeclone.surfaces.mcp.service import CodeCloneMCPService
    from codeclone.surfaces.mcp.session import MCPAnalysisRequest

    if exit_how == "die_finalizing":
        _die_inside_the_finalization(out)
    service = CodeCloneMCPService()
    request = MCPAnalysisRequest(root=str(root), respect_pyproject=True)
    first = str(service.analyze_repository(request)["run_id"])
    _module(root, 5)
    second = str(service.analyze_repository(request)["run_id"])
    executions = {
        run_id: service._runs.get_for_root(
            run_id, root=root
        ).execution.execution_event_id
        for run_id in (first, second)
    }
    whole = readings(service, root=str(root), run_id=first, other=second)
    for run_id in (first, second):
        service._runs.drop_payload(
            resident_identity(service._runs.get_for_root(run_id, root=root))
        )
    dropped = readings(service, root=str(root), run_id=first, other=second)
    for index in range(extra):
        _module(root, 7 + index)
        service.analyze_repository(request)
    intent_id = ""
    if exit_how == "intent":
        # The intent is declared on R2 held whole: the tree is R2's, so the
        # analysis registers that same run again (its payload went above).
        service.analyze_repository(request)
        started = service.start_controlled_change(
            root=str(root), scope={"allowed_files": ["README.md"]}, intent="hold R2"
        )
        assert started["status"] == "active", started
        intent_id = str(started["intent_id"])
    _write(
        out,
        {
            "first": first,
            "second": second,
            "executions": executions,
            "whole": whole,
            "dropped": dropped,
            "intent_id": intent_id,
            "pid": os.getpid(),
        },
    )
    if exit_how in {"kill", "intent"}:
        os.kill(os.getpid(), signal.SIGKILL)
    service.shutdown_cleanup()


def role_publish(root: Path, out: str, count: int) -> None:
    """Another server on the same root: ``count`` analyses of new trees."""
    from codeclone.surfaces.mcp.service import CodeCloneMCPService
    from codeclone.surfaces.mcp.session import MCPAnalysisRequest

    service = CodeCloneMCPService()
    request = MCPAnalysisRequest(root=str(root), respect_pyproject=True)
    published = []
    for index in range(count):
        _module(root, 20 + index)
        published.append(str(service.analyze_repository(request)["run_id"]))
    _write(out, {"published": published})
    service.shutdown_cleanup()


def _trip(*_args: object, **_kwargs: object) -> object:
    raise AnalysisTripwire("this process may not analyse")


def _install_tripwire() -> None:
    import codeclone.surfaces.mcp.session as session_module

    for stage in ("bootstrap", "discover", "process", "analyze", "report"):
        setattr(session_module, stage, _trip)


def _single_probes(
    service: CodeCloneMCPService, *, root: Path, first: str, second: str
) -> dict[str, Callable[[], object]]:
    """The one-call probes of B, by name: ``summary`` (R1's summary),
    ``others`` (the tools without a store road), ``tripwire`` (an analysis,
    which must trip) and ``recover`` (``first`` naming an intent declared by
    a process that is gone, ``second`` its run)."""
    from codeclone.surfaces.mcp.session import MCPAnalysisRequest

    spelled = str(root)
    return {
        "summary": lambda: _ask(lambda: service.get_run_summary(first, root=spelled)),
        "others": lambda: other_readings(service, root=spelled, run_id=first),
        "tripwire": lambda: _ask(
            lambda: service.analyze_repository(
                MCPAnalysisRequest(root=spelled, respect_pyproject=True)
            )
        ),
        "recover": lambda: _ask(
            lambda: service.manage_change_intent(
                action="recover", intent_id=first, root=spelled, run_id=second
            )
        ),
    }


def role_b(root: Path, out: str, first: str, second: str, probe: str) -> None:
    """Start from nothing, with every analysis stage a tripwire, and answer
    every reading of R1 (``probe == "answer"``) -- or one of
    :func:`_single_probes`, written under its own name."""
    _install_tripwire()
    from codeclone.api import run_restoration as door
    from codeclone.api.run_store_serving import _SERVED_FACTS
    from codeclone.surfaces.mcp import _run_restoration as restoration_module
    from codeclone.surfaces.mcp.service import CodeCloneMCPService

    service = CodeCloneMCPService()
    single = _single_probes(service, root=root, first=first, second=second)
    if probe in single:
        _write(out, {probe: single[probe]()})
        return
    restorations: list[str] = []

    def counted(*, root: Path, run_id: str) -> RunRestoration:
        restorations.append(run_id)
        return door.restore_run(root=root, run_id=run_id)

    # The spy sits on the name the registry's miss hook calls.
    restoration_module.restore_run = counted  # type: ignore[attr-defined]
    held_before = {
        "executions": len(service._runs._executions),
        "served_facts": len(_SERVED_FACTS.runs()),
    }
    answers = readings(service, root=str(root), run_id=first, other=second)
    held = service._runs.held_for_root(first, root=root)
    _write(
        out,
        {
            "held_before": held_before,
            "restorations": restorations,
            "held_kind": type(held).__name__,
            "answers": answers,
            "pid": os.getpid(),
        },
    )


def main() -> None:
    role, root, out, *rest = sys.argv[1:]
    if role == "a":
        role_a(Path(root), out, rest[0], int(rest[1]))
    elif role == "publish":
        role_publish(Path(root), out, int(rest[0]))
    else:
        role_b(Path(root), out, rest[0], rest[1], rest[2])


if __name__ == "__main__":
    main()
