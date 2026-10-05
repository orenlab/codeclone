# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The change-control cycles behind the patch-contract serving pins
(consumer migration C6).

Every cycle is one in-process MCP session over its own temporary tree with
the run store on and its own store file: analyse, declare an intent, edit,
analyse again, ask ``check_patch_contract``.  The session is kept so a pin
can ask the same question twice -- the serving switch on the store, then on
memory -- and compare the two answers.

The cycles are chosen to REACH every verdict the verifier distinguishes
(Probe Validity Law): accepted, accepted with external changes, violated by
leaving the scope, by touching a forbidden path, by a structural regression,
by a gate failure the patch caused, by a state artifact; unverified for a
missing after-run, an after-run that is not new, missing evidence, an
incomparable pair; and every verification profile.  A verdict nobody reached
is a verdict nobody compared, so the accounting is stated before anything is
counted.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from codeclone.api.run_store_serving import ServedPatchRun, read_run_store_patch_run
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPRunRecord
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.utils.coerce import as_mapping, as_sequence
from tests import conftest as corpora
from tests._run_summary_serving import (
    _bumped,
    _dropped,
    _edited,
    _quarter_covered_report,
    serving_environment,
)

#: The graded function of the evaluation carrier with three branches fewer:
#: a structural improvement inside the declared file.
_GRADED_SIMPLER = (
    "def graded(value: int) -> str:\n    if value < 0:\n        return 'v0'\n"
    + "".join(f"    elif value < {i}:\n        return 'v{i}'\n" for i in range(1, 10))
    + "    return 'vmax'\n"
)
#: The graded function with five branches more: worse complexity, no new
#: finding family member beyond the one the carrier already has.
_GRADED_HARDER = (
    "def graded(value: int) -> str:\n    if value < 0:\n        return 'v0'\n"
    + "".join(f"    elif value < {i}:\n        return 'v{i}'\n" for i in range(1, 18))
    + "    return 'vmax'\n"
)
#: A function body that is a clone unit, written twice: a new function clone
#: group wherever both copies land (measured: the default unit floor reports
#: it; a body of augmented assignments of the same length it does not).
_TWIN_BODY = (
    "    total = 0\n    largest = 0\n    smallest = 999\n    count = 0\n"
    "    zeros = 0\n    for item in items:\n        total = total + item\n"
    "        count = count + 1\n        if item == 0:\n            zeros = zeros + 1\n"
    "        if item > largest:\n            largest = item\n"
    "        if item < smallest:\n            smallest = item\n"
    '    return {"total": total, "zeros": zeros, "smallest": smallest, '
    '"count": count}\n'
)


def _twin(name: str) -> str:
    return f"def {name}(items: list[int]) -> dict[str, int]:\n{_TWIN_BODY}"


@dataclass
class PatchCycle:
    """One change-control cycle: the session, its tree, its store, its runs."""

    name: str
    root: Path
    store_path: Path
    service: CodeCloneMCPService
    before: MCPRunRecord
    after: MCPRunRecord | None = None
    intent_id: str | None = None
    #: The analysis options every analysis of this cycle runs with.
    options: dict[str, object] = field(default_factory=dict)
    #: The questions asked of this cycle: label -> check_patch_contract kwargs.
    questions: dict[str, dict[str, object]] = field(default_factory=dict)

    def ask(self, label: str, *, serve_from: str | None) -> dict[str, object]:
        """``check_patch_contract`` for one question under one switch."""
        with serving_environment(self.store_path, serve_from=serve_from):
            try:
                return self.service.check_patch_contract(**self.questions[label])
            except Exception as refusal:  # a refusal is an answer, compared too
                return {"__refused__": type(refusal).__name__, "detail": str(refusal)}


def _analyze(
    service: CodeCloneMCPService, root: Path, **options: object
) -> MCPRunRecord:
    service.analyze_repository(
        MCPAnalysisRequest(root=str(root), analysis_mode="full", **options)  # type: ignore[arg-type]
    )
    return service._runs.records()[-1]


class PatchCycles:
    """Every cycle, built on first use and kept for the session."""

    def __init__(self, base: Path) -> None:
        self._base = base
        self._baseline: Path | None = None
        self._built: dict[str, PatchCycle] = {}

    def __getitem__(self, name: str) -> PatchCycle:
        if name not in self._built:
            self._built[name] = CYCLE_BUILDERS[name](self, name)
        return self._built[name]

    # -- trees ---------------------------------------------------------------

    def _stage_a_baseline(self) -> Path:
        if self._baseline is None:
            holder = self._base / "_baseline"
            holder.mkdir()
            self._baseline = corpora._comparison_baseline(holder)
        return self._baseline

    def tree(self, name: str, *, fresh_baseline: bool = False) -> Path:
        """The served comparison tree with the evaluation carrier; with
        ``fresh_baseline`` its baseline is rewritten from the tree itself,
        so the before-run starts with every gate passing."""
        holder = self._base / f"_{name}"
        holder.mkdir()
        root = corpora._served_comparison_tree(
            holder, "trusted", self._stage_a_baseline()
        )
        corpora._write_tree(root, corpora.EVALUATION_CARRIER)
        (root / "README.md").write_text("# corpus\n", "utf-8")
        (root / "data").mkdir()
        (root / "data" / "settings.json").write_text('{"a": 1}\n', "utf-8")
        if fresh_baseline:
            corpora._run_codeclone_cli(
                [
                    str(root),
                    "--no-progress",
                    "--api-surface",
                    "--baseline",
                    str(root / "codeclone.baseline.json"),
                    "--update-baseline",
                ],
                {},
            )
        return root

    def session(
        self, name: str, root: Path, *, coverage: bool = True, **options: object
    ) -> PatchCycle:
        """One session over ``root``; with ``coverage`` every analysis of it
        joins a Cobertura report, so the strict profile's coverage gate has
        an input (without one it refuses, which one cycle keeps)."""
        store_path = self._base / f"{name}.sqlite3"
        service = CodeCloneMCPService(history_limit=4)
        if coverage:
            (root / "coverage.xml").write_text(_quarter_covered_report(root), "utf-8")
            options = {"coverage_xml": "coverage.xml", **options}
        options = {"api_surface": True, **options}
        with serving_environment(store_path, serve_from=None):
            before = _analyze(service, root, **options)
        return PatchCycle(
            name=name,
            root=root,
            store_path=store_path,
            service=service,
            before=before,
            options=dict(options),
        )

    def declare(
        self, cycle: PatchCycle, scope: Mapping[str, object], *, strictness: str = "ci"
    ) -> None:
        with serving_environment(cycle.store_path, serve_from=None):
            started = cycle.service.start_controlled_change(
                root=str(cycle.root),
                scope=dict(scope),
                intent=f"battery cycle {cycle.name}",
                strictness=strictness,
            )
        assert started.get("edit_allowed") is True, started
        cycle.intent_id = str(started["intent_id"])

    def reanalyze(self, cycle: PatchCycle, **options: object) -> None:
        with serving_environment(cycle.store_path, serve_from=None):
            cycle.after = _analyze(
                cycle.service, cycle.root, **{**cycle.options, **options}
            )


# -- the cycles ----------------------------------------------------------------

_SCOPE_GRADED = {"allowed_files": ["pkg/eval_graded.py"]}


def _verify(cycle: PatchCycle, label: str, **params: object) -> None:
    question: dict[str, object] = {"mode": "verify", "root": str(cycle.root)}
    question.update(params)
    cycle.questions[label] = question


def _structural_questions(
    cycle: PatchCycle, label: str, changed: list[str], *, intent: bool = True
) -> None:
    """The full structural verify under every strictness profile."""
    assert cycle.after is not None
    for strictness in ("ci", "strict", "relaxed"):
        params: dict[str, object] = {
            "after_run_id": cycle.after.run_id,
            "changed_files": changed,
            "strictness": strictness,
        }
        if intent:
            params["intent_id"] = cycle.intent_id
        else:
            params["before_run_id"] = cycle.before.run_id
        _verify(cycle, f"{label}:{strictness}", **params)


def _budget_questions(cycle: PatchCycle) -> None:
    for strictness in ("ci", "strict", "relaxed"):
        cycle.questions[f"budget:{strictness}"] = {
            "mode": "budget",
            "root": str(cycle.root),
            "run_id": cycle.before.run_id,
            "intent_id": cycle.intent_id,
            "strictness": strictness,
        }


def _improved(self: PatchCycles, name: str) -> PatchCycle:
    """In scope, three branches fewer: accepted.  No coverage report, so
    the strict profile's coverage gate refuses here (an answer too)."""
    cycle = self.session(name, self.tree(name), coverage=False)
    self.declare(cycle, _SCOPE_GRADED)
    _budget_questions(cycle)
    corpora._write_tree(cycle.root, {"pkg/eval_graded.py": _GRADED_SIMPLER})
    self.reanalyze(cycle)
    after = cycle.after
    assert after is not None
    _structural_questions(cycle, "structural", ["pkg/eval_graded.py"])
    _structural_questions(cycle, "no_intent", ["pkg/eval_graded.py"], intent=False)
    # Fast-path and refusal questions on the same intent.
    _verify(cycle, "no_after_run", intent_id=cycle.intent_id)
    _verify(
        cycle,
        "python_without_after",
        intent_id=cycle.intent_id,
        changed_files=["pkg/eval_graded.py"],
    )
    _verify(
        cycle,
        "after_not_new",
        intent_id=cycle.intent_id,
        after_run_id=cycle.before.run_id,
        changed_files=["pkg/eval_graded.py"],
    )
    _verify(
        cycle,
        "missing_after_id",
        intent_id=cycle.intent_id,
        after_run_id="0" * 12,
        changed_files=["pkg/eval_graded.py"],
    )
    _verify(
        cycle,
        "no_before_run",
        before_run_id="f" * 12,
        after_run_id=after.run_id,
        changed_files=["pkg/eval_graded.py"],
    )
    _verify(cycle, "no_runs_at_all")
    _verify(
        cycle,
        "documentation_only",
        intent_id=cycle.intent_id,
        changed_files=["README.md"],
    )
    _verify(
        cycle,
        "documentation_only_with_after",
        intent_id=cycle.intent_id,
        after_run_id=after.run_id,
        changed_files=["README.md"],
    )
    _verify(
        cycle,
        "non_python",
        intent_id=cycle.intent_id,
        changed_files=["data/settings.json"],
    )
    _verify(
        cycle,
        "governance_without_after",
        intent_id=cycle.intent_id,
        changed_files=["pyproject.toml"],
    )
    _verify(
        cycle,
        "governance_with_after",
        intent_id=cycle.intent_id,
        after_run_id=after.run_id,
        changed_files=["pyproject.toml"],
    )
    _verify(
        cycle,
        "state_artifact",
        intent_id=cycle.intent_id,
        changed_files=["codeclone.baseline.json"],
    )
    _verify(
        cycle,
        "state_artifact_with_after",
        intent_id=cycle.intent_id,
        after_run_id=after.run_id,
        changed_files=["pkg/eval_graded.py", ".codeclone/report.json"],
    )
    return cycle


def _external(self: PatchCycles, name: str) -> PatchCycle:
    """In scope improved, a new clone pair outside the scope that the patch
    does not claim: accepted with external changes."""
    cycle = self.session(name, self.tree(name))
    self.declare(cycle, _SCOPE_GRADED)
    corpora._write_tree(
        cycle.root,
        {
            "pkg/eval_graded.py": _GRADED_SIMPLER,
            "pkg/ext_twin_a.py": _twin("ext_twin_a"),
            "pkg/ext_twin_b.py": _twin("ext_twin_b"),
        },
    )
    self.reanalyze(cycle)
    _structural_questions(cycle, "structural", ["pkg/eval_graded.py"])
    return cycle


def _left_scope(self: PatchCycles, name: str) -> PatchCycle:
    """A second file the scope does not declare: violated by scope."""
    cycle = self.session(name, self.tree(name))
    self.declare(cycle, _SCOPE_GRADED)
    corpora._write_tree(
        cycle.root,
        {
            "pkg/eval_graded.py": _GRADED_SIMPLER,
            "pkg/eval_route.py": corpora.EVALUATION_CARRIER["pkg/eval_route.py"]
            + "\n\ndef routed() -> int:\n    return 1\n",
        },
    )
    self.reanalyze(cycle)
    changed = ["pkg/eval_graded.py", "pkg/eval_route.py"]
    _structural_questions(cycle, "structural", changed)
    _verify(cycle, "fast_path_scope", intent_id=cycle.intent_id, changed_files=changed)
    return cycle


def _forbidden(self: PatchCycles, name: str) -> PatchCycle:
    """A declared forbidden path touched: violated."""
    cycle = self.session(name, self.tree(name))
    self.declare(
        cycle,
        {
            "allowed_files": ["pkg/eval_graded.py", "pkg/eval_split.py"],
            "forbidden": ["pkg/eval_split.py"],
        },
    )
    corpora._write_tree(
        cycle.root,
        {
            "pkg/eval_graded.py": _GRADED_SIMPLER,
            "pkg/eval_split.py": corpora.EVALUATION_CARRIER["pkg/eval_split.py"]
            + "    def m9(self) -> int:\n        return 9\n",
        },
    )
    self.reanalyze(cycle)
    _structural_questions(
        cycle, "structural", ["pkg/eval_graded.py", "pkg/eval_split.py"]
    )
    return cycle


def _regressed(self: PatchCycles, name: str) -> PatchCycle:
    """A new clone pair inside the scope and a harder function: violated by
    structural regression, worsened symbols in scope."""
    cycle = self.session(name, self.tree(name))
    self.declare(cycle, _SCOPE_GRADED)
    corpora._write_tree(
        cycle.root,
        {
            "pkg/eval_graded.py": _GRADED_HARDER
            + "\n\n"
            + _twin("in_scope_twin_a")
            + "\n\n"
            + _twin("in_scope_twin_b"),
        },
    )
    self.reanalyze(cycle)
    _structural_questions(cycle, "structural", ["pkg/eval_graded.py"])
    return cycle


def _gate_caused(self: PatchCycles, name: str) -> PatchCycle:
    """The baseline is the before-tree, so every gate passes before; the
    patch adds a clone pair in scope: the gate fails because of the patch."""
    cycle = self.session(name, self.tree(name, fresh_baseline=True))
    self.declare(cycle, _SCOPE_GRADED)
    _budget_questions(cycle)
    corpora._write_tree(
        cycle.root,
        {
            "pkg/eval_graded.py": corpora.EVALUATION_CARRIER["pkg/eval_graded.py"]
            + "\n\n"
            + _twin("gate_twin_a")
            + "\n\n"
            + _twin("gate_twin_b"),
        },
    )
    self.reanalyze(cycle)
    _structural_questions(cycle, "structural", ["pkg/eval_graded.py"])
    _structural_questions(cycle, "no_intent", ["pkg/eval_graded.py"], intent=False)
    return cycle


#: The graded function past the request's complexity threshold below.
_GRADED_PAST_THRESHOLD = (
    "def graded(value: int) -> str:\n    if value < 0:\n        return 'v0'\n"
    + "".join(f"    elif value < {i}:\n        return 'v{i}'\n" for i in range(1, 31))
    + "    return 'vmax'\n"
)


def _harder_only(self: PatchCycles, name: str) -> PatchCycle:
    """Fresh baseline and a complexity threshold above every function of the
    tree; the patch makes one function cross it: the gate fails because of a
    metric the patch worsened in scope."""
    cycle = self.session(
        name, self.tree(name, fresh_baseline=True), complexity_threshold=30
    )
    self.declare(cycle, _SCOPE_GRADED)
    _budget_questions(cycle)
    corpora._write_tree(cycle.root, {"pkg/eval_graded.py": _GRADED_PAST_THRESHOLD})
    self.reanalyze(cycle)
    _structural_questions(cycle, "structural", ["pkg/eval_graded.py"])
    return cycle


def _incomparable(self: PatchCycles, name: str) -> PatchCycle:
    """The after-run analysed under other settings: unverified."""
    cycle = self.session(name, self.tree(name))
    self.declare(cycle, _SCOPE_GRADED)
    corpora._write_tree(cycle.root, {"pkg/eval_graded.py": _GRADED_SIMPLER})
    self.reanalyze(cycle, min_loc=3, min_stmt=2)
    _structural_questions(cycle, "structural", ["pkg/eval_graded.py"])
    return cycle


def _invariant(self: PatchCycles, name: str) -> PatchCycle:
    """A comment-only edit in scope: the analysis facts do not move."""
    cycle = self.session(name, self.tree(name))
    self.declare(cycle, _SCOPE_GRADED)
    corpora._write_tree(
        cycle.root,
        {
            "pkg/eval_graded.py": corpora.EVALUATION_CARRIER["pkg/eval_graded.py"]
            + "# a trailing comment\n"
        },
    )
    self.reanalyze(cycle)
    _structural_questions(cycle, "structural", ["pkg/eval_graded.py"])
    return cycle


def _queued(self: PatchCycles, name: str) -> PatchCycle:
    """The intent is queued: unverified, not active."""
    from codeclone.surfaces.mcp._intent import IntentStatus

    cycle = self.session(name, self.tree(name))
    self.declare(cycle, _SCOPE_GRADED)
    assert cycle.intent_id is not None
    intents = cycle.service._active_intents
    intents[cycle.intent_id] = dataclasses.replace(
        intents[cycle.intent_id], status=IntentStatus.QUEUED
    )
    _verify(
        cycle, "queued", intent_id=cycle.intent_id, changed_files=["pkg/eval_graded.py"]
    )
    _budget_questions(cycle)
    return cycle


def _expired(self: PatchCycles, name: str) -> PatchCycle:
    """The intent was declared against another report: expired."""
    cycle = self.session(name, self.tree(name))
    self.declare(cycle, _SCOPE_GRADED)
    corpora._write_tree(cycle.root, {"pkg/eval_graded.py": _GRADED_SIMPLER})
    self.reanalyze(cycle)
    assert cycle.intent_id is not None
    intents = cycle.service._active_intents
    intents[cycle.intent_id] = dataclasses.replace(
        intents[cycle.intent_id], report_digest="0" * 64
    )
    _structural_questions(cycle, "structural", ["pkg/eval_graded.py"])
    return cycle


def _git(root: Path, *args: str) -> None:
    import subprocess

    subprocess.run(
        [
            "git",
            "-c",
            "user.name=battery",
            "-c",
            "user.email=battery@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _predates(self: PatchCycles, name: str) -> PatchCycle:
    """A git tree whose declared file was already dirty at declaration and
    whose analysis facts do not move: no BEFORE exists (contract B)."""
    root = self.tree(name)
    # The service writes under ``.codeclone/`` on every analysis; ignored,
    # so the workspace witness of two analyses of the same bytes is equal.
    (root / ".gitignore").write_text(".codeclone/\n", "utf-8")
    (root / "coverage.xml").write_text(_quarter_covered_report(root), "utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "corpus")
    corpora._write_tree(
        root,
        {
            "pkg/eval_graded.py": corpora.EVALUATION_CARRIER["pkg/eval_graded.py"]
            + "# a trailing comment\n"
        },
    )
    cycle = self.session(name, root)
    with serving_environment(cycle.store_path, serve_from=None):
        started = cycle.service.start_controlled_change(
            root=str(cycle.root),
            scope=dict(_SCOPE_GRADED),
            intent=f"battery cycle {name}",
            dirty_scope_policy="continue_own_wip",
        )
    assert started.get("edit_allowed") is True, started
    cycle.intent_id = str(started["intent_id"])
    self.reanalyze(cycle)
    _structural_questions(cycle, "structural", ["pkg/eval_graded.py"])
    return cycle


def _api_lane_off(self: PatchCycles, name: str) -> PatchCycle:
    """The API lane off over a baseline that carries one, under the strict
    budget.  The two sides' gate inputs differ here (the memory's metrics
    diff counts 29 broken API symbols, the store states no API delta), and
    the answers do not: the API gate is lane-gated, so the term never
    reaches a verdict (measured 2026-10-03) -- a population that holds the
    shadow to the ANSWER, not to its inputs."""
    cycle = self.session(name, self.tree(name), api_surface=False)
    self.declare(cycle, _SCOPE_GRADED, strictness="strict")
    _budget_questions(cycle)
    corpora._write_tree(cycle.root, {"pkg/eval_graded.py": _GRADED_SIMPLER})
    self.reanalyze(cycle)
    _structural_questions(cycle, "structural", ["pkg/eval_graded.py"])
    return cycle


def _truncated_api(self: PatchCycles, name: str) -> PatchCycle:
    """One file the parser refuses, the API lane on, the strict budget: the
    memory's metrics diff counts two broken API symbols on a truncated run,
    the store states no API delta (the run summary's declared disagreement,
    desk 2026-09-27), and the strict budget gates API breaks -- the
    disagreement reaches the answer, so memory is served and named."""
    root = self.tree(name)
    corpora._write_unparsable(root)
    cycle = self.session(name, root)
    self.declare(cycle, _SCOPE_GRADED, strictness="strict")
    _budget_questions(cycle)
    corpora._write_tree(cycle.root, {"pkg/eval_graded.py": _GRADED_SIMPLER})
    self.reanalyze(cycle)
    _structural_questions(cycle, "structural", ["pkg/eval_graded.py"])
    return cycle


#: Two modules importing each other inside their functions: a new cycle
#: whose every edge is deferred -- the one cycle kind that counts as new but
#: not as a new IMPORT cycle (measured: the served corpora carry none new).
_LAZY_PAIR: dict[str, str] = {
    "pkg/lazy_p.py": (
        "def lazy_p(value: int) -> int:\n"
        "    from pkg.lazy_q import lazy_q\n\n"
        "    return lazy_q(value - 1) if value > 0 else 0\n"
    ),
    "pkg/lazy_q.py": (
        "def lazy_q(value: int) -> int:\n"
        "    from pkg.lazy_p import lazy_p\n\n"
        "    return lazy_p(value - 1) if value > 0 else 1\n"
    ),
}


def _deferred_cycle(self: PatchCycles, name: str) -> PatchCycle:
    """Fresh baseline; the patch adds a cycle of deferred imports in scope:
    a new cycle that is not a new import cycle."""
    cycle = self.session(name, self.tree(name, fresh_baseline=True))
    self.declare(cycle, {"allowed_files": sorted(_LAZY_PAIR)})
    corpora._write_tree(cycle.root, _LAZY_PAIR)
    self.reanalyze(cycle)
    _structural_questions(cycle, "structural", sorted(_LAZY_PAIR))
    return cycle


def _profiles(self: PatchCycles, name: str) -> PatchCycle:
    """Every verification profile under a scope that declares its file."""
    cycle = self.session(name, self.tree(name))
    self.declare(
        cycle,
        {
            "allowed_files": [
                "pkg/eval_graded.py",
                "README.md",
                "data/settings.json",
                "pyproject.toml",
            ]
        },
    )
    corpora._write_tree(
        cycle.root,
        {
            "pkg/eval_graded.py": _GRADED_SIMPLER,
            "README.md": "# corpus, edited\n",
            "data/settings.json": '{"a": 2}\n',
        },
    )
    self.reanalyze(cycle)
    after = cycle.after
    assert after is not None
    for label, changed in (
        ("documentation_only", ["README.md"]),
        ("non_python", ["data/settings.json"]),
        ("governance", ["pyproject.toml"]),
        ("python", ["pkg/eval_graded.py"]),
        ("mixed", ["pkg/eval_graded.py", "README.md", "data/settings.json"]),
    ):
        _verify(
            cycle, f"{label}:fast", intent_id=cycle.intent_id, changed_files=changed
        )
        _verify(
            cycle,
            f"{label}:after",
            intent_id=cycle.intent_id,
            after_run_id=after.run_id,
            changed_files=changed,
        )
    _verify(
        cycle,
        "state_artifact:fast",
        intent_id=cycle.intent_id,
        changed_files=["codeclone.baseline.json"],
    )
    _verify(
        cycle,
        "state_artifact:after",
        intent_id=cycle.intent_id,
        after_run_id=after.run_id,
        changed_files=[".codeclone/db/cache.sqlite3"],
    )
    _verify(
        cycle, "documentation_only:diff_ref", intent_id=cycle.intent_id, diff_ref="HEAD"
    )
    _budget_questions(cycle)
    return cycle


CYCLE_BUILDERS: dict[str, Callable[[PatchCycles, str], PatchCycle]] = {
    "improved": _improved,
    "external": _external,
    "left_scope": _left_scope,
    "forbidden": _forbidden,
    "regressed": _regressed,
    "gate_caused": _gate_caused,
    "harder_only": _harder_only,
    "incomparable": _incomparable,
    "invariant": _invariant,
    "queued": _queued,
    "profiles": _profiles,
    "expired": _expired,
    "predates": _predates,
    "api_lane_off": _api_lane_off,
    "truncated_api": _truncated_api,
    "deferred_cycle": _deferred_cycle,
}

# -- one store row replaced: the carriers of the answer ----------------------
#
# Each perturbation replaces stored rows of the runs as the store decodes
# them (``tests/_run_summary_serving.store_row_replaced``: the whole read and
# the bounded read meet the same replacement), and names the answer fields
# it must move -- the floor, never "something moved".  The store's answer
# then disagrees with the memory's, so memory is served and the moved fields
# are named in ``serving.detail``.  Every replacement keeps the model's own
# laws (a vocabulary word a run can carry, a severity with its priority):
# a replacement the model refuses tests the refusal, not the carrier.

_Perturb = Callable[[dict[str, list[object]]], None]


def _dropped_every(family: str, match: Callable[[Any], bool]) -> _Perturb:
    """Every row of the family that matches is gone, in every run read."""

    def perturb(collected: dict[str, list[object]]) -> None:
        rows = collected.get(family)
        if rows is not None:
            rows[:] = [row for row in rows if not match(row)]

    return perturb


def _named(qualname: str, dimension: str) -> Callable[[object], bool]:
    return lambda row: (
        getattr(row, "dimension", None) == dimension
        and getattr(getattr(row, "symbol", None), "qualname", None) == qualname
    )


#: Each carrier: (cycle, question, rows replaced, the fields that must move).
PATCH_ROW_PERTURBATIONS: dict[str, tuple[str, str, _Perturb, tuple[str, ...]]] = {
    "health_result.budget": (
        "improved",
        "budget:ci",
        _edited("health_result", _bumped("score")),
        ("current_state.health_score",),
    ),
    "health_result.verify": (
        "improved",
        "structural:ci",
        _edited("health_result", _bumped("score")),
        ("before.health", "after.health"),
    ),
    "risk_observation.max": (
        "improved",
        "budget:ci",
        _edited(
            "risk_observation",
            _bumped("numerator"),
            _named("new_tangle", "cyclomatic_complexity"),
        ),
        ("current_state.complexity_max",),
    ),
    "risk_observation.headroom": (
        "profiles",
        "budget:strict",
        _edited(
            "risk_observation",
            _bumped("numerator"),
            _named("new_tangle", "cyclomatic_complexity"),
        ),
        ("current_state.complexity_max", "headroom.complexity_headroom"),
    ),
    "risk_observation.worsened": (
        "harder_only",
        "structural:ci",
        _edited(
            "risk_observation",
            _bumped("numerator"),
            _named("graded", "cyclomatic_complexity"),
        ),
        ("worsened", "intent_worsened", "gate_preview.reasons"),
    ),
    "coupling_cohesion.cbo": (
        "improved",
        "budget:ci",
        _edited(
            "coupling_cohesion_observation", _bumped("numerator"), _named("Hub", "cbo")
        ),
        ("current_state.coupling_max",),
    ),
    "coupling_cohesion.lcom4": (
        "improved",
        "budget:ci",
        _edited(
            "coupling_cohesion_observation",
            _bumped("numerator"),
            _named("Split", "lcom4"),
        ),
        ("current_state.cohesion_max",),
    ),
    "dependency_cycle": (
        "improved",
        "budget:ci",
        _dropped("dependency_cycle"),
        ("current_state.dependency_cycles",),
    ),
    "clone_group.count": (
        "improved",
        "budget:ci",
        _dropped("clone_group"),
        ("current_state.clone_groups",),
    ),
    "dead_symbol_group.confidence": (
        "improved",
        "budget:ci",
        _edited(
            "dead_symbol_group",
            lambda row: dataclasses.replace(row, confidence="medium"),
            lambda row: row.confidence == "high",
        ),
        ("current_state.dead_code_high_confidence",),
    ),
    "clone_group.verdict": (
        "regressed",
        "structural:ci",
        _dropped_every("clone_group", lambda row: "in_scope_twin_a" in repr(row)),
        (
            "status",
            "structural_delta.regressions",
            "intent_regressions",
            "contract_violations",
            "blocking_violations",
            "claim_validation_recommended",
            "message",
        ),
    ),
    "clone_novelty.gate": (
        "gate_caused",
        "structural:ci",
        _dropped_every("clone_novelty", lambda row: row.novelty == "new"),
        (
            "gate_preview.would_fail",
            "gate_preview.exit_code",
            "gate_preview.reasons",
            "gate_worsened",
            "intent_caused_gate_failure",
            "contract_violations",
            "blocking_violations",
            "message",
        ),
    ),
    "clone_novelty.budget": (
        "improved",
        "budget:ci",
        _dropped_every("clone_novelty", lambda row: row.novelty == "new"),
        ("gate_preview.would_fail", "gate_preview.exit_code", "message"),
    ),
    "finding_evaluation.severity": (
        "gate_caused",
        "structural:ci",
        _dropped_every(
            "finding_evaluation",
            lambda row: row.finding_id.startswith("clone:function"),
        ),
        ("structural_delta.regressions", "intent_regressions"),
    ),
}

#: A stored fact the memory holds and the store does not: the coverage join
#: of a run analysed with a report.  The strict budget gates coverage, the
#: store refuses that gate, the memory answers it -- a disagreement.
PATCH_STORE_REFUSAL: tuple[str, str, _Perturb] = (
    "profiles",
    "budget:strict",
    _dropped("coverage_join"),
)


def stored_patch_run(store_path: Path, record: MCPRunRecord) -> ServedPatchRun:
    """The facts one execution's run lends the patch contract, read through
    the door the surface reads through -- never a reading of the test's own."""
    with serving_environment(store_path, serve_from="run_store"):
        stored, outcome = read_run_store_patch_run(
            root=record.root, link=record.execution.run_snapshot_link
        )
    assert stored is not None, outcome
    return stored


def document_gate_state(record: MCPRunRecord) -> dict[str, object]:
    """The gate's input record as the document reader builds it for one
    execution -- the inputs the memory gate preview is evaluated over."""
    from codeclone.report.gates.evaluator import _gate_state_from_report_document

    state = _gate_state_from_report_document(
        report_document=record.served_report,
        metrics_diff=record.metrics_diff,
        clone_new_count=len(record.new_func) + len(record.new_block),
        clone_total=record.func_clones_count + record.block_clones_count,
    )
    return dataclasses.asdict(state)


def document_metric_items(
    record: MCPRunRecord,
) -> dict[str, dict[tuple[str, str], int]]:
    """The per-symbol metric index the memory side reads off the document,
    for each family the verifier compares."""
    from codeclone.surfaces.mcp._patch_contract_runs import (
        METRIC_VALUE_KEYS,
        record_metric_item_index,
    )

    return {
        family: record_metric_item_index(
            record.served_report, family=family, value_keys=keys
        )
        for family, keys in METRIC_VALUE_KEYS.items()
    }


def document_lane_trust(record: MCPRunRecord) -> dict[str, str]:
    """The lane trust the document's baseline section states, as the gate
    reads it, and the run's enabled lanes."""
    baseline = as_mapping(record.served_report.get("baseline"))
    return {
        str(as_mapping(row)["name"]): str(as_mapping(row)["status"])
        for row in as_sequence(baseline.get("sorted_lane_trust"))
    }


class RecordingAuditWriter:
    """An audit writer that keeps every event it is handed, numbered."""

    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> int:
        self.events.append(event)
        return len(self.events)

    def close(self) -> None:
        return None


#: One set of cycles per pytest session, whichever module asks first.
_SHARED: dict[str, PatchCycles] = {}


def shared_cycles(factory: pytest.TempPathFactory) -> PatchCycles:
    """The session's cycles, under the session's own temporary root."""
    key = str(factory.getbasetemp())
    if key not in _SHARED:
        _SHARED[key] = PatchCycles(factory.mktemp("patch_contract_cycles").resolve())
    return _SHARED[key]


__all__ = [
    "CYCLE_BUILDERS",
    "PATCH_ROW_PERTURBATIONS",
    "PATCH_STORE_REFUSAL",
    "PatchCycle",
    "PatchCycles",
    "RecordingAuditWriter",
    "document_gate_state",
    "document_lane_trust",
    "document_metric_items",
    "shared_cycles",
    "stored_patch_run",
]
