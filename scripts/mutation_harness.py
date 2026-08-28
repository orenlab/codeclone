#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Mutation protocol harness: the protocol runs itself, so it cannot be skipped.

A hand-written mutation table is a claim.  This tool turns the claim into a
measurement.  For every mutant it snapshots the whole worktree, proves the home
is green before anything is touched, applies exactly one edit, proves the edit
reached the disk, purges stale bytecode, runs the declared home under every
declared hash seed, counts the tests that were actually collected, restores the
file, and re-proves the worktree path by path.  Only then does it name a
verdict, and only ``kill`` exits zero.

Nine failure modes, each one measured on this repository, are refused by
construction rather than by discipline:

1.  A run that collected nothing looks green.  The verdict reads the junit
    ``tests`` attribute, never the log, and zero collected is ``void``.
2.  Restoring a fixed list of files hides mutants left elsewhere.  Restore is
    proven by re-reading the whole ``git status`` surface, not a list.
3.  A mutation whose site moved never lands.  The target is read back off the
    disk and its digest must have changed.
4.  A survivor in a narrowed home means nothing.  The home is declared, and a
    narrowed home can only ever yield ``survive_narrow``.
5.  A verdict that flips with ``PYTHONHASHSEED`` is not a verdict.  Seeds are
    aggregated by the least favourable outcome.
6.  Two mutations at once mask each other.  One mutant carries one edit, and a
    battery restores and re-proves the tree between mutants.
7.  Stale ``__pycache__`` answers with yesterday's code.  Caches are purged and
    the child runs with bytecode writing disabled.
8.  A timeout or a signal skips ``finally``.  Signals are converted into an
    exception so the restore path is the only way out.
9.  "It is equivalent" buries a survivor.  Equivalence is a justified
    annotation on a survivor and never becomes a verdict of its own.

Usage::

    python scripts/mutation_harness.py --root <abs> --plan plan.json

The plan is JSON on purpose: a shell list of paths in a variable does not word
split under zsh, which is how the void runs of this week were produced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import FrameType
from typing import NoReturn
from xml.etree import ElementTree

PROTOCOL_VERSION = "codeclone.mutation_protocol/1"
DEFAULT_TIMEOUT_SECONDS = 1800.0
DEFAULT_SEEDS = (0,)
MIN_EQUIVALENCE_JUSTIFICATION = 40

_CACHE_SKIP_DIRS = frozenset({".git", ".venv", "node_modules"})
_RENAME_CODES = frozenset({"R", "C"})
_MUTANT_KEYS = frozenset(
    {
        "id",
        "target",
        "find",
        "replace",
        "occurrence",
        "home",
        "seeds",
        "timeout_seconds",
        "equivalence_claim",
    }
)
_REQUIRED_MUTANT_KEYS = frozenset({"id", "target", "find", "replace", "home"})
_HOME_KEYS = frozenset({"declared", "nodes"})
_HOME_KINDS = frozenset({"full", "narrow"})


class Verdict(str, Enum):
    """The closed set of outcomes a mutation run may report."""

    KILL = "kill"
    SURVIVE = "survive"
    SURVIVE_NARROW = "survive_narrow"
    VOID = "void"
    ERROR = "error"


# Only a kill exits zero: a survivor, an empty home and a broken run are all
# states an agent must not be able to report as success.
_EXIT_CODE: Mapping[Verdict, int] = {
    Verdict.KILL: 0,
    Verdict.SURVIVE: 1,
    Verdict.SURVIVE_NARROW: 1,
    Verdict.VOID: 2,
    Verdict.ERROR: 3,
}

# Worst first.  Aggregation always keeps the least favourable outcome, so a
# mutant that survived under any seed can never be reported as killed.
_SEVERITY: tuple[Verdict, ...] = (
    Verdict.ERROR,
    Verdict.VOID,
    Verdict.SURVIVE,
    Verdict.SURVIVE_NARROW,
    Verdict.KILL,
)


# Every outcome carries the one step that follows from it.  Longest matching
# reason prefix wins; the verdict default catches the rest.
_NEXT_STEP_BY_REASON: tuple[tuple[str, str], ...] = (
    (
        "tree_not_restored",
        "Stop. The worktree was not put back: restore every path in "
        "residual_paths by hand and re-run. No measurement on this tree counts.",
    ),
    (
        "home_already_red",
        "The home was red before anything was mutated. Make it green first: a "
        "red home reds for every mutant and kills nothing.",
    ),
    (
        "target_is_git_ignored",
        "git cannot witness an ignored path, so the restore proof would be "
        "vacuous. Point the mutant at a tracked file.",
    ),
    (
        "no_tests_collected",
        "The home collected zero tests. Fix home.nodes until a real, non-empty "
        "selection runs; a run that collected nothing is not evidence.",
    ),
    (
        "no_junit_report",
        "pytest wrote no report, so the collected count does not exist. Check "
        "home.nodes for a path or node id that is not there.",
    ),
    (
        "find_not_found",
        "The site moved. Re-read the target and re-state find.",
    ),
    (
        "ambiguous_find",
        "find matches more than one site. Lengthen it, or name occurrence.",
    ),
    (
        "occurrence_out_of_range",
        "The target holds fewer sites than occurrence names. Re-read it.",
    ),
    (
        "mutation_not_applied",
        "The file on disk did not change: replace produced the original bytes.",
    ),
    (
        "equivalence_claim_without_survivor",
        "Equivalence annotates a survivor. Drop equivalence_claim.",
    ),
    (
        "equivalence_justification_too_short",
        "State, in a sentence, which observable output the mutated behaviour "
        "cannot reach. A word is not a justification.",
    ),
    (
        "timeout_",
        "The home did not finish inside timeout_seconds. Raise it or narrow the "
        "home, then re-run: a timeout measured nothing.",
    ),
    (
        "runner_fault_rc_",
        "pytest exited with a code that carries no result. Fix the invocation "
        "before reading anything into it.",
    ),
    (
        "interrupted_",
        "The run was interrupted and the tree was restored. Re-run it.",
    ),
)

_NEXT_STEP_BY_VERDICT: Mapping[str, str] = {
    "kill": (
        "Record this mutant, its home and its digest in the mutation table of "
        "the delivery report."
    ),
    "survive": (
        "The home does not pin this behaviour. Strengthen a test until this "
        "mutant reds, or state equivalence_claim -- which annotates the "
        "survivor and never turns it into a kill."
    ),
    "survive_narrow": (
        "Re-run this mutant with home.declared=full and no nodes before "
        "reporting anything about it: a survivor in a narrowed home is unknown, "
        "not survived."
    ),
    "void": ("Nothing ran. Fix the home and re-run; do not report this mutant."),
    "error": ("The mutant was not measured. Read reason, fix the cause and re-run."),
}


def next_step(verdict: Verdict, reason: str) -> str:
    """The single deterministic action this outcome obliges."""
    for prefix, step in _NEXT_STEP_BY_REASON:
        if reason.startswith(prefix):
            return step
    return _NEXT_STEP_BY_VERDICT[verdict.value]


class PlanError(Exception):
    """The plan does not describe a runnable mutation battery."""


class MutationError(Exception):
    """A mutant could not be measured; ``reason`` names the refusal."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Interrupted(BaseException):
    """A termination signal, re-shaped so the restore path cannot be skipped."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Home:
    """The declared test population a mutant is measured against."""

    declared: str
    nodes: tuple[str, ...]

    @property
    def kind(self) -> str:
        """The home width derived from the arguments, not from the claim."""
        return "narrow" if self.nodes else "full"


@dataclass(frozen=True)
class Mutant:
    """One edit, one home, one measurement."""

    identifier: str
    target: str
    find: str
    replace: str
    occurrence: int | None
    home: Home
    seeds: tuple[int, ...]
    timeout_seconds: float
    equivalence_claim: str | None


@dataclass(frozen=True)
class SeedRun:
    """One ``pytest`` invocation: its exit code and the tests it collected."""

    seed: int
    returncode: int
    collected: int | None
    failed: int
    errors: int


@dataclass(frozen=True)
class AppliedMutation:
    """The bytes needed to put the worktree back exactly as it was."""

    path: Path
    original: bytes
    mutated: bytes


@dataclass(frozen=True)
class Attempt:
    """Everything measured for one mutant, before a verdict is named."""

    baselines: tuple[SeedRun, ...]
    seeds: tuple[SeedRun, ...]
    original_sha256: str | None
    mutated_sha256: str | None
    failure: str | None
    refusal: tuple[Verdict, str] | None


@dataclass(frozen=True)
class Battery:
    """A finished battery: the report, its exit code and a one-line summary."""

    report: dict[str, object]
    exit_code: int
    summary: str


# One clean measurement of a home, keyed by its nodes and hash seed.
BaselineCache = dict[tuple[tuple[str, ...], int], SeedRun]


# ---------------------------------------------------------------------------
# Plan parsing.  Unknown keys are rejected: a typo must never become a default.
# ---------------------------------------------------------------------------


def _as_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise PlanError(f"{label} must be an object")
    return value


def _as_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise PlanError(f"{label} must be a string")
    return value


def _as_sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise PlanError(f"{label} must be an array")
    return value


def _as_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PlanError(f"{label} must be a number")
    return float(value)


def _as_index(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanError(f"{label} must be an integer")
    if value < 1:
        raise PlanError(f"{label} must be 1 or greater")
    return value


def _check_keys(
    payload: Mapping[str, object],
    allowed: frozenset[str],
    required: frozenset[str],
    label: str,
) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise PlanError(f"{label} has unknown keys: {', '.join(unknown)}")
    missing = sorted(required - set(payload))
    if missing:
        raise PlanError(f"{label} is missing keys: {', '.join(missing)}")


def _parse_home(value: object, label: str) -> Home:
    payload = _as_mapping(value, label)
    _check_keys(payload, _HOME_KEYS, frozenset({"declared"}), label)
    declared = _as_text(payload["declared"], f"{label}.declared")
    if declared not in _HOME_KINDS:
        raise PlanError(f"{label}.declared must be full or narrow")
    nodes = tuple(
        _as_text(node, f"{label}.nodes[]")
        for node in _as_sequence(payload.get("nodes", []), f"{label}.nodes")
    )
    home = Home(declared=declared, nodes=nodes)
    if home.kind != declared:
        raise PlanError(
            f"{label} declares {declared} but the node list makes it {home.kind}"
        )
    return home


def _parse_seeds(value: object, label: str) -> tuple[int, ...]:
    seeds = tuple(
        int(_as_number(seed, f"{label}[]")) for seed in _as_sequence(value, label)
    )
    if not seeds:
        raise PlanError(f"{label} must name at least one seed")
    if len(set(seeds)) != len(seeds):
        raise PlanError(f"{label} repeats a seed")
    return seeds


def _parse_mutant(value: object, label: str) -> Mutant:
    payload = _as_mapping(value, label)
    _check_keys(payload, _MUTANT_KEYS, _REQUIRED_MUTANT_KEYS, label)
    occurrence = payload.get("occurrence")
    claim = payload.get("equivalence_claim")
    return Mutant(
        identifier=_as_text(payload["id"], f"{label}.id"),
        target=_as_text(payload["target"], f"{label}.target"),
        find=_as_text(payload["find"], f"{label}.find"),
        replace=_as_text(payload["replace"], f"{label}.replace"),
        occurrence=(
            None if occurrence is None else _as_index(occurrence, f"{label}.occurrence")
        ),
        home=_parse_home(payload["home"], f"{label}.home"),
        seeds=(
            DEFAULT_SEEDS
            if "seeds" not in payload
            else _parse_seeds(payload["seeds"], f"{label}.seeds")
        ),
        timeout_seconds=_as_number(
            payload.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
            f"{label}.timeout_seconds",
        ),
        equivalence_claim=(
            None if claim is None else _as_text(claim, f"{label}.equivalence_claim")
        ),
    )


def load_plan(path: Path) -> tuple[Mutant, ...]:
    """Read a battery plan, refusing anything that is not fully declared."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PlanError(f"plan {path} is unreadable") from exc
    except json.JSONDecodeError as exc:
        raise PlanError(f"plan {path} is not valid JSON: {exc}") from exc
    payload = _as_mapping(raw, "plan")
    _check_keys(payload, frozenset({"mutants"}), frozenset({"mutants"}), "plan")
    entries = _as_sequence(payload["mutants"], "plan.mutants")
    if not entries:
        raise PlanError("plan.mutants must name at least one mutant")
    mutants = tuple(
        _parse_mutant(entry, f"plan.mutants[{index}]")
        for index, entry in enumerate(entries)
    )
    identifiers = [mutant.identifier for mutant in mutants]
    if len(set(identifiers)) != len(identifiers):
        raise PlanError("plan.mutants repeats a mutant id")
    return mutants


# ---------------------------------------------------------------------------
# Worktree state.  The unit of proof is the whole tree, never a list of files.
# ---------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def _digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_digest(path: Path) -> str:
    try:
        return _digest_bytes(path.read_bytes())
    except OSError:
        return "ABSENT"


def is_git_ignored(root: Path, relative: str) -> bool:
    """Whether git refuses to witness this path.

    ``git status`` never reports an ignored path, so a mutant planted in one
    would pass the restore proof without ever being looked at.  Such a target is
    refused rather than measured.
    """
    completed = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", "--", relative],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def _porcelain_entries(root: Path) -> tuple[tuple[str, str], ...]:
    """Every non-ignored path git reports as changed, with its status code."""
    fields = _git(root, "status", "--porcelain=v1", "-uall", "-z").split("\0")
    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if not entry:
            continue
        code = entry[:2]
        if code[0] in _RENAME_CODES:
            index += 1
        entries.append((code, entry[3:]))
    return tuple(sorted(entries, key=lambda item: item[1]))


def tree_state(root: Path) -> dict[str, str]:
    """Map every dirty or untracked path to its status code and content digest."""
    return {
        path: f"{code}:{_file_digest(root / path)}"
        for code, path in _porcelain_entries(root)
    }


def tree_witness(root: Path) -> str:
    """The human-readable ``git status --short`` witness for the whole worktree."""
    return _git(root, "status", "--short", "-uall")


def _state_difference(
    before: Mapping[str, str], after: Mapping[str, str]
) -> tuple[str, ...]:
    keys = sorted(set(before) | set(after))
    return tuple(key for key in keys if before.get(key) != after.get(key))


def purge_bytecode_caches(root: Path) -> int:
    """Remove every ``__pycache__`` under ``root``; returns how many were removed."""
    removed = 0
    for directory, subdirectories, _files in os.walk(root, topdown=True):
        subdirectories[:] = [
            name for name in subdirectories if name not in _CACHE_SKIP_DIRS
        ]
        if "__pycache__" in subdirectories:
            shutil.rmtree(Path(directory) / "__pycache__", ignore_errors=True)
            subdirectories.remove("__pycache__")
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# Applying exactly one edit, and proving it reached the disk.
# ---------------------------------------------------------------------------


def _nth_index(text: str, needle: str, occurrence: int) -> int:
    index = -1
    for _ in range(occurrence):
        index = text.index(needle, index + 1)
    return index


def _site_index(text: str, mutant: Mutant) -> int:
    """The offset of the single site this mutant names, or a typed refusal."""
    total = text.count(mutant.find)
    wanted = mutant.occurrence
    if total == 0:
        raise MutationError("find_not_found")
    if wanted is None and total > 1:
        raise MutationError("ambiguous_find")
    if wanted is not None and total < wanted:
        raise MutationError("occurrence_out_of_range")
    return _nth_index(text, mutant.find, wanted or 1)


def _substitute(text: str, mutant: Mutant) -> str:
    index = _site_index(text, mutant)
    return text[:index] + mutant.replace + text[index + len(mutant.find) :]


def _apply_mutation(root: Path, mutant: Mutant) -> AppliedMutation:
    path = (root / mutant.target).resolve()
    if root.resolve() not in path.parents:
        raise MutationError("target_outside_root")
    if not path.is_file():
        raise MutationError("target_not_a_file")
    if is_git_ignored(root, mutant.target):
        raise MutationError("target_is_git_ignored")
    original = path.read_bytes()
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MutationError("target_not_utf8") from exc
    mutated = _substitute(text, mutant).encode("utf-8")
    path.write_bytes(mutated)
    if _file_digest(path) == _digest_bytes(original):
        raise MutationError("mutation_not_applied")
    return AppliedMutation(path=path, original=original, mutated=mutated)


# ---------------------------------------------------------------------------
# Running the declared home and counting what it actually collected.
# ---------------------------------------------------------------------------


def _read_junit(path: Path) -> tuple[int | None, int, int]:
    try:
        document = ElementTree.parse(path)
        suites = list(document.getroot().iter("testsuite"))
        return (
            sum(int(suite.get("tests", "0")) for suite in suites),
            sum(int(suite.get("failures", "0")) for suite in suites),
            sum(int(suite.get("errors", "0")) for suite in suites),
        )
    except (OSError, ElementTree.ParseError, ValueError):
        return None, 0, 0


def _run_seed(root: Path, mutant: Mutant, seed: int) -> SeedRun:
    purge_bytecode_caches(root)
    with tempfile.TemporaryDirectory(prefix="mutation-harness-") as workspace:
        junit = Path(workspace) / "junit.xml"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit}",
            *mutant.home.nodes,
        ]
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = str(seed)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=mutant.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise MutationError(f"timeout_after_{mutant.timeout_seconds:g}s") from exc
        collected, failed, errors = _read_junit(junit)
    return SeedRun(
        seed=seed,
        returncode=completed.returncode,
        collected=collected,
        failed=failed,
        errors=errors,
    )


def _baseline_run(
    root: Path,
    mutant: Mutant,
    seed: int,
    cache: BaselineCache,
) -> SeedRun:
    """The home measured on the clean tree.

    Cached per home and seed: a battery only continues while the tree has been
    proven byte-identical between mutants, so one clean measurement stands.
    """
    key = (mutant.home.nodes, seed)
    cached = cache.get(key)
    if cached is not None:
        return cached
    run = _run_seed(root, mutant, seed)
    cache[key] = run
    return run


def _baseline_refusal(run: SeedRun) -> tuple[Verdict, str] | None:
    """Why no verdict is obtainable from this home, or ``None`` if it is sound."""
    if run.collected is None:
        return Verdict.VOID, "no_junit_report"
    if run.collected == 0:
        return Verdict.VOID, "no_tests_collected"
    if run.returncode not in (0, 1):
        return Verdict.ERROR, f"runner_fault_rc_{run.returncode}"
    if run.returncode == 1:
        return Verdict.ERROR, "home_already_red"
    return None


def _mutate_and_run(
    root: Path, mutant: Mutant, baselines: tuple[SeedRun, ...]
) -> Attempt:
    applied: AppliedMutation | None = None
    runs: tuple[SeedRun, ...] = ()
    failure: str | None = None
    try:
        applied = _apply_mutation(root, mutant)
        runs = tuple(_run_seed(root, mutant, seed) for seed in mutant.seeds)
    except (MutationError, Interrupted) as exc:
        failure = exc.reason
    finally:
        if applied is not None:
            applied.path.write_bytes(applied.original)
    return Attempt(
        baselines=baselines,
        seeds=runs,
        original_sha256=None if applied is None else _digest_bytes(applied.original),
        mutated_sha256=None if applied is None else _digest_bytes(applied.mutated),
        failure=failure,
        refusal=None,
    )


def _attempt(
    root: Path,
    mutant: Mutant,
    cache: BaselineCache,
) -> Attempt:
    try:
        baselines = tuple(
            _baseline_run(root, mutant, seed, cache) for seed in mutant.seeds
        )
    except (MutationError, Interrupted) as exc:
        return Attempt((), (), None, None, exc.reason, None)
    for run in baselines:
        refusal = _baseline_refusal(run)
        if refusal is not None:
            return Attempt(baselines, (), None, None, None, refusal)
    return _mutate_and_run(root, mutant, baselines)


# ---------------------------------------------------------------------------
# The decision table.  Every input combination maps to exactly one verdict.
# ---------------------------------------------------------------------------


def _seed_verdict(run: SeedRun, home: Home) -> tuple[Verdict, str]:
    if run.collected is None:
        return Verdict.VOID, "no_junit_report"
    if run.collected == 0:
        return Verdict.VOID, "no_tests_collected"
    if run.returncode not in (0, 1):
        return Verdict.ERROR, f"runner_fault_rc_{run.returncode}"
    if run.returncode == 1:
        return Verdict.KILL, "tests_failed"
    if home.kind == "narrow":
        return Verdict.SURVIVE_NARROW, "narrow_home_stayed_green"
    return Verdict.SURVIVE, "full_home_stayed_green"


def _aggregate(outcomes: Sequence[tuple[Verdict, str]]) -> tuple[Verdict, str]:
    verdict, reason = min(outcomes, key=lambda item: _SEVERITY.index(item[0]))
    if len({outcome[0] for outcome in outcomes}) > 1:
        return verdict, "unstable_across_seeds"
    return verdict, reason


def _with_equivalence(
    verdict: Verdict, reason: str, claim: str | None
) -> tuple[Verdict, str]:
    """An equivalence claim annotates a survivor; it never improves a verdict."""
    if claim is None:
        return verdict, reason
    if len(claim.strip()) < MIN_EQUIVALENCE_JUSTIFICATION:
        return Verdict.ERROR, "equivalence_justification_too_short"
    if verdict not in (Verdict.SURVIVE, Verdict.SURVIVE_NARROW):
        return Verdict.ERROR, "equivalence_claim_without_survivor"
    return verdict, reason


def _decide(
    mutant: Mutant, attempt: Attempt, residual: Sequence[str]
) -> tuple[Verdict, str]:
    if residual:
        return Verdict.ERROR, "tree_not_restored"
    if attempt.failure is not None:
        return Verdict.ERROR, attempt.failure
    if attempt.refusal is not None:
        return attempt.refusal
    outcomes = [_seed_verdict(run, mutant.home) for run in attempt.seeds]
    verdict, reason = _aggregate(outcomes)
    return _with_equivalence(verdict, reason, mutant.equivalence_claim)


# ---------------------------------------------------------------------------
# The report.  Its digest is the machine evidence a controller can re-derive.
# ---------------------------------------------------------------------------


def _seed_payload(run: SeedRun, home: Home) -> dict[str, object]:
    verdict, reason = _seed_verdict(run, home)
    return {
        "seed": run.seed,
        "returncode": run.returncode,
        "collected": run.collected,
        "failed": run.failed,
        "errors": run.errors,
        "verdict": verdict.value,
        "reason": reason,
    }


def canonical_digest(payload: Mapping[str, object]) -> str:
    """A sha256 over the machine-stable part of a report."""
    serialized = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _stable_payload(
    base_commit: str,
    mutant: Mutant,
    attempt: Attempt,
    verdict: Verdict,
    reason: str,
    restored: bool,
) -> dict[str, object]:
    return {
        "protocol": PROTOCOL_VERSION,
        "base_commit": base_commit,
        "id": mutant.identifier,
        "target": mutant.target,
        "find": mutant.find,
        "replace": mutant.replace,
        "occurrence": mutant.occurrence,
        "home": {
            "declared": mutant.home.declared,
            "kind": mutant.home.kind,
            "nodes": list(mutant.home.nodes),
        },
        "original_sha256": attempt.original_sha256,
        "mutated_sha256": attempt.mutated_sha256,
        "baselines": [_seed_payload(run, mutant.home) for run in attempt.baselines],
        "seeds": [_seed_payload(run, mutant.home) for run in attempt.seeds],
        "verdict": verdict.value,
        "reason": reason,
        "equivalence_claimed": mutant.equivalence_claim is not None,
        "restore_verified": restored,
    }


def run_mutant(
    root: Path, mutant: Mutant, base_commit: str, cache: BaselineCache
) -> dict[str, object]:
    """Measure one mutant end to end and return its report."""
    before_state = tree_state(root)
    before_witness = tree_witness(root)
    attempt = _attempt(root, mutant, cache)
    residual = _state_difference(before_state, tree_state(root))
    verdict, reason = _decide(mutant, attempt, residual)
    stable = _stable_payload(
        base_commit, mutant, attempt, verdict, reason, not residual
    )
    return {
        **stable,
        "digest": canonical_digest(stable),
        "exit_code": _EXIT_CODE[verdict],
        "next_step": next_step(verdict, reason),
        "residual_paths": list(residual),
        "equivalence": {
            "claimed": mutant.equivalence_claim is not None,
            "justification": mutant.equivalence_claim,
        },
        "checks": {
            "home_baseline_green": attempt.refusal is None and not attempt.failure,
            "mutation_applied": attempt.mutated_sha256 is not None,
            "collection_counted": bool(attempt.seeds)
            and all(run.collected is not None for run in attempt.seeds),
            "restore_verified": not residual,
        },
        "tree_witness_before": before_witness,
        "tree_witness_after": tree_witness(root),
    }


# ---------------------------------------------------------------------------
# The battery.  One mutation is live at a time, and the tree is re-proven between.
# ---------------------------------------------------------------------------


def _preflight(root: Path) -> str:
    if not root.is_dir():
        raise MutationError("root_not_a_directory")
    try:
        return _git(root, "rev-parse", "HEAD").strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise MutationError("git_unavailable") from exc


def _battery_verdict(reports: Sequence[Mapping[str, object]]) -> Verdict:
    verdicts = [Verdict(str(report["verdict"])) for report in reports]
    return min(verdicts, key=_SEVERITY.index)


def _summarize(reports: Sequence[Mapping[str, object]], verdict: Verdict) -> str:
    lines: list[str] = []
    for report in reports:
        lines.append(f"{report['id']}: {report['verdict']} ({report['reason']})")
        if report["verdict"] != Verdict.KILL.value:
            lines.append(f"    next step: {report['next_step']}")
    lines.append(f"battery: {verdict.value} -> exit {_EXIT_CODE[verdict]}")
    return "\n".join(lines)


def run_battery(root: Path, mutants: Sequence[Mutant]) -> Battery:
    """Run every mutant in turn, refusing to continue on an unproven worktree."""
    try:
        base_commit = _preflight(root)
    except MutationError as exc:
        return _refused_battery(exc.reason)
    opening = tree_state(root)
    cache: BaselineCache = {}
    reports: list[dict[str, object]] = []
    for mutant in mutants:
        report = run_mutant(root, mutant, base_commit, cache)
        reports.append(report)
        if report["residual_paths"]:
            break
    drift = _state_difference(opening, tree_state(root))
    verdict = _battery_verdict(reports)
    if drift:
        verdict = Verdict.ERROR
    payload: dict[str, object] = {
        "protocol": PROTOCOL_VERSION,
        "base_commit": base_commit,
        "verdict": verdict.value,
        "exit_code": _EXIT_CODE[verdict],
        "residual_paths": list(drift),
        "tree_clean": not drift,
        "tree_witness_after": tree_witness(root),
        "mutants": reports,
    }
    payload["digest"] = canonical_digest(
        {
            "protocol": PROTOCOL_VERSION,
            "base_commit": base_commit,
            "verdict": verdict.value,
            "mutants": [report["digest"] for report in reports],
        }
    )
    return Battery(payload, _EXIT_CODE[verdict], _summarize(reports, verdict))


def _refused_battery(reason: str) -> Battery:
    payload: dict[str, object] = {
        "protocol": PROTOCOL_VERSION,
        "verdict": Verdict.ERROR.value,
        "reason": reason,
        "exit_code": _EXIT_CODE[Verdict.ERROR],
        "mutants": [],
    }
    payload["digest"] = canonical_digest(payload)
    return Battery(payload, _EXIT_CODE[Verdict.ERROR], f"battery refused: {reason}")


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


def _raise_interrupt(signum: int, _frame: FrameType | None) -> NoReturn:
    raise Interrupted(f"interrupted_by_signal_{signum}")


def _install_interrupt_guard() -> None:
    """Turn termination signals into an exception the restore path must catch."""
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, _raise_interrupt)


PLAN_TEMPLATE = """\
{
  "mutants": [
    {
      "id": "m01-short-name-of-what-you-broke",
      "target": "codeclone/some/module.py",
      "find": "the exact source text to replace, matching exactly one site",
      "replace": "the text that breaks the behaviour the test claims to pin",
      "occurrence": null,
      "home": {"declared": "full", "nodes": []},
      "seeds": [0],
      "timeout_seconds": 1800,
      "equivalence_claim": null
    }
  ]
}

home is declared, never inferred.  A full home names no nodes; a narrow home
names pytest node ids or paths and can only ever yield survive_narrow.
occurrence, seeds, timeout_seconds and equivalence_claim may be omitted.
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="Run with --protocol for the full protocol and a plan template.",
    )
    parser.add_argument("--root", default=None, help="absolute worktree root")
    parser.add_argument("--plan", default=None, help="battery plan, JSON")
    parser.add_argument("--report", default=None, help="write the JSON report here")
    parser.add_argument(
        "--protocol",
        action="store_true",
        help="print the protocol and a plan template, then exit",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a battery plan and return the exit code its worst verdict earns."""
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    if arguments.protocol:
        print(f"{__doc__}\n{PLAN_TEMPLATE}")
        return 0
    missing = [name for name in ("root", "plan") if getattr(arguments, name) is None]
    if missing:
        print(
            f"--{' and --'.join(missing)} required; --protocol explains the plan",
            file=sys.stderr,
        )
        return _EXIT_CODE[Verdict.ERROR]
    try:
        mutants = load_plan(Path(arguments.plan))
    except PlanError as exc:
        print(f"plan rejected: {exc}", file=sys.stderr)
        return _EXIT_CODE[Verdict.ERROR]
    _install_interrupt_guard()
    battery = run_battery(Path(arguments.root), mutants)
    serialized = json.dumps(battery.report, indent=2, sort_keys=True)
    print(serialized)
    if arguments.report is not None:
        Path(arguments.report).write_text(serialized + "\n", encoding="utf-8")
    print(battery.summary, file=sys.stderr)
    return battery.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
