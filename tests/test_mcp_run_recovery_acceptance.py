# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Acceptance of run recovery: process A analyses and leaves, process B starts
from nothing and answers from the run store (ruling 2026-10-12, recovery).

Every role is its own operating-system process (``tests._mcp_recovery_
processes``), sharing nothing but a temporary repository, its own run store
and a JSON file of answers.  B runs with every analysis stage a tripwire, and
the tripwire's positive control is its own case: B calling
``analyze_repository`` trips it.

What B owes, read against A:

* every reading with a store road answers byte for byte as A answers once it
  let the payloads go -- the closed list of fields that may differ is
  :data:`_OPERATIONAL` (the age of the answering process);
* a reading that refused ``payload_evicted`` in A after the drop is served in
  B (the authority candidates);
* nothing B answers was held before it asked: it held no execution and no
  served facts, and it restored the run exactly once;
* a tree edited between A and B is seen in ``drifted_files`` -- the manifest
  rides the execution record;
* a run the window collected is ``run_expired`` with its record as proof, a
  run never recorded is ``run_not_found``, a store without the registry is
  ``incompatible_generation``, and an A killed inside its finalization left
  nothing restorable (``run_not_found``), never a success after the fact.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from codeclone.api.run_restoration import PUBLICATION_RETENTION
from tests._mcp_restoration_fixtures import AUTHORITY_LANE_ON, Repo, git

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: The fields of an answer that state the answering PROCESS, not the run:
#: its start, which a second process cannot share by construction.
_OPERATIONAL: tuple[tuple[str, ...], ...] = (
    ("code_provenance", "process_start_epoch"),
)

#: Readings whose store road answers a run held without its payload, so B and
#: "A after the drop" must agree on them; the rest refuse typed in both.
_STORE_READINGS = (
    "get_run_summary",
    "get_blast_radius",
    "compare_runs",
    "evaluate_gates",
    "check_patch_contract",
    "check_authority_candidates",
)


#: A sink the semantic-authority lane ranks, so the run carries a non-empty
#: authority-candidate population for the store to state.
_SINK = """import hashlib


def digest(value: str, extra: str) -> str:
    first = value.lower()
    second = extra.lower()
    payload = second + first
    return hashlib.md5(payload.encode()).hexdigest()
"""


def _repo(tmp_path: Path) -> Repo:
    root = tmp_path / "repo"
    root.joinpath("pkg").mkdir(parents=True)
    root.joinpath("pkg", "__init__.py").write_text("", "utf-8")
    root.joinpath("pkg", "m.py").write_text(
        "".join(f"def f{n}(x: int) -> int:\n    return x * {n}\n\n" for n in range(3)),
        "utf-8",
    )
    root.joinpath("pkg", "sink.py").write_text(_SINK, "utf-8")
    root.joinpath("README.md").write_text("stable\n", "utf-8")
    root.joinpath("pyproject.toml").write_text(AUTHORITY_LANE_ON, "utf-8")
    for args in (("init", "-q"), ("add", "."), ("commit", "-qm", "init")):
        git(root, *args)
    return Repo(root=root, store=root / ".codeclone" / "db" / "runs.sqlite3")


def _env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CODECLONE_", "CI"))
    }
    env.update(
        {
            "HOME": str(home),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "CODECLONE_RUN_STORE_ENABLED": "1",
            "CODECLONE_RUN_STORE_FORCE": "1",
            "CODECLONE_SERVE_FROM": "run_store",
        }
    )
    return env


def _role(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "from tests._mcp_recovery_processes import main; main()",
            *args,
        ],
        cwd=_REPO_ROOT,
        env=_env(tmp_path),
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )


def _loaded(path: Path) -> dict[str, object]:
    loaded = json.loads(path.read_text("utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _a(
    tmp_path: Path, repo: Repo, *, exit_how: str = "clean", extra: int = 0
) -> dict[str, object]:
    out = tmp_path / "a.json"
    done = _role(tmp_path, "a", str(repo.root), str(out), exit_how, str(extra))
    expected = -9 if exit_how in {"kill", "intent"} else 0
    assert done.returncode == expected, done.stderr
    return _loaded(out)


def _b(
    tmp_path: Path, repo: Repo, a: dict[str, object], probe: str = "answer"
) -> dict[str, object]:
    out = tmp_path / f"b-{probe}.json"
    done = _role(
        tmp_path,
        "b",
        str(repo.root),
        str(out),
        str(a["first"]),
        str(a["second"]),
        probe,
    )
    assert done.returncode == 0, done.stderr
    return _loaded(out)


def _operational_free(answer: object) -> object:
    if not isinstance(answer, dict):
        return answer
    trimmed = json.loads(json.dumps(answer))
    for path in _OPERATIONAL:
        node = trimmed
        for key in path[:-1]:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        if isinstance(node, dict):
            node.pop(path[-1], None)
    return trimmed


# -- the tripwire's positive control --------------------------------------------


def test_b_cannot_analyse(tmp_path: Path) -> None:
    """The positive control of every B below: its analysis stages trip."""
    repo = _repo(tmp_path)
    a = _a(tmp_path, repo)
    tripped = _b(tmp_path, repo, a, probe="tripwire")["tripwire"]
    assert isinstance(tripped, dict)
    assert tripped["__error__"] == "AnalysisTripwire"


# -- B answers from the store, as A answers without payloads ----------------------


@pytest.mark.parametrize("exit_how", ["clean", "kill"])
def test_b_answers_every_reading_as_a_does_once_the_payloads_went(
    tmp_path: Path, exit_how: str
) -> None:
    repo = _repo(tmp_path)
    a = _a(tmp_path, repo, exit_how=exit_how)
    b = _b(tmp_path, repo, a)

    # The population tells the runs apart, and the drop is visible in A.
    whole, dropped = a["whole"], a["dropped"]
    assert isinstance(whole, dict) and isinstance(dropped, dict)
    assert a["first"] != a["second"]
    assert whole["get_run_summary"] != dropped["get_run_summary"]

    # Nothing was held before B asked; each run was found again once.
    assert b["held_before"] == {"executions": 0, "served_facts": 0}
    assert b["restorations"] == [a["first"], a["second"]]
    assert b["held_kind"] == "ResidentRun"
    assert b["pid"] != a["pid"]

    answers = b["answers"]
    assert isinstance(answers, dict)
    for reading in sorted(answers):
        assert _operational_free(answers[reading]) == _operational_free(
            dropped[reading]
        ), reading


def test_a_reading_that_refused_after_the_drop_serves_the_run_in_b(
    tmp_path: Path,
) -> None:
    """The authority candidates: before this wave a run without its payload
    was refused ``payload_evicted`` here; B serves it from the store, the
    same rows A's whole run stated."""
    repo = _repo(tmp_path)
    a = _a(tmp_path, repo)
    b = _b(tmp_path, repo, a)
    served = b["answers"]["check_authority_candidates"]  # type: ignore[index]
    whole = a["whole"]["check_authority_candidates"]  # type: ignore[index]
    assert served["serving"]["source"] == "run_store", served
    assert served["items"] == whole["items"]
    assert served["total"] == whole["total"] > 0


def _probe_in_b(
    tmp_path: Path, repo: Repo, probe: str, first: str, second: str
) -> dict[str, object]:
    """One single-call probe of a fresh B, its answer as written."""
    out = tmp_path / f"b-{probe}-{first[:12]}.json"
    done = _role(tmp_path, "b", str(repo.root), str(out), first, second, probe)
    assert done.returncode == 0, done.stderr
    answer = _loaded(out)[probe]
    assert isinstance(answer, dict)
    return answer


def _summary_in_b(tmp_path: Path, repo: Repo, run_id: str) -> dict[str, object]:
    return _probe_in_b(tmp_path, repo, "summary", run_id, run_id)


# -- freshness: the manifest rides the record --------------------------------------


def test_an_edit_between_a_and_b_is_seen_as_drift(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _a(tmp_path, repo)
    second = str(a["second"])
    assert _summary_in_b(tmp_path, repo, second)["drifted_files"] == []
    repo.root.joinpath("pkg", "__init__.py").write_text("VALUE = 1\n", "utf-8")
    assert _summary_in_b(tmp_path, repo, second)["drifted_files"] == ["pkg/__init__.py"]


# -- the typed answers, each on its own cause ---------------------------------------


def test_a_collected_run_is_expired_with_proof_and_an_unknown_one_not_found(
    tmp_path: Path,
) -> None:
    """A analyses one tree more than the window holds after R1: R1 left the
    store, and its record is the proof."""
    repo = _repo(tmp_path)
    a = _a(tmp_path, repo, extra=4)
    expired = _summary_in_b(tmp_path, repo, str(a["first"]))
    never = _summary_in_b(tmp_path, repo, "ffffffff")
    executions = a["executions"]
    assert isinstance(executions, dict)
    assert expired["reason"] == "run_expired", expired
    assert expired["expired"]["execution_event_id"] == executions[a["first"]]  # type: ignore[index]
    assert never["reason"] == "run_not_found", never
    assert "expired" not in never


def test_a_store_without_the_registry_is_incompatible(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _a(tmp_path, repo)
    with closing(sqlite3.connect(repo.store)) as raw:
        raw.execute("DROP TRIGGER run_executions_immutable")
        raw.commit()
    answer = _summary_in_b(tmp_path, repo, str(a["second"]))
    assert answer["reason"] == "incompatible_generation", answer
    assert "codeclone run-store migrate" in str(answer["next_step"])


def test_a_killed_inside_its_finalization_leaves_nothing_restorable(
    tmp_path: Path,
) -> None:
    """Killed after every row of the finalization was written and before the
    commit: the snapshot is published and held by the publisher's lease, and
    no record, no edge exists -- B answers ``run_not_found``, never a run
    that only looks finalized."""
    repo = _repo(tmp_path)
    out = tmp_path / "a.json"
    done = _role(tmp_path, "a", str(repo.root), str(out), "die_finalizing", "0")
    assert done.returncode == 17, done.stderr
    dying = json.loads(out.read_text("utf-8"))["dying_report"]
    assert repo.rows("SELECT count(*) FROM runs WHERE published = 1") == [(1,)]
    assert repo.rows("SELECT count(*) FROM run_executions") == [(0,)]
    assert repo.rows("SELECT count(*) FROM run_report_links") == [(0,)]
    assert repo.rows("SELECT kind FROM run_leases") == [("active",)]
    assert _summary_in_b(tmp_path, repo, dying)["reason"] == "run_not_found"


# -- a second server publishing on the same root -------------------------------------


@pytest.mark.parametrize(("intent", "expected"), [(True, None), (False, "run_expired")])
def test_another_servers_publications_take_a_run_only_no_intent_holds(
    tmp_path: Path, intent: bool, expected: str | None
) -> None:
    """A declares a change intent on R2 and is killed; another server then
    publishes one tree more than the window holds.  The intent's store lease
    holds R2 against that server's sweeps, and B finds it; without the
    intent the window takes it, and B says so.  Either way the sweeps ran:
    the store keeps the window's runs and the one run a lease holds, never
    more -- a sweep that refused would keep R2 too, by doing nothing."""
    repo = _repo(tmp_path)
    a = _a(tmp_path, repo, exit_how="intent" if intent else "kill")
    out = tmp_path / "publish.json"
    published = _role(tmp_path, "publish", str(repo.root), str(out), "5")
    assert published.returncode == 0, published.stderr
    assert repo.rows("SELECT count(*) FROM runs WHERE published = 1") == [
        (PUBLICATION_RETENTION.max_runs + int(intent),)
    ]
    answer = _summary_in_b(tmp_path, repo, str(a["second"]))
    assert answer.get("reason") == expected, answer


def test_every_other_tool_answers_a_run_it_does_not_hold_typed(
    tmp_path: Path,
) -> None:
    """The tools that read a run's payload have no store road: in B each one
    answers -- served, or the typed ``payload_evicted`` of a run held by its
    resident identity, or (the latest, which is this session's alone)
    ``run_not_found`` -- and none raises what it raised before this wave,
    ``MCPRunNotFoundError``."""
    repo = _repo(tmp_path)
    a = _a(tmp_path, repo)
    others = _b(tmp_path, repo, a, probe="others")["others"]
    assert isinstance(others, dict)
    raised = {name: answer for name, answer in others.items() if "__error__" in answer}
    assert raised == {}, raised
    reasons = {
        name: answer.get("reason")
        for name, answer in others.items()
        if answer.get("status") == "unavailable"
    }
    assert reasons["resource_latest_summary"] == "run_not_found"
    assert set(reasons.values()) <= {"payload_evicted", "run_not_found"}, reasons


# -- the named boundary: an intent of a process that is gone ------------------------


def test_an_intent_of_a_process_that_is_gone_is_recovered_after_one_analysis(
    tmp_path: Path,
) -> None:
    """The boundary of this restoration: an intent's before-run is not found
    again by its execution.  Asked to recover the intent A declared on R2, B
    answers typed -- it knows the run, it does not hold its payload -- and,
    R2's files being unchanged, says that one analysis registers this same
    run whole; never a raw error, never the loop back to the same refusal."""
    repo = _repo(tmp_path)
    a = _a(tmp_path, repo, exit_how="intent")
    recovered = _probe_in_b(
        tmp_path, repo, "recover", str(a["intent_id"]), str(a["second"])
    )
    assert recovered["reason"] == "payload_evicted", recovered
    assert recovered["retryable"] is False
    assert "registers this same run whole" in str(recovered["next_step"])
